import os

os.environ["KERAS_BACKEND"] = "torch"  # Or "jax" / "torch"

import json
import datetime
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

import torch
from keras.models import load_model

# feature transformations for model input
from backend.taxi_demand import TaxiDemand, FHVHVTaxiDemand

# import layers for keras load_model
from model.layers.stgcn import STGCNBlock
from model.layers.adaptive_adjacency import AdaptiveAdjacency


WORKDIR = Path(__file__).resolve().parents[1]
dataPath = WORKDIR / "data" / "raw"
cleanDataPath = WORKDIR / "data" / "clean"

taxiPath = dataPath / "tlc_trip_record" / "yellow"
clean_taxiPath = cleanDataPath / "clean_tlc_trip_record" / "yellow"
fhvhvPath = dataPath / "tlc_trip_record" / "fhvhv"
weatherPath = dataPath / "weather"
lookUpPath = dataPath / "NYC_Taxi_Zones.csv"

input_steps = 12 
target_index = 0
FEATURE_LIST = ['pickups', 'precipitation', 'wind_speed_10m', 'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos']


def _get_taxiDemand(start_date: datetime.datetime, end_date: datetime.datetime, is_fhvhv : bool):
    if is_fhvhv:
        return FHVHVTaxiDemand(start_date, end_date)
    else:
        return TaxiDemand(start_date, end_date)

def _get_stgcn(keras_weights_path):
    return load_model(
        keras_weights_path,
        compile=False
    )


class DemandPredictionModel:

    def __init__(self, input_steps : int = 12):
        self.stgcn_yellow = _get_stgcn(WORKDIR / "data" / "stgcn.keras")
        self.stgcn_fhvhv = _get_stgcn(WORKDIR / "data" / "stgcn_fhvhv.keras")
        self.input_steps = input_steps


    def predict(self, today : str, is_fhvhv : bool) -> np.ndarray:
        today_date = datetime.datetime.strptime(today, "%Y-%m-%d")
        start_date = today_date - datetime.timedelta(hours=24)
        end_date = today_date - datetime.timedelta(hours=0)

        prep_demand_wrapper = _get_taxiDemand(start_date, end_date, is_fhvhv)
        demand_data = prep_demand_wrapper.prepare_dataset(FEATURE_LIST)
        demand_input_features, _ = prep_demand_wrapper.construct_dataset(demand_data, self.input_steps)

        # print("Input shape:", demand_input_features.shape)
        # print("Num samples:", len(demand_input_features))

        if is_fhvhv:
            y_pred = self.stgcn_fhvhv.predict(demand_input_features, batch_size=32)
        else:
            y_pred = self.stgcn_yellow.predict(demand_input_features, batch_size=32)

        # print("Output shape:", y_pred.shape)
        return np.squeeze(y_pred, axis=-1)


    def jsonify_output(self, pred: np.ndarray, taxi_zones: str | Path) -> dict:
        max_zone_per_h = np.max(pred, axis=1, keepdims=True)
        max_zone_per_h[max_zone_per_h == 0] = 1.0

        with open(taxi_zones, "r") as file:
            zones = json.load(file)

        intensity = pred / max_zone_per_h
        intensity = np.clip(intensity, 0.0, 1.0)

        pretty = [
            {
                "hour": i,
                "zones": [
                    {
                        "zone_id": zones["features"][j]["properties"]["id"],
                        "zone_name": zones["features"][j]["properties"]["zone"],
                        "borough": zones["features"][j]["properties"]["borough"],
                        "predicted_pickups": float(pred[i, j]),
                        "intensity": float(intensity[i, j]),
                    }
                    for j in range(pred.shape[1])
                ],
            }
            for i in range(pred.shape[0])
        ]

        return {"forecast": pretty}
