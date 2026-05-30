"""
Read the clean parquets of Yellow and FHVHV and generates a small parquet
with metrics about demand aggregated by taxi zone, ready to be used with
other datasets such as POIs.

REQUIREMENTS:
    Need the clean datasets of Yellow and FHVHV
    Setup Spark

OUTPUT:
    data/clean/taxi_zone_demand.parquet
    Columns:
        - PULocationID, pickup_borough, pickup_zone
        - total_trips, avg_daily_pickups
        - pickups_morning (6-12h), pickups_afternoon (12-18h),
          pickups_evening (18-24h), pickups_night (0-6h)
        - avg_fare, avg_tip, avg_tip_pct, avg_trip_miles, avg_trip_time_secs  (combined)
        - avg_fare_yellow, avg_fare_fhvhv
        - avg_tip_yellow, avg_tip_fhvhv
        - avg_tip_pct_yellow, avg_tip_pct_fhvhv
        - avg_trip_miles_yellow, avg_trip_miles_fhvhv
        - avg_trip_time_secs_yellow, avg_trip_time_secs_fhvhv
        - trips_yellow, trips_fhvhv, yellow_share_pct
"""

import findspark
findspark.init()

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType
from pathlib import Path

# CONFIG

PROJECT_ROOT = Path.cwd()

YELLOW_PATH = PROJECT_ROOT / "data" / "clean" / "clean_tlc_trip_record" / "yellow"
FHVHV_PATH  = PROJECT_ROOT / "data" / "clean" / "clean_tlc_trip_record" / "fhvhv"
OUTPUT_PATH  = PROJECT_ROOT / "data" / "clean" / "taxi_zone_demand.parquet"

# SPARK

def get_spark() -> SparkSession:

    spark = (SparkSession.builder
        .master("local[*]")
        .config("spark.driver.memory", "24g")
        .config("spark.executor.memory", "24g")
        .config("spark.sql.shuffle.partitions", "200")
        .config("spark.sql.adaptive.advisoryPartitionSizeInBytes", "128m")
        .config("spark.driver.maxResultSize", "2g")
        .config("spark.sql.session.timeZone", "America/New_York")
        .config("spark.sql.timestampType", "TIMESTAMP_NTZ")
        # Network binding fixes for macOS
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .getOrCreate())
    return spark

# LOAD

def load_yellow(spark: SparkSession) -> DataFrame:
    df = spark.read.parquet(str(YELLOW_PATH))
    df = df.select(
        F.col("PULocationID").cast(IntegerType()),
        F.col("pickup_datetime"),
        F.col("trip_distance").alias("trip_miles"),
        F.col("trip_time").cast("long").alias("trip_time"),
        F.col("total_amount"),
        F.col("tip_amount").alias("tips"),
        F.col("pickup_borough"),
        F.col("pickup_zone"),
        F.lit("yellow").alias("source"),
    )
    return df


def load_fhvhv(spark: SparkSession) -> DataFrame:
    df = spark.read.parquet(str(FHVHV_PATH))
    df = df.select(
        F.col("PULocationID").cast(IntegerType()),
        F.col("pickup_datetime"),
        F.col("trip_miles"),
        F.col("trip_time").cast("long").alias("trip_time"),
        F.col("total_amount"),
        F.col("tips"),
        F.col("pickup_borough"),
        F.col("pickup_zone"),
        F.lit("fhvhv").alias("source"),
    )
    return df

# AGGREGATION

