#!/usr/bin/env python3
"""Cross-calibration: match MODIS vs VIIRS hotspots and compare FRP.

Replaces the original greedy nearest-neighbour matcher. Why greedy failed
on real FIRMS data (Zambia, Oct 2026; see VALIDATION.md):

  * Density imbalance: VIIRS 375 m resolves ~4-28x more detections than
    MODIS 1 km in the same fire area, so "nearest VIIRS pixel" is
    arbitrary inside a fire front, not the same fire.
  * No FRP check: greedy paired purely on distance, so a 5 MW VIIRS
    pixel could match a 500 MW MODIS pixel.
  * 12 h time window: fires evolve and overpasses differ (Terra ~10:30,
    Aqua / S-NPP ~13:30 local), so same-cell detections hours apart are
    often different fires or different burn stages.
  * File-order dependence: whichever MODIS row came first grabbed the
    best VIIRS pixel; later rows got leftovers.

New matcher (validated on real FIRMS data, VALIDATION.md):

  1. Grid-bucketed candidate generation (no O(n^2) scan).
  2. Hard gates: distance <= 1.5 km, |dt| <= 3 h, FRP ratio in
     [0.05, 3.0]. The ratio band is wide on purpose: per-pixel VIIRS
     FRP runs systematically below MODIS FRP (median ratio ~0.35 in
     validation), because a 1 km MODIS pixel aggregates a front that
     VIIRS splits into 375 m pixels.
  3. Global one-to-one assignment (Hungarian) minimising
         cost = 0.5 * (dist / 1.5 km) + 1.0 * (|dt| / 3 h)
                + 1.0 * |log10(VIIRS_FRP / MODIS_FRP / 0.35)|
     Distance is deliberately down-weighted: for an extended fire
     front the closest VIIRS pixel is often not the same fire, while
     time coincidence and FRP consistency discriminate better.
     If scipy is unavailable, falls back to a global cost-sorted
     greedy with one-to-one enforcement (same gates and cost).
  4. Unmatched detections are dropped, never forced into pairs.

Usage:
    python calibrate.py                      # uses data/sample_fires.csv
    python calibrate.py --input data/firms_MODIS_NRT_*.csv data/firms_VIIRS_SNPP_NRT_*.csv
                                             # one or more files are merged
"""
import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
SAMPLE = BASE_DIR / "data" / "sample_fires.csv"

# --- matcher defaults (validated on real FIRMS data, see VALIDATION.md) ---
MAX_DIST_KM = 1.5
MAX_DT_HOURS = 3.0
FRP_RATIO_MIN = 0.05
FRP_RATIO_MAX = 3.0
FRP_RATIO_REF = 0.35  # median VIIRS/MODIS per-pixel FRP ratio in validation
W_DIST, W_TIME, W_FRP = 0.5, 1.0, 1.0


def load_fires(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"acq_time": str, "acq_date": str})
    df["acq_time"] = df["acq_time"].str.zfill(4)
    df["acq_datetime"] = pd.to_datetime(
        df["acq_date"] + " " + df["acq_time"].str.zfill(4).str[:2]
        + ":" + df["acq_time"].str.zfill(4).str[2:],
        errors="coerce",
    )
    df["sensor"] = df["instrument"].str.upper().map(
        {"MODIS": "MODIS", "VIIRS": "VIIRS"}).fillna(df["instrument"])
    return df


