"""Same function as in src/aggregate_demand.py but adapted to the need of the wealth analysis. 
It also separates the yellow and fhv dataframes in different functions to be able to use them separately in the wealth analysis
and therefore compare and analyze if the different trips and services affect wealth distribution.
"""

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as f, types
import findspark
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import os
from pathlib import Path
import geopandas as gpd
from shapely import wkt
import json

def count_trips(yellow, fhv):
    """
    Count the number of trips in the yellow and fhv dataframes, filtering by dropoff year (2023, 2024, 2025).
    """
    yellow = yellow.withColumn("dropoff_year", f.year("dropoff_datetime"))
    yellow = yellow.filter(f.col("dropoff_year").isin([2023, 2024, 2025]))
    fhv = fhv.withColumn("dropoff_year", f.year("dropoff_datetime"))
    fhv = fhv.filter(f.col("dropoff_year").isin([2023, 2024, 2025]))
    print("Número total de viajes de taxis amarillos:", yellow.count())
    print("Número total de viajes de FHV/HV:", fhv.count())
    # Unir los DataFrames de taxis amarillos y FHV/HV
    df_all = yellow.unionByName(fhv)
    print("Número total de viajes combinados:", df_all.count())
    return yellow, fhv

def time_band_calc(yellow, fhv):
    """Calculate the time band for each trip in the yellow and fhv dataframes, based on the pickup hour. The time bands are:
    - Morning: 6-11
    - Afternoon: 12-17
    - Evening: 18-23
    - Night: 0-5
    """
    # Time band yellow
    yellow = yellow.withColumn("pickup_hour", f.hour("pickup_datetime"))
    yellow = yellow.withColumn("time_band",
        f.when(f.col("pickup_hour").between(6, 11), "morning")
            .when(f.col("pickup_hour").between(12, 17), "afternoon")
            .when(f.col("pickup_hour").between(18, 23), "evening")
            .otherwise("night")  # 0-5
        )

    # Time band fhv
    fhv = fhv.withColumn("pickup_hour", f.hour("pickup_datetime"))
    fhv = fhv.withColumn("time_band",
        f.when(f.col("pickup_hour").between(6, 11), "morning")
            .when(f.col("pickup_hour").between(12, 17), "afternoon")
            .when(f.col("pickup_hour").between(18, 23), "evening")
            .otherwise("night")  # 0-5
        )
    return yellow, fhv

def tip_pct_calc(yellow, fhv):
    # Tip percent yellow
    yellow = yellow.withColumn("tip_pct",
        f.when(f.col("total_amount") > 0,
                (f.col("tips") / f.col("total_amount")) * 100
        ).otherwise(0.0)
    )
    # Tip percent fhv
    fhv = fhv.withColumn("tip_pct",
        f.when(f.col("total_amount") > 0,
                (f.col("tips") / f.col("total_amount")) * 100
        ).otherwise(0.0)
    )
    return yellow, fhv

def range_days(yellow, fhv):
    # Number of days yellow
    date_range_yellow = yellow.agg(
        f.min(f.to_date("pickup_datetime")).alias("min_date"),
        f.max(f.to_date("pickup_datetime")).alias("max_date"),
    ).collect()[0]
    n_days_yellow = (date_range_yellow["max_date"] - date_range_yellow["min_date"]).days + 1
    print(f"Date range: {n_days_yellow} days")
    # Number of days uber
    date_range_fhv = fhv.agg(
        f.min(f.to_date("pickup_datetime")).alias("min_date"),
        f.max(f.to_date("pickup_datetime")).alias("max_date"),
    ).collect()[0]
    n_days_fhv = (date_range_fhv["max_date"] - date_range_fhv["min_date"]).days + 1
    print(f"Date range: {n_days_fhv} days")
    return n_days_yellow, n_days_fhv


def aggregations_yellow_fhv(yellow, fhv, n_days_yellow, n_days_fhv):
    """
    Calculate the following aggregations for the yellow and fhv dataframes, grouped by PULocationID, pickup_borough and pickup_zone:
    - Volume: total trips, average daily pickups
    - Money: average fare, average tip, average tip percent, median fare
    - Trip metrics: average trip miles, average trip time in seconds
    """
    agg_yellow = yellow.groupBy("PULocationID", "pickup_borough", "pickup_zone").agg(
        # Volume, average daily pickups
        f.count("*").alias("total_trips"),
        f.round(f.count("*") / n_days_yellow, 1).alias("avg_daily_pickups"),

        # Money: average fare, tip, tip percent, median fare
        f.round(f.avg("total_amount"), 2).alias("avg_fare"),
        f.round(f.avg("tips"), 2).alias("avg_tip"),
        f.round(f.avg("tip_pct"), 2).alias("avg_tip_pct"),
        f.round(f.percentile_approx("total_amount", 0.5), 2).alias("median_fare"),

        # Trip metrics
        f.round(f.avg("trip_miles"), 2).alias("avg_trip_miles"),
        f.round(f.avg("trip_time"), 0).cast("long").alias("avg_trip_time_secs")
    )
    agg_fhv = fhv.groupBy("PULocationID", "pickup_borough", "pickup_zone").agg(
            # Volume
            f.count("*").alias("total_trips"),
            f.round(f.count("*") / n_days_fhv, 1).alias("avg_daily_pickups"),

            # Money
            f.round(f.avg("total_amount"), 2).alias("avg_fare"),
            f.round(f.avg("tips"), 2).alias("avg_tip"),
            f.round(f.avg("tip_pct"), 2).alias("avg_tip_pct"),
            f.round(f.percentile_approx("total_amount", 0.5), 2).alias("median_fare"),


            # Trip metrics
            f.round(f.avg("trip_miles"), 2).alias("avg_trip_miles"),
            f.round(f.avg("trip_time"), 0).cast("long").alias("avg_trip_time_secs")
        )
    return agg_yellow, agg_fhv

