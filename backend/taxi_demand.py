import os
import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd

import pyspark  
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as f

WORKDIR = Path(__file__).resolve().parents[1]
dataPath = WORKDIR / "data" / "raw"
cleanDataPath = WORKDIR / "data" / "clean"

taxiPath = dataPath / "tlc_trip_record" / "yellow"
# RAW_TAXI_PATH = Path(PROJECT_ROOT, "data/raw/tlc_trip_record/yellow/")
clean_taxiPath = cleanDataPath / "clean_tlc_trip_record" / "yellow"
# CLEAN_TAXI_PATH = Path(PROJECT_ROOT, "data/clean/clean_tlc_trip_record/yellow/")
fhvhvPath = dataPath / "tlc_trip_record" / "fhvhv"
# RAW_FHVHV_TAXI_PATH = Path(PROJECT_ROOT, "data/raw/tlc_trip_record/fhvhv/")
weatherPath = dataPath / "weather"
# WEATHER_PATH = Path(PROJECT_ROOT, "data/raw/weather/")
lookUpPath = dataPath / "NYC_Taxi_Zones.csv"
# LOOK_UP_PATH = Path(PROJECT_ROOT, "data/NYC_Taxi_Zones_20251203.csv")


class TaxiDemand:
    def __init__(self, start_date: datetime.datetime, end_date: datetime.datetime, spark: SparkSession = None):
        self.format = "%Y-%m-%d %H:%M"
        self.start_date = start_date.strftime(self.format)
        self.end_date = end_date.strftime(self.format)
        self.spark = spark


    def load_dfs(self):
        if self.spark is None:
            return self._load_taxi_df(), self._load_weather_df()
        else:
            return self._load_clean_taxi_df(), self._load_weather_df()
    def prepare_dataset(self, selected_features: list[str] = [], save_path: str = ""):
        """
        Prepare dataset of shape (T, N, F)
        
        If save_path isn't passed, then it will construct the dataset inplace and return it
        If save_path is passed, it will first try loading the dataset from the path. If an error occurs then it will construct the dataset, save it in save_path, and return it
        """
        if save_path == "":
            all_features, all_times = self._prepare_features()
            X = self._build_feature_tensor(all_features,selected_features)
            return X
        try:
            loaded_data = np.load(save_path)
            X = loaded_data["X"]
            return X
        except:
            all_features, all_times = self._prepare_features()
            X = self._build_feature_tensor(all_features,selected_features)
            np.savez_compressed(save_path, X=X)
            return X
    def construct_dataset(self, data, input_steps: int, target_feature_index: int = 0):
        """
        Construct dataset from data for training and predicting
        data: (T, N, F)
        Returns:
        X: (num_samples, input_steps, N, F)
        y: (num_samples, N)
        """
        T, N, F = data.shape
        num_samples = T - input_steps 

        X = np.zeros((num_samples, input_steps, N, F), dtype=data.dtype)
        y = np.zeros((num_samples, 1, N), dtype=data.dtype)

        for i in range(num_samples):
            X[i] = data[i : i + input_steps]
            y[i] = data[i + input_steps : i + input_steps + 1, : , target_feature_index]
        y = y.reshape((num_samples, N))
        return X, y
    def _build_feature_tensor(self,feature_dict: dict, selected_features: list[str] = []):
        """
        Stacks selected features into a single tensor.
        Returns: X of shape (T_total, N, num_selected_features)
        """
        arrays_to_stack = []
        if len(selected_features) == 0:
            selected_features = feature_dict.keys()
        for feat in selected_features:
            if feat not in feature_dict:
                raise ValueError(f"Feature '{feat}' not found in feature dictionary.")
            arrays_to_stack.append(feature_dict[feat])
        return np.stack(arrays_to_stack, axis=-1)
    def _prepare_features(self):
        """
        Reads taxi and weather data and returns a dictionary of feature matrices.
        Every feature matrix has the exact shape (T_total, N).
        """
        taxi_df, weather = self.load_dfs()
        return self._extract_features(taxi_df, weather)
    def _load_taxi_df(self):
        dfs = []
        file_paths = []
        for period in pd.period_range(start=self.start_date, end=self.end_date, freq='M'):
            file_paths.append( taxiPath / f"yellow_tripdata_{period.year}-{period.month:02d}.parquet")

        for parquet_path in file_paths:
            try:
                df = pd.read_parquet(parquet_path)
                df.rename(columns = {"tpep_pickup_datetime" : "pickup_datetime"}, inplace= True)
                df = df[["pickup_datetime", "PULocationID", "DOLocationID"]].dropna()
                dfs.append(df)
            except:
                continue
        taxi_df = pd.concat(dfs, ignore_index=True)

        taxi_df["pickup_datetime"] = pd.to_datetime(taxi_df["pickup_datetime"])
        taxi_df = taxi_df.loc[(taxi_df["pickup_datetime"] >= self.start_date) & (taxi_df["pickup_datetime"] <= self.end_date)]
        
        return taxi_df

    def _load_weather_df(self):
        dfs=[]
        for i in range(1,264):
            try:
                c = pd.read_parquet( weatherPath / f"hourly/{i}/2022-01-01_2025-12-31.parquet")
                c["id"] = i
                dfs.append(c)
            except:
                raise ValueError(f"Weather data for location {i} missing.\n\t Please check if { weatherPath / f"hourly/{i}/2022-01-01_2025-12-31.parquet"} exists")
        weather = pd.concat(dfs)
        weather["us_datetime"] = weather.datetime.dt.tz_localize(None).astype("datetime64[us]")
        weather = weather.loc[(weather["datetime"] >= self.start_date) & \
                    (weather["datetime"] <= self.end_date)]
        return weather
    def _load_clean_taxi_df(self):
        
        taxi_df = self.spark.read.parquet(str(clean_taxiPath))

        taxi_df = taxi_df.select("pickup_datetime", "PULocationID", "DOLocationID").dropna()
        taxi_df = taxi_df.filter((f.col("pickup_datetime") >= self.start_date) & 
                                (f.col("pickup_datetime") <= self.end_date))

        return taxi_df.toPandas()
    def _extract_features(self, taxi_df, weather):

        location_ids = range(1,264,1)
        # Time binning for taxi data
        taxi_df["time_bin"] = taxi_df["pickup_datetime"].dt.floor("1h")
        # Time binning for weather (assuming it's already hourly, but just to be safe)
        weather["time_bin"] = weather["datetime"].dt.floor("1h")
        
        all_times = pd.date_range(start=self.start_date, end=self.end_date, freq="1h", inclusive="left")
        N = len(location_ids)
        T_total = len(all_times)

        features = {}
        # Pickups
        pu_matrix = taxi_df.groupby(["time_bin", "PULocationID"]).size().unstack(fill_value=0)
        pu_matrix = pu_matrix.reindex(index=all_times, columns=location_ids, fill_value=0)
        features["pickups"] = pu_matrix.to_numpy().astype("float32")

        # --- WEATHER FEATURES ---
        # We pivot the weather dataframe so Time is the index, Zone ID is the column, and the metric is the value
        # We will extract 4 common weather features as an example
        weather_cols_to_extract = ["temperature_2m", "precipitation", "wind_speed_10m", "relative_humidity_2m"]
        w_grouped = weather.groupby(["time_bin", "id"])[weather_cols_to_extract].mean()
            
        # Unstack the location 'id' to columns, creating a multi-index DataFrame
        w_matrix_all = w_grouped.unstack("id")
        
        # Reindex the time axis to match T_total
        w_matrix_all = w_matrix_all.reindex(index=all_times)

        for w_col in weather_cols_to_extract:
            # Extract the specific feature's columns, reindex for location_ids, fill NaNs, and convert
            w_mat = w_matrix_all[w_col].reindex(columns=location_ids)
            w_mat = w_mat.ffill().bfill().fillna(0)
            features[w_col] = w_mat.to_numpy().astype("float32")
        # --- TIME FEATURES ---
        hours = all_times.hour.values.astype("float32")
        hours_sin = np.sin(2 * np.pi * hours / 24.0).astype("float32")
        hours_cos = np.cos(2 * np.pi * hours / 24.0).astype("float32")

        features["hour_sin"] = np.tile(hours_sin[:, None], (1, N))
        features["hour_cos"] = np.tile(hours_cos[:, None], (1, N))
        
        day_of_week = all_times.dayofweek.values.astype("float32")
        dow_sin = np.sin(2 * np.pi * day_of_week / 7.0).astype("float32")
        dow_cos = np.cos(2 * np.pi * day_of_week / 7.0).astype("float32")
        
        features["dow_sin"] = np.tile(dow_sin[:, None], (1, N))
        features["dow_cos"] = np.tile(dow_cos[:, None], (1, N))
        
        # Month (Cyclical: 1=January to 12=December)
        month = all_times.month.values.astype("float32")
        month_sin = np.sin(2 * np.pi * month / 12.0).astype("float32")
        month_cos = np.cos(2 * np.pi * month / 12.0).astype("float32")
        
        features["month_sin"] = np.tile(month_sin[:, None], (1, N))
        features["month_cos"] = np.tile(month_cos[:, None], (1, N))

        return features, all_times
    

class FHVHVTaxiDemand(TaxiDemand): 
    def __init__(self, start_date: datetime, end_date: datetime.datetime, spark: SparkSession = None):
        # Initialize the parent class attributes using super()
        super().__init__(start_date, end_date, spark)
        
    def _load_taxi_df(self):
        
        dfs = []
        file_paths = []
        for period in pd.period_range(start=self.start_date, end=self.end_date, freq='M'):
            file_paths.append( fhvhvPath / f"fhvhv_tripdata_{period.year}-{period.month:02d}.parquet")

        for parquet_path in file_paths:
            try:
                df = pd.read_parquet(parquet_path)[["pickup_datetime", "PULocationID", "DOLocationID"]].dropna()
                dfs.append(df)
            except:
                continue
        taxi_df = pd.concat(dfs, ignore_index=True)

        taxi_df["pickup_datetime"] = pd.to_datetime(taxi_df["pickup_datetime"])
        taxi_df = taxi_df.loc[(taxi_df["pickup_datetime"] >= self.start_date) & (taxi_df["pickup_datetime"] <= self.end_date)]
        return taxi_df

