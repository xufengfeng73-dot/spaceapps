#!/usr/bin/env python3
"""Download NASA FIRMS active-fire data (MODIS C6.1 + VIIRS 375m) as CSV.

Usage:
    python fetch_firms.py --map-key YOUR_KEY
    python fetch_firms.py --map-key YOUR_KEY --region -125,32,-114,42 --days 3
    FIRMS_MAP_KEY=YOUR_KEY python fetch_firms.py

Without a MAP_KEY the script does NOT fail: it falls back to the bundled
demo file data/sample_fires.csv and prints instructions for getting a free key.

Get a free FIRMS MAP_KEY here (email request, usually issued instantly):
    https://firms.modaps.eosdis.nasa.gov/api/area/
"""
import argparse
import os
import sys
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SAMPLE = DATA_DIR / "sample_fires.csv"

API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{product}/{region}/{days}"

# MODIS Collection 6.1 and VIIRS 375m (Suomi-NPP). NOAA-20 available as
# VIIRS_NOAA20_NRT via --products if you want a third stream.
# Current FIRMS area-API product names (verified 2026-10-20).
# MODIS_C6_1 is retired ("Invalid source"); use MODIS_NRT.
DEFAULT_PRODUCTS = ["MODIS_NRT", "VIIRS_SNPP_NRT"]

SENSOR_OF = {"MODIS_NRT": "MODIS", "VIIRS_SNPP_NRT": "VIIRS",
             "VIIRS_NOAA20_NRT": "VIIRS", "VIIRS_NOAA21_NRT": "VIIRS"}


def download(map_key: str, product: str, region: str, days: int) -> Path:
    url = API.format(key=map_key, product=product, region=region, days=days)
    print(f"[fetch] {product}  region={region} days={days}")
    try:
        r = requests.get(url, timeout=60)
    except requests.RequestException as e:
        raise RuntimeError(f"network error contacting FIRMS: {e}")
    if r.status_code != 200:
        raise RuntimeError(f"FIRMS returned HTTP {r.status_code}: {r.text[:200]}")
    text = r.text.strip()
    if not text or text.startswith("<") or "Invalid" in text[:200]:
        raise RuntimeError(f"FIRMS did not return CSV data: {text[:200]}")
    out = DATA_DIR / f"firms_{product}_{region.replace(',', '_')}_{days}d.csv"
    out.write_text(text, encoding="utf-8")
    n_rows = max(len(text.splitlines()) - 1, 0)
    print(f"[fetch] saved {out.name}  ({n_rows} detections)")
    return out


def fallback(reason: str) -> int:
    print(f"[fetch] Download skipped: {reason}")
    print(f"[fetch] Falling back to bundled demo data: {SAMPLE.name}")
    print()
    print("To use live NASA data, get a FREE FIRMS MAP_KEY:")
    print("  1. Open https://firms.modaps.eosdis.nasa.gov/api/area/")
    print("  2. Enter your email -> you receive a MAP_KEY (usually instantly).")
    print("  3. Re-run:  FIRMS_MAP_KEY=<your key> python fetch_firms.py")
    print()
    print("NOTE: sample_fires.csv is SYNTHETIC demo data for pipeline testing only.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Download FIRMS active-fire CSVs.")
    ap.add_argument("--map-key", default=os.environ.get("FIRMS_MAP_KEY"),
                    help="FIRMS MAP_KEY (or set env FIRMS_MAP_KEY)")
    ap.add_argument("--region", default="world",
                    help="'world' or lon_min,lat_min,lon_max,lat_max "
                         "(e.g. -125,32,-114,42)")
    ap.add_argument("--days", type=int, default=1,
                    help="day range 1-10 (default 1)")
    ap.add_argument("--products", nargs="+", default=DEFAULT_PRODUCTS,
                    help="FIRMS product names (default: MODIS_C6_1 VIIRS_SNPP_NRT)")
    args = ap.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    if not args.map_key:
        return fallback("no MAP_KEY provided")
    if not (1 <= args.days <= 10):
        return fallback(f"--days must be 1-10 (got {args.days})")

    ok, failed = [], []
    for product in args.products:
        try:
            ok.append(download(args.map_key, product, args.region, args.days))
        except RuntimeError as e:
            print(f"[fetch] ERROR for {product}: {e}")
            failed.append(product)

    if failed and not ok:
        return fallback(f"all downloads failed ({', '.join(failed)})")
    if failed:
        print(f"[fetch] WARNING: {len(failed)} product(s) failed, "
              f"{len(ok)} saved. Continuing with what we have.")
    print("[fetch] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