def _candidate_pairs(modis: pd.DataFrame, viirs: pd.DataFrame,
                     max_dist_km: float, max_dt_hours: float):
    """All (modis_row, viirs_row, dist_km, dt_h) within the space/time gates.

    Grid-bucketed: VIIRS points are hashed into ~max_dist_km cells, so each
    MODIS point only checks its own and neighbouring cells instead of the
    full VIIRS set (no O(n^2) scan; this matters at VIIRS densities).
    """
    if modis.empty or viirs.empty:
        return []
    cell = max(max_dist_km / 111.0, 1e-6)
    buckets = defaultdict(list)
    for j, v in viirs.iterrows():
        buckets[(int(v.latitude // cell), int(v.longitude // cell))].append(j)
    t0 = pd.Timestamp("2026-01-01")
    v_t = ((viirs["acq_datetime"] - t0).dt.total_seconds() / 3600).to_numpy()
    v_lat = np.radians(viirs["latitude"].to_numpy())
    v_lon = np.radians(viirs["longitude"].to_numpy())
    v_index = viirs.index.to_numpy()
    pos_of = {idx: k for k, idx in enumerate(v_index)}
    pairs = []
    for i, mrow in modis.iterrows():
        lat1, lon1 = math.radians(mrow.latitude), math.radians(mrow.longitude)
        m_t = (mrow["acq_datetime"] - t0).total_seconds() / 3600
        dlat = max_dist_km / 111.0
        dlon = max_dist_km / (111.0 * max(abs(math.cos(lat1)), 0.2))
        js = []
        for ci in range(int((mrow.latitude - dlat) // cell),
                        int((mrow.latitude + dlat) // cell) + 1):
            for cj in range(int((mrow.longitude - dlon) // cell),
                            int((mrow.longitude + dlon) // cell) + 1):
                js.extend(buckets.get((ci, cj), []))
        if not js:
            continue
        ks = np.array([pos_of[j] for j in js])
        dp = v_lat[ks] - lat1
        dl = v_lon[ks] - lon1
        a = np.sin(dp / 2) ** 2 + math.cos(lat1) * np.cos(v_lat[ks]) * np.sin(dl / 2) ** 2
        dist = 2 * 6371.0 * np.arcsin(np.sqrt(a))
        dt = np.abs(v_t[ks] - m_t)
        for pos, j in enumerate(js):
            if dist[pos] <= max_dist_km and dt[pos] <= max_dt_hours:
                pairs.append((i, j, float(dist[pos]), float(dt[pos])))
    return pairs


def _assign(cands, modis, viirs, w_dist, w_time, w_frp):
    """Global one-to-one assignment over candidate pairs.

    Returns a list of (modis_row, viirs_row, dist_km, dt_h, cost).
    Prefers scipy's Hungarian algorithm; falls back to global cost-sorted
    greedy with one-to-one enforcement when scipy is missing.
    """
    if not cands:
        return []
    m_frp = modis["frp"].to_dict()
    v_frp = viirs["frp"].to_dict()
    scored = []
    for (i, j, d, dt) in cands:
        mf, vf = m_frp.get(i), v_frp.get(j)
        if mf is None or vf is None or not np.isfinite(mf) or not np.isfinite(vf):
            continue
        if mf <= 0 or vf <= 0:
            continue
        ratio = vf / mf
        if ratio < FRP_RATIO_MIN or ratio > FRP_RATIO_MAX:
            continue
        cost = (w_dist * (d / MAX_DIST_KM) + w_time * (dt / MAX_DT_HOURS)
                + w_frp * abs(math.log10(ratio / FRP_RATIO_REF)))
        scored.append((i, j, d, dt, cost))
    if not scored:
        return []
    try:
        from scipy.optimize import linear_sum_assignment
    except ImportError:
        used_m, used_v, out = set(), set(), []
        for (i, j, d, dt, cost) in sorted(scored, key=lambda r: r[4]):
            if i in used_m or j in used_v:
                continue
            used_m.add(i)
            used_v.add(j)
            out.append((i, j, d, dt, cost))
        return out
    mis = sorted({s[0] for s in scored})
    vjs = sorted({s[1] for s in scored})
    mi_idx = {x: k for k, x in enumerate(mis)}
    vj_idx = {x: k for k, x in enumerate(vjs)}
    big = 1e9
    cost_m = np.full((len(mis), len(vjs)), big)
    lookup = {}
    for (i, j, d, dt, cost) in scored:
        cost_m[mi_idx[i], vj_idx[j]] = cost
        lookup[(i, j)] = (d, dt, cost)
    ri, ci = linear_sum_assignment(cost_m)
    out = []
    for a, b in zip(ri, ci):
        if cost_m[a, b] < big / 2:
            i, j = mis[a], vjs[b]
            d, dt, cost = lookup[(i, j)]
            out.append((i, j, d, dt, cost))
    return out


def match_hotspots(df: pd.DataFrame,
                   spatial_tol_km: float = MAX_DIST_KM,
                   time_tol_hours: float = MAX_DT_HOURS) -> pd.DataFrame:
    """Hungarian one-to-one MODIS<->VIIRS matching with space/time/FRP gates.

    Unmatched detections are dropped, never forced into pairs.
    """
    modis = df[df["sensor"] == "MODIS"]
    viirs = df[df["sensor"] == "VIIRS"]
    cands = _candidate_pairs(modis, viirs, spatial_tol_km, time_tol_hours)
    assigned = _assign(cands, modis, viirs, W_DIST, W_TIME, W_FRP)
    pairs = []
    for (i, j, d, dt, _cost) in assigned:
        mrow = modis.loc[i]
        vrow = viirs.loc[j]
        pairs.append({
            "modis_idx": i, "viirs_idx": j,
            "dist_km": round(d, 3), "dt_hours": round(dt, 2),
            "modis_frp": mrow.frp, "viirs_frp": vrow.frp,
            "frp_ratio": round(vrow.frp / mrow.frp, 3) if mrow.frp else float("nan"),
            "modis_time": str(mrow.acq_datetime), "viirs_time": str(vrow.acq_datetime),
        })
    return pd.DataFrame(pairs)


def compare_frp(pairs: pd.DataFrame) -> dict:
    """FRP comparison on matched pairs."""
    if pairs.empty:
        return {"n_matched": 0}
    out = {
        "n_matched": len(pairs),
        "mean_modis_frp": round(pairs.modis_frp.mean(), 2),
        "mean_viirs_frp": round(pairs.viirs_frp.mean(), 2),
        "mean_bias_viirs_minus_modis": round(
            (pairs.viirs_frp - pairs.modis_frp).mean(), 2),
        "mean_ratio_viirs_over_modis": round(
            (pairs.viirs_frp / pairs.modis_frp.replace(0, float("nan"))).mean(), 3),
        "median_ratio_viirs_over_modis": round(
            (pairs.viirs_frp / pairs.modis_frp.replace(0, float("nan"))).median(), 3),
        "pearson_r": round(pairs[["modis_frp", "viirs_frp"]].corr().iloc[0, 1], 3),
    }
    try:
        from scipy.stats import spearmanr
        out["spearman_rho"] = round(
            spearmanr(pairs.modis_frp, pairs.viirs_frp).statistic, 3)
    except Exception:
        pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="MODIS/VIIRS cross-calibration")
    ap.add_argument("--input", nargs="+", default=[str(SAMPLE)],
                    help="one or more FIRMS CSVs (merged automatically)")
    ap.add_argument("--spatial-tol-km", type=float, default=MAX_DIST_KM)
    ap.add_argument("--time-tol-hours", type=float, default=MAX_DT_HOURS)
    args = ap.parse_args()

    frames = []
    for pth in args.input:
        frames.append(load_fires(Path(pth)))
    df = pd.concat(frames, ignore_index=True)
    src = ", ".join(args.input)
    n_modis = (df.sensor == "MODIS").sum()
    n_viirs = (df.sensor == "VIIRS").sum()
    print(f"[calibrate] loaded {len(df)} detections "
          f"({n_modis} MODIS, {n_viirs} VIIRS) from {src}")

    pairs = match_hotspots(df, args.spatial_tol_km, args.time_tol_hours)
    stats = compare_frp(pairs)
    stats["n_modis"] = int(n_modis)
    stats["n_viirs"] = int(n_viirs)
    stats["match_rate"] = (round(stats["n_matched"] / n_modis, 3)
                           if n_modis else 0.0)

    print("[calibrate] FRP comparison (matched pairs):")
    for k, v in stats.items():
        print(f"    {k}: {v}")

    out = BASE_DIR / "data" / "matched_pairs.csv"
    pairs.to_csv(out, index=False)
    print(f"[calibrate] wrote {out.name} ({len(pairs)} pairs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
