#!/usr/bin/env python3
"""Cross-calibration scaffold: match MODIS vs VIIRS hotspots and compare FRP.

This is a STARTING POINT, not the final model. It does:
  1. load FIRMS-style CSVs (downloaded or data/sample_fires.csv)
  2. greedy spatio-temporal matching of MODIS <-> VIIRS detections
  3. a first-look FRP comparison (bias, ratio, correlation)

48-HOUR TODOs (marked TODO below):
  - detection-efficiency weighting (VIIRS 375m sees smaller fires than MODIS 1km)
  - diurnal-cycle correction (Terra ~10:30 / Aqua & VIIRS ~13:30 overpasses)
  - a real calibration model, e.g. regress VIIRS FRP on MODIS FRP per biome
  - gridded "burning activity calendar" aggregation for the web app

Usage:
    python calibrate.py                      # uses data/sample_fires.csv
    python calibrate.py --input data/firms_MODIS_NRT_*.csv data/firms_VIIRS_SNPP_NRT_*.csv
                                             # one or more files are merged
"""
import argparse
import math
import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
SAMPLE = BASE_DIR / "data" / "sample_fires.csv"


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


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def match_hotspots(df: pd.DataFrame,
                   spatial_tol_km: float = 1.0,
                   time_tol_hours: float = 12.0) -> pd.DataFrame:
    """Greedy nearest-neighbour MODIS<->VIIRS matching.

    TODO(48h): replace greedy matching with overpass-coincident windows
    (match only detections from near-simultaneous Terra/Aqua vs S-NPP passes)
    and add a proper one-to-many handling for clustered fire fronts.
    """
    modis = df[df["sensor"] == "MODIS"].reset_index(drop=True)
    viirs = df[df["sensor"] == "VIIRS"].reset_index(drop=True)
    used = set()
    pairs = []
    for i, m in modis.iterrows():
        best, best_d = None, None
        for j, v in viirs.iterrows():
            if j in used:
                continue
            d = haversine_km(m.latitude, m.longitude, v.latitude, v.longitude)
            dt = abs((m.acq_datetime - v.acq_datetime).total_seconds()) / 3600
            if d <= spatial_tol_km and dt <= time_tol_hours:
                if best_d is None or d < best_d:
                    best, best_d = j, d
        if best is not None:
            used.add(best)
            v = viirs.loc[best]
            pairs.append({
                "modis_idx": i, "viirs_idx": best,
                "dist_km": round(best_d, 3),
                "modis_frp": m.frp, "viirs_frp": v.frp,
                "modis_time": str(m.acq_datetime), "viirs_time": str(v.acq_datetime),
            })
    return pd.DataFrame(pairs)


def compare_frp(pairs: pd.DataFrame) -> dict:
    """First-look FRP comparison on matched pairs."""
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
        "pearson_r": round(pairs[["modis_frp", "viirs_frp"]].corr().iloc[0, 1], 3),
    }
    # TODO(48h): fit the actual cross-calibration here, e.g.
    #   log(viirs_frp) = a + b * log(modis_frp)  per land-cover class,
    #   then apply the inverse to build one harmonized FRP series.
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="MODIS/VIIRS cross-calibration scaffold")
    ap.add_argument("--input", nargs="+", default=[str(SAMPLE)],
                    help="one or more FIRMS CSVs (merged automatically)")
    ap.add_argument("--spatial-tol-km", type=float, default=1.0)
    ap.add_argument("--time-tol-hours", type=float, default=12.0)
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
    print("[calibrate] NOTE: scaffold only — see TODO(48h) markers for the real model.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