def aggregate_demand(df: DataFrame, n_days: int) -> DataFrame:
    """
    Aggregates demand metrics respect of PULocationID.

    Args:
        df: Unified DataFrame with Yellow and FHVHV.
        n_days: Number of days to calculate averages.
    """

    # Time band
    df = df.withColumn("pickup_hour", F.hour("pickup_datetime"))
    df = df.withColumn("time_band",
        F.when(F.col("pickup_hour").between(6, 11), "morning")
         .when(F.col("pickup_hour").between(12, 17), "afternoon")
         .when(F.col("pickup_hour").between(18, 23), "evening")
         .otherwise("night")  # 0-5
    )

    # Tip percent
    df = df.withColumn("tip_pct",
        F.when(F.col("total_amount") > 0,
               (F.col("tips") / F.col("total_amount")) * 100
        ).otherwise(0.0)
    )

    # Main aggregation
    agg = df.groupBy("PULocationID", "pickup_borough", "pickup_zone").agg(
        # Volume
        F.count("*").alias("total_trips"),
        F.round(F.count("*") / n_days, 1).alias("avg_daily_pickups"),

        # Money: combined
        F.round(F.avg("total_amount"), 2).alias("avg_fare"),
        F.round(F.avg("tips"), 2).alias("avg_tip"),
        F.round(F.avg("tip_pct"), 2).alias("avg_tip_pct"),
        F.round(F.percentile_approx("total_amount", 0.5), 2).alias("median_fare"),

        # Money: per source
        F.round(F.avg(F.when(F.col("source") == "yellow", F.col("total_amount"))), 2).alias("avg_fare_yellow"),
        F.round(F.avg(F.when(F.col("source") == "fhvhv",  F.col("total_amount"))), 2).alias("avg_fare_fhvhv"),
        F.round(F.avg(F.when(F.col("source") == "yellow", F.col("tips"))), 2).alias("avg_tip_yellow"),
        F.round(F.avg(F.when(F.col("source") == "fhvhv",  F.col("tips"))), 2).alias("avg_tip_fhvhv"),
        F.round(F.avg(F.when(F.col("source") == "yellow", F.col("tip_pct"))), 2).alias("avg_tip_pct_yellow"),
        F.round(F.avg(F.when(F.col("source") == "fhvhv",  F.col("tip_pct"))), 2).alias("avg_tip_pct_fhvhv"),

        # Trip metrics: combined
        F.round(F.avg("trip_miles"), 2).alias("avg_trip_miles"),
        F.round(F.avg("trip_time"), 0).cast("long").alias("avg_trip_time_secs"),

        # Trip metrics: per source
        F.round(F.avg(F.when(F.col("source") == "yellow", F.col("trip_miles"))), 2).alias("avg_trip_miles_yellow"),
        F.round(F.avg(F.when(F.col("source") == "fhvhv",  F.col("trip_miles"))), 2).alias("avg_trip_miles_fhvhv"),
        F.round(F.avg(F.when(F.col("source") == "yellow", F.col("trip_time"))), 0).cast("long").alias("avg_trip_time_secs_yellow"),
        F.round(F.avg(F.when(F.col("source") == "fhvhv",  F.col("trip_time"))), 0).cast("long").alias("avg_trip_time_secs_fhvhv"),

        # Total trips per source
        F.sum(F.when(F.col("source") == "yellow", 1).otherwise(0)).alias("trips_yellow"),
        F.sum(F.when(F.col("source") == "fhvhv",  1).otherwise(0)).alias("trips_fhvhv"),
    )

    # Pickups by time band
    time_agg = (
        df.groupBy("PULocationID", "time_band")
          .count()
          .groupBy("PULocationID")
          .pivot("time_band", ["morning", "afternoon", "evening", "night"])
          .agg(F.first("count"))
    )

    for band in ["morning", "afternoon", "evening", "night"]:
        time_agg = time_agg.withColumn(
            f"pickups_{band}",
            F.round(F.coalesce(F.col(band), F.lit(0)) / n_days, 1)
        ).drop(band)

    # Join
    result = agg.join(time_agg, on="PULocationID", how="left")

    # Yellow share
    result = result.withColumn(
        "yellow_share_pct",
        F.round(F.col("trips_yellow") / F.col("total_trips") * 100, 1)
    )

    return result.orderBy("PULocationID")

# MAIN

def main():
    spark = get_spark()

    print("Loading Yellow...")
    yellow = load_yellow(spark)
    print(f"Yellow rows: {yellow.count():,}")

    print("Loading FHVHV...")
    fhvhv = load_fhvhv(spark)
    print(f"FHVHV rows: {fhvhv.count():,}")

    # Union
    combined = yellow.unionByName(fhvhv)
    total = combined.count()
    print(f"Combined: {total:,} trips")

    # Number of days
    date_range = combined.agg(
        F.min(F.to_date("pickup_datetime")).alias("min_date"),
        F.max(F.to_date("pickup_datetime")).alias("max_date"),
    ).collect()[0]
    n_days = (date_range["max_date"] - date_range["min_date"]).days + 1
    print(f"Date range: {n_days} days")

    print("Aggregating demand per zone...")
    demand = aggregate_demand(combined, n_days)

    # Save
    print(f"Saving at {OUTPUT_PATH}...")
    demand_pdf = demand.toPandas()
    demand_pdf.to_parquet(OUTPUT_PATH, compression='snappy')

    # Preview
    demand.orderBy(F.desc("avg_daily_pickups")).show(15, truncate=False)

    print(f"\nReady. {demand.count()} zones saved.")
    spark.stop()


if __name__ == "__main__":
    main()