def pickup_time_band_results(yellow, fhv, agg_yellow, agg_fhv, n_days_yellow, n_days_fhv):
    """
    Calculate the number of pickups by time band for the yellow and fhv dataframes, grouped by PULocationID. 
    Then, join the results with the aggregations calculated in the previous function and order by PULocationID.
    """
    # Pickups by time band yellow
    time_agg_yellow = (
        yellow.groupBy("PULocationID", "time_band")
            .count()
            .groupBy("PULocationID")
            .pivot("time_band", ["morning", "afternoon", "evening", "night"])
            .agg(f.first("count"))
    )

    for band in ["morning", "afternoon", "evening", "night"]:
        time_agg_yellow = time_agg_yellow.withColumn(
            f"pickups_{band}",
            f.round(f.coalesce(f.col(band), f.lit(0)) / n_days_yellow, 1)
        ).drop(band)

    # Join
    result_yellow = agg_yellow.join(time_agg_yellow, on="PULocationID", how="left")
    result_yellow = result_yellow.orderBy("PULocationID")

    # Pickups by time band fhv
    time_agg_fhv = (
        fhv.groupBy("PULocationID", "time_band")
            .count()
            .groupBy("PULocationID")
            .pivot("time_band", ["morning", "afternoon", "evening", "night"])
            .agg(f.first("count"))
    )

    for band in ["morning", "afternoon", "evening", "night"]:
        time_agg_fhv = time_agg_fhv.withColumn(
            f"pickups_{band}",
            f.round(f.coalesce(f.col(band), f.lit(0)) / n_days_fhv, 1)
        ).drop(band)

    # Join
    result_fhv = agg_fhv.join(time_agg_fhv, on="PULocationID", how="left")
    result_fhv = result_fhv.orderBy("PULocationID")

    return result_yellow, result_fhv



def aggregations_yellow_fhv_pois(yellow_pois, fhv_pois, n_days_yellow, n_days_fhv):
    """Calculate the following aggregations for the yellow and fhv dataframes with pois, grouped by PULocationID, pickup_borough and pickup_zone:
    - Volume: total trips, average daily pickups
    - Money: average fare, average tip, average tip percent, median fare
    - Trip metrics: average trip miles, average trip time in seconds
    - POIs destination: total trips to high SES areas, percentage of trips to high SES zones
    """
    agg_yellow_pois = yellow_pois.groupBy("PULocationID", "pickup_borough", "pickup_zone").agg(
        # Volume, average daily pickups
        f.count("*").alias("total_trips"),
        f.round(f.count("*") / n_days_yellow, 1).alias("avg_daily_pickups"),

        # Money: average fare, tip, tip percent, median fare
        f.round(f.avg("total_amount"), 2).alias("avg_fare"),
        f.round(f.avg("tips"), 2).alias("avg_tip"),
        f.round(f.avg("tip_pct"), 2).alias("avg_tip_pct"),
        f.round(f.percentile_approx("total_amount", 0.5), 2).alias("median_fare"),

        # Trip metrics
        f.round(f.avg("trip_miles"), 2).alias("avg_trip_miles"),
        f.round(f.avg("trip_time"), 0).cast("long").alias("avg_trip_time_secs"),

        # POIs destination
        f.sum(f.when(f.col("is_high_SES")==True, 1).otherwise(0)).alias("trips_to_high_SES"),
        f.round(f.sum(f.when(f.col("is_high_SES")==True, 1).otherwise(0)).alias("trips_to_high_SES")/f.count("*"),2).alias("trips_to_high_SES_pct")
        
    )
    agg_fhv_pois = fhv_pois.groupBy("PULocationID", "pickup_borough", "pickup_zone").agg(
        # Volume
        f.count("*").alias("total_trips"),
        f.round(f.count("*") / n_days_fhv, 1).alias("avg_daily_pickups"),

        # Money
        f.round(f.avg("total_amount"), 2).alias("avg_fare"),
        f.round(f.avg("tips"), 2).alias("avg_tip"),
        f.round(f.avg("tip_pct"), 2).alias("avg_tip_pct"),
        f.round(f.percentile_approx("total_amount", 0.5), 2).alias("median_fare"),


        # Trip metrics
        f.round(f.avg("trip_miles"), 2).alias("avg_trip_miles"),
        f.round(f.avg("trip_time"), 0).cast("long").alias("avg_trip_time_secs"),


        # POIs destination
        f.sum(f.when(f.col("is_high_SES")==True, 1).otherwise(0)).alias("trips_to_high_SES"),
        f.round(f.sum(f.when(f.col("is_high_SES")==True, 1).otherwise(0)).alias("trips_to_high_SES")/f.count("*"),2).alias("trips_to_high_SES_pct")
    )
    return agg_yellow_pois, agg_fhv_pois