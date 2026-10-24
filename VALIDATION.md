# Matching pipeline validation (real FIRMS data)

## What was wrong with greedy matching

The original `calibrate.py` matched MODIS↔VIIRS greedily: for each MODIS
row in file order, take the nearest unused VIIRS pixel within 1.0 km and
12 h, ignoring FRP entirely. On real data this collapses for four
concrete reasons, all measured on the run below:

1. **Density imbalance.** VIIRS 375 m resolves far more detections than
   MODIS 1 km (here 8,870 vs 320 in the same region/days, ~28:1), so
   inside a fire front the "nearest" VIIRS pixel is arbitrary, not the
   same fire.
2. **No FRP check.** Distance-only pairing happily matches a 5 MW VIIRS
   pixel to a 500 MW MODIS pixel.
3. **12 h window is too loose.** Overpasses differ (Terra ~10:30,
   Aqua / S-NPP ~13:30 local) and fires evolve, so same-cell detections
   hours apart are often different fires or burn stages.
4. **File-order dependence.** Whichever MODIS row came first grabbed the
   best VIIRS pixel; later rows got leftovers. Greedy's Spearman rank
   correlation on matched FRP was only 0.281 on this dataset.

## New matcher (`calibrate.py`)

1. Grid-bucketed candidate generation (no O(n²) scan — required at
   VIIRS densities; a naive all-pairs scan over this dataset is ~2.8M
   distance computations in pure Python).
2. Hard gates: distance ≤ 1.5 km, |Δt| ≤ 3 h, FRP ratio in [0.05, 3.0].
   The ratio band is wide on purpose: per-pixel VIIRS FRP runs
   systematically below MODIS FRP (median ratio 0.345 here), because a
   1 km MODIS pixel aggregates a front that VIIRS splits into 375 m
   pixels.
3. Global one-to-one assignment (Hungarian, `scipy.optimize`) minimising
   `0.5·(dist/1.5 km) + 1.0·(|Δt|/3 h) + 1.0·|log10(ratio/0.35)|`.
   Distance is deliberately down-weighted: for an extended front the
   closest VIIRS pixel is often not the same fire, while time
   coincidence and FRP consistency discriminate better. Without scipy,
   the code falls back to global cost-sorted greedy with one-to-one
   enforcement (same gates and cost).
4. Unmatched detections are dropped, never forced into pairs.

## Validation run (2026-10-24)

- **Data:** live NASA FIRMS area API, Zambia bbox 22,−18,34,−8,
  last 2 days (2026-10-23 full day + 2026-10-24 partial day; the fetch
  ran before the 10-24 afternoon overpass, so 10-24 is incomplete).
- **Inputs:** MODIS_NRT 320 detections, VIIRS_SNPP_NRT 8,870 detections.
- **New matcher:** 144 matched pairs, match rate 0.450,
  **FRP Pearson r = 0.885, Spearman ρ = 0.740**,
  mean MODIS FRP 51.69 MW, mean VIIRS FRP 17.53 MW,
  median VIIRS/MODIS ratio 0.345.
- **Same-data greedy replica** (old 1.0 km / 12 h rule, file order):
  166 pairs, Pearson r = 0.562, Spearman ρ = 0.281.
- **Old reported baseline:** the previous session's Zambia 2-day run
  (MODIS 824, VIIRS 3,461, 402 naive pairs) gave Pearson r = 0.048.
  Different days, so the apples-to-apples comparison is the same-data
  replica above; on either baseline the new matcher is clearly above
  the failed level.
- **Full-day subset (2026-10-23 only):** 120 pairs, Pearson r = 0.880,
  Spearman ρ = 0.625 — the result is stable, not a one-day fluke.
  The partial 10-24 subset alone is noisy for every method (n ≈ 24)
  because the afternoon overpass had not been downloaded yet; it is
  not a matcher failure.

## Reproduce

```bash
pip install -r requirements.txt   # adds scipy for the Hungarian step
python fetch_firms.py --region 22,-18,34,-8 --days 2   # needs FIRMS_MAP_KEY
python calibrate.py --input data/firms_MODIS_NRT_*.csv data/firms_VIIRS_SNPP_NRT_*.csv
```

## Files changed in this update

- `calibrate.py` — greedy matcher replaced (this file's docstring
  explains the change); CLI flags and `matched_pairs.csv` output kept.
- `requirements.txt` — added `scipy` (Hungarian assignment).
- `VALIDATION.md` — this record.
- Untouched: `fetch_firms.py`, `app.py`, `README.md`,
  `data/sample_fires.csv`.
