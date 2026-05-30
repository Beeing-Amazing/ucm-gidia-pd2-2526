"""To run this script, you need the optional project dependencies: `download`"""

import asyncio
import json
from pathlib import Path

import httpx
import pandas as pd
import requests
from shapely import wkt
from shapely.geometry import Point
from tqdm import tqdm

from scripts import project_root, TAXI_ZONE

BOROUGHS = {
    "manhattan": "https://www.nyc.gov/assets/finance/downloads/pdf/rolling_sales/rollingsales_manhattan.xlsx",
    "bronx":     "https://www.nyc.gov/assets/finance/downloads/pdf/rolling_sales/rollingsales_bronx.xlsx",
    "brooklyn":  "https://www.nyc.gov/assets/finance/downloads/pdf/rolling_sales/rollingsales_brooklyn.xlsx",
    "queens":    "https://www.nyc.gov/assets/finance/downloads/pdf/rolling_sales/rollingsales_queens.xlsx",
    "statenisland": "https://www.nyc.gov/assets/finance/downloads/pdf/rolling_sales/rollingsales_statenisland.xlsx",
}

GEOCODE_URL = "https://geosearch.planninglabs.nyc/v2/search"
CONCURRENCY = 100
SAVE_DIR = project_root / "data" / "rollingprices"
CACHE_FILE = SAVE_DIR / "geo_cache.json"
OUTPUT_FILE = SAVE_DIR / "rollingsales_nyc.csv"


def download_xlsx_files():
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    for borough, url in BOROUGHS.items():
        dest = SAVE_DIR / f"rollingsales_{borough}.xlsx"
        if dest.exists():
            print(f"Already downloaded: {dest.name}")
            continue
        print(f"Downloading {borough}...")
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        dest.write_bytes(r.content)
        print(f"Saved {dest.name}")


def load_and_clean() -> pd.DataFrame:
    dfs = []
    borough_map = {1: "manhattan", 2: "bronx", 3: "brooklyn", 4: "queens", 5: "statenisland"}
    for borough in BOROUGHS:
        path = SAVE_DIR / f"rollingsales_{borough}.xlsx"
        df = pd.read_excel(path, skiprows=4, header=0)
        dfs.append(df)

    df = pd.concat(dfs, ignore_index=True)
    df["BOROUGH"] = df["BOROUGH"].map(borough_map)

    cols = [
        "BOROUGH", "NEIGHBORHOOD", "ADDRESS", "ZIP CODE",
        "BUILDING CLASS CATEGORY", "BUILDING CLASS AT TIME OF SALE",
        "RESIDENTIAL UNITS", "COMMERCIAL UNITS", "TOTAL UNITS",
        "GROSS SQUARE FEET", "SALE PRICE", "SALE DATE", "YEAR BUILT",
    ]
    df = df[cols]
    df = df.dropna(subset=["ADDRESS", "SALE PRICE", "SALE DATE"])
    df = df[df["SALE PRICE"] > 0]
    return df


def build_query(row):
    addr = str(row["ADDRESS"]).strip().split(",")[0].strip()
    borough = str(row["BOROUGH"]).strip().title()
    zipcode = str(row["ZIP CODE"]).split(".")[0]
    return f"{addr}, {borough}, NY {zipcode}"


async def geocode_one(client, sem, query):
    async with sem:
        for attempt in range(3):
            try:
                r = await client.get(GEOCODE_URL, params={"text": query, "size": 1}, timeout=10)
                r.raise_for_status()
                features = r.json().get("features", [])
                if features:
                    lon, lat = features[0]["geometry"]["coordinates"]
                    return query, lat, lon
                return query, None, None
            except Exception:
                if attempt == 2:
                    return query, None, None
                await asyncio.sleep(1)


async def geocode_all(pending: list, geo_cache: dict):
    sem = asyncio.Semaphore(CONCURRENCY)
    limits = httpx.Limits(max_connections=CONCURRENCY, max_keepalive_connections=CONCURRENCY)
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = [geocode_one(client, sem, q) for q in pending]
        batch = []
        for coro in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Geocoding"):
            query, lat, lon = await coro
            geo_cache[query] = [lat, lon]
            batch.append(query)
            if len(batch) >= 500:
                CACHE_FILE.write_text(json.dumps(geo_cache))
                batch.clear()
        CACHE_FILE.write_text(json.dumps(geo_cache))


def find_taxi_zone(lat, lon, zone_list):
    if lat is None or lon is None:
        return None, None
    pt = Point(lon, lat)
    for zone_id, zone_name, geom in zone_list:
        if geom.contains(pt):
            return zone_id, zone_name
    return None, None


def download_rolling_sales():
    SAVE_DIR.mkdir(parents=True, exist_ok=True)

    download_xlsx_files()

    df = load_and_clean()
    print(f"Rows after cleaning: {len(df)}")

    df["_query"] = df.apply(build_query, axis=1)
    unique_queries = df["_query"].dropna().unique()
    print(f"Unique addresses to geocode: {len(unique_queries)}")

    geo_cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
    pending = [q for q in unique_queries if q not in geo_cache]
    print(f"Already cached: {len(geo_cache)} | Pending: {len(pending)}")

    if pending:
        asyncio.run(geocode_all(pending, geo_cache))

    found = sum(1 for v in geo_cache.values() if v[0] is not None)
    print(f"Geocoded: {found}/{len(unique_queries)} ({found/len(unique_queries)*100:.1f}%)")

    df["latitude"] = df["_query"].map(lambda q: geo_cache.get(q, [None, None])[0])
    df["longitude"] = df["_query"].map(lambda q: geo_cache.get(q, [None, None])[1])
    df = df.drop(columns=["_query"])

    taxi_zones_path = TAXI_ZONE if isinstance(TAXI_ZONE, Path) else Path(TAXI_ZONE)
    df_zones = pd.read_csv(taxi_zones_path)
    df_zones["geometry"] = df_zones["geometry"].apply(wkt.loads)
    zone_list = list(df_zones[["id", "zone", "geometry"]].itertuples(index=False, name=None))
    print(f"Taxi zones loaded: {len(zone_list)}")

    tqdm.pandas(desc="Taxi zone lookup")
    df[["taxi_zone_id", "taxi_zone_name"]] = df.progress_apply(
        lambda row: pd.Series(find_taxi_zone(row["latitude"], row["longitude"], zone_list)), axis=1
    )

    matched = df["taxi_zone_id"].notna().sum()
    print(f"Rows with taxi zone: {matched}/{len(df)} ({matched/len(df)*100:.1f}%)")

    df = df.dropna(subset=["taxi_zone_id"])
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved to {OUTPUT_FILE}")
