"""
Utility functions used by other scripts, including logger config
"""

import os
import time
import logging
from pathlib import Path

from scripts import LOG_DIR, LOG_LEVEL, TAXI_ZONE

import pandas as pd
import geopandas as gpd
from shapely import wkt


def load_dotenv(dotenv : str | Path) -> dict:
    result = {}
    with open(dotenv, "r") as f:
        for line in f:
            line = line.strip()
            if line == "": continue
            words = line.split("=", maxsplit=1)
            if len(words) != 2: continue
            
            try:
                result[str(words[0])] = str(words[1].strip("\""))
            except TypeError:
                pass
    return result


def get_logger(name : str) -> logging.Logger:
    t = time.localtime()
    os.makedirs(LOG_DIR, exist_ok=True)
    file = LOG_DIR / f"{name}_{t.tm_year}{t.tm_mon:02}{t.tm_mday:02}.txt"

    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVEL)

    logging.basicConfig(
        format="%(levelname)s %(asctime)s %(filename)s:%(lineno)s - %(message)s",
        datefmt="%Y-%m-%d_%H-%M-%S",
        filename=file,
        encoding="utf-8",
    )

    return logger


def write_nyc_taxi_zones_geojson(dest : Path, override = False):
    df = pd.read_csv(TAXI_ZONE)
    df['geometry'] = df['geometry'].apply(wkt.loads)

    gdf = gpd.GeoDataFrame(df, geometry='geometry')
    if not dest.exists() or override:
        gdf.to_file(dest, driver="GeoJSON")

