import findspark
import pyspark  
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.types import (
    StructType, StructField, StringType, TimestampNTZType,
    IntegerType, DoubleType, LongType
)
from pyspark.sql import functions as f
from pathlib import Path
import pandas as pd
from src.dataSampling import TLCSampler

#==============#
#   CONFIGS    #
#==============#

projectRoot = Path.cwd()

INPUT_PATH = Path(projectRoot) / "data" / "raw" / "tlc_trip_record" / "fhvhv"
OUTPUT_CLEAN = Path(projectRoot) / "data" / "clean" / "clean_tlc_trip_record" / "fhvhv"
OUTPUT_TRANSFORMED = Path(projectRoot) / "data" / "clean" / "transformed_tlc_trip_record" / "fhvhv"

POIS_PATH = Path(projectRoot) / "data" / "clean" / "pois" / "zones_with_poi_group_density.parquet"

WEATHER_DATA = Path(projectRoot) / "data" / "raw" / "weather" / "hourly"
WEATHER_DATA_PD = Path(projectRoot) / "data" / "raw" / "weather"/ "weather_contated.parquet"

# ZONE_CSV = Path(projectRoot)/ "data" / "raw" / "tlc_trip_record" / "taxi_zone_lookup.csv"
ZONE_CSV = Path(projectRoot) / "data" / "taxi_zone_lookup.csv"

MIN_DATETIME = "2020-01-01"
MIN_DATETIME_TRANSFORMED = "2022-01-01"
MAX_DATETIME =  "2026-01-01"

MAX_TRIP_MILES = 60         # 60 miles  = 96,50 km
MIN_TRIP_MILES = 0.1        # 0,1 miles = 160 meters
MAX_TRIP_TIME = 7200        # 7200 seconds = 2 hours
MIN_TRIP_TIME = 300         # 300 seconds = 5 min

MIN_FARE = 1.0
MAX_FARE = 250.00           # Base passenger fare (before fees, taxes, etc)

# Taxi zones that are airports
AIPORT_IDS = [1, 132, 138]

MAX_TIP_PCT = 0.5           # In percentage (%) respect of base passenger fare

POIS_COL = [
    'education_per_mi2',
    'entertainment_per_mi2',
    'food_drink_per_mi2',
    'healthcare_per_mi2',
    'nightlife_alcohol_per_mi2',
    'tourism_per_mi2'
]

#==============#
#    SPARK     #
#==============#

def get_spark() -> SparkSession:
    """
    Create a Spark session.

    This setup is tuned for a MacBook.

    Change the configs according to your device if you wanna run it.
    If we want to run this code on the cloud,
    we will need to change the configs too.
    """
    spark = (SparkSession.builder
        .master("local[4]")  
        .config("spark.driver.memory", "12g")
        .config("spark.executor.memory", "8g")
        .config("spark.sql.shuffle.partitions", "200")
        .config("spark.sql.adaptive.advisoryPartitionSizeInBytes", "64m")
        .config("spark.driver.maxResultSize", "1g")
        .config("spark.sql.session.timeZone", "America/New_York")
        .config("spark.sql.timestampType", "TIMESTAMP_NTZ")
        # Network binding fixes for macOS
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .getOrCreate())
    
    return spark
#==============#
#     LOAD     #
#==============#

def load_fhvhv(spark: SparkSession) -> DataFrame:

    """
    Load all FHVHV parquets with a fixed schema. 

    Args:
        A Spark session
    Returns:
        A Spark DataFrame
    """

    # Columns omitted from schema, never used:
    #   dispatching_base_num, originating_base_num, on_scene_datetime,
    #   bcf, access_a_ride_flag, wav_request_flag, wav_match_flag
    schema = StructType([
        StructField("hvfhs_license_num",        StringType()),
        StructField("request_datetime",         TimestampNTZType()),
        StructField("pickup_datetime",          TimestampNTZType()),
        StructField("dropoff_datetime",         TimestampNTZType()),
        StructField("PULocationID",             LongType()),
        StructField("DOLocationID",             LongType()),
        StructField("trip_miles",               DoubleType()),
        StructField("trip_time",                LongType()),
        StructField("base_passenger_fare",      DoubleType()),
        StructField("tolls",                    DoubleType()),
        StructField("sales_tax",                DoubleType()),
        StructField("congestion_surcharge",     DoubleType()),
        StructField("airport_fee",              DoubleType()),
        StructField("tips",                     DoubleType()),
        StructField("driver_pay",               DoubleType()),
        StructField("shared_request_flag",      StringType()),
        StructField("shared_match_flag",        StringType()),
        StructField("cbd_congestion_fee",       DoubleType()),
    ])

    path = str(INPUT_PATH / "*.parquet")
    df = spark.read.schema(schema).parquet(path)
    return df

def load_zones(spark: SparkSession) -> DataFrame:
    """
    Load and prepare the zone lookup table.

    Args:
        A Spark session
    Returns:
        A Spark DataFrame
    """
    path = str(ZONE_CSV)
    df = spark.read.option("header", "true").csv(path)
    df = df.select(
        f.col("LocationID").cast(IntegerType()).alias("LocationID"),
        f.col("Borough").alias("Borough"),
        f.col("Zone").alias("Zone"),
        f.col("service_zone").alias("service_zone"),
    )
    return df

def load_weather(spark: SparkSession, path : str = None) -> DataFrame:

    """
    Load and prepare the weather table.

    Args:
        A Spark session and a path with the concatenated parquet
    Returns:
        A Spark DataFrame
    """

    schema = StructType([
    StructField("datetime", TimestampNTZType()),
    StructField("temperature_2m", DoubleType()),
    StructField("apparent_temperature", DoubleType()),
    StructField("precipitation", DoubleType()),
    StructField("rain", DoubleType()),
    StructField("snowfall", DoubleType()),
    StructField("wind_speed_10m", DoubleType()),
    StructField("wind_gusts_10m", DoubleType()),
    StructField("relative_humidity_2m", DoubleType()),
    StructField("weather_code", DoubleType()),
    StructField("id", LongType())
    ])

    if path == None:
        dfs=[]
        for i in range(1,264):
            try:
                c = pd.read_parquet(WEATHER_DATA / f"{i}/2022-01-01_2025-12-31.parquet")
                c["id"] = i
                dfs.append(c)
            except:
                continue
        weather = pd.concat(dfs)
        
        weather.to_parquet(WEATHER_DATA_PD)
        path = str(WEATHER_DATA_PD)
        
    weather_df = spark.read.schema(schema).parquet(path)

    weather_df = (
        weather_df
        .withColumns(
            {
                "hour": f.hour('datetime'),
                "year": f.year('datetime'),
                "month": f.month('datetime'),
                "day": f.dayofmonth('datetime'),
            }
        )
    )

    return weather_df

def load_pois(spark):
    """
    Load POIs
    """
    pois_df = spark.read.parquet(str(POIS_PATH))

    return pois_df

#==============#
#    CLEAN     #
#==============#

def clean_data(df: DataFrame) -> DataFrame:
    """
    Clean the FHVHV dataset:
        - Drop rows with nulls
        - Filter out-of-range dates, trips, fare.
        - Remove negative fares and unreasonable trip metrics
        - Standardize flag columns
    """

    # Delete the 31 nulls of request_datetime
    df_clean = df.dropna(subset=["request_datetime"])

    df_clean = df_clean.where(
        # Delete locationID not in [264, 265] which are unknown or N/A (outside NYC)
        # And assure that it's in the correct range.
        f.col("PULocationID").between(1, 263) &
        f.col("DOLocationID").between(1, 263) &

        # Airport_fee Condition 1. Delete
        ~(
            ((f.col("DOLocationID").isin(AIPORT_IDS)) | (f.col("PULocationID").isin(AIPORT_IDS))) 
            & (f.col("airport_fee").isNull())
        ) &

        # datetimes must be in the right intervals
        f.col("request_datetime").between(f.lit(MIN_DATETIME), f.lit(MAX_DATETIME)) &
        f.col("pickup_datetime").between(f.lit(MIN_DATETIME), f.lit(MAX_DATETIME)) &
        f.col("dropoff_datetime").between(f.lit(MIN_DATETIME), f.lit(MAX_DATETIME)) &

        # By logic:
        # Dropoff time must be greater than pickup time
        # Pickup time must be greater than requested time
        (f.col("dropoff_datetime") > f.col("pickup_datetime")) & 
        (f.col("pickup_datetime") > f.col("request_datetime")) &

        # Trip metrics
        f.col("trip_miles").between(MIN_TRIP_MILES, MAX_TRIP_MILES) &
        f.col("trip_time").between(MIN_TRIP_TIME, MAX_TRIP_TIME) &

        # delete negative numbers
        (f.col("driver_pay") >= 0) &
        # cap base_passenger_fare
        f.col("base_passenger_fare").between(MIN_FARE, MAX_FARE)
    )

    # Fill Nulls
    df_clean = df_clean.fillna({
        # Airport_fee Condition 2. Replace with 0
        "airport_fee": 0,
        "cbd_congestion_fee": 0,
        "tips": 0,
        "tolls": 0,
        "sales_tax": 0,
        "congestion_surcharge": 0,
    })

    # Tips: no negatives, cap at MAX_TIP_PCT * base_passenger_fare
    df_clean = df_clean.where(
        (f.col("tips") >= 0) &
        (f.col("tips") <= MAX_TIP_PCT*f.col("base_passenger_fare"))
    )

    
    # Convert to boolean
    df_clean = df_clean.withColumns({
        col: f.when(f.upper(f.col(col)) == "Y", True).otherwise(False).cast("boolean")
        for col in ["shared_request_flag", "shared_match_flag"]
    })

    return df_clean

#==============#
#    JOINS     #
#==============#

def broadcast_join_zones(df: DataFrame, zones: DataFrame) -> DataFrame:
    """
    Broadcast join taxi_zone_lookup twice:
      - PULocationID -> pickup_borough, pickup_zone, pickup_service_zone
      - DOLocationID -> dropoff_borough, dropoff_zone, dropoff_service_zone
    """
    pu_zones = zones.select(
        f.col("LocationID").alias("_pu_loc"),
        f.col("Borough").alias("pickup_borough"),
        f.col("Zone").alias("pickup_zone"),
        f.col("service_zone").alias("pickup_service_zone"),
    )
    do_zones = zones.select(
        f.col("LocationID").alias("_do_loc"),
        f.col("Borough").alias("dropoff_borough"),
        f.col("Zone").alias("dropoff_zone"),
        f.col("service_zone").alias("dropoff_service_zone"),
    )

    df = df.join(f.broadcast(pu_zones), df.PULocationID == pu_zones._pu_loc, "left").drop("_pu_loc")
    df = df.join(f.broadcast(do_zones), df.DOLocationID == do_zones._do_loc, "left").drop("_do_loc")

    return df

def join_pois_trips(df_trips: DataFrame, df_pois: DataFrame, pois_cols: list[str], idx_col: str) -> DataFrame:
    """
    Broadcast join POIS
    """
    pois_pu = (
        df_pois.select(*([idx_col] + pois_cols))
    )
    pois_do = (
        df_pois.select(*([idx_col] + pois_cols))
    )

    for poi in pois_cols:
        pois_pu = pois_pu.withColumnRenamed(poi, f"pu_poi_{poi}")
        
        pois_do = pois_do.withColumnRenamed(poi, f"do_poi_{poi}")

    df_final = df_trips.join(pois_pu, df_trips.PULocationID == pois_pu.id, 'left').drop('id')
    df_final = df_final.join(pois_do, df_final.DOLocationID == pois_do.id, 'left').drop('id')

    return df_final

def join_weather(df: DataFrame, weather: DataFrame) -> DataFrame:
    """
    Broadcast join weather
    """
    df_final = (
        df
        .join(
            weather,
            (df["pickup_hour"] == weather["hour"]) &
            (df["pickup_year"] == weather["year"]) &
            (df["pickup_day"] == weather["day"]) &
            (df["pickup_month"] == weather["month"]) &
            (df["PULocationID"] == weather["id"]),
            how='left'
        )
        .dropna()
        .drop("id", "datetime", "year", "month", "hour", "day")
    )

    return df_final

#============================#
#    Feature Engineering     #
#============================#

def engineer_feature(df:DataFrame) -> DataFrame:
    """
    Creates the following columns:
        - Company name.
        - Simple temporal variables: Year, Month, Day.
            - The rest of temporal variables can be derive aposteriori to save space.
        - Trip metrics: total amount paid by customer, customer wait time and company collected fees.
    """

    df = df.withColumn(
        "company",
        f.when(f.col("hvfhs_license_num") == "HV0002", "Juno")
        .when(f.col("hvfhs_license_num") == "HV0003", "Uber")
        .when(f.col("hvfhs_license_num") == "HV0004", "Via")
        .when(f.col("hvfhs_license_num") == "HV0005", "Lyft")
        .otherwise(f.col("hvfhs_license_num"))
    )
    
    df = (df
        .withColumn("pickup_year", f.year("pickup_datetime"))              
        .withColumn("pickup_month", f.month("pickup_datetime"))
        .withColumn("pickup_day", f.dayofmonth("pickup_datetime"))
    )
    
    df = df.withColumn(
        "total_amount",
        f.round(
            f.col("base_passenger_fare") +
            f.col("tolls") +
            f.col("sales_tax") +
            f.col("congestion_surcharge") +
            f.col("airport_fee") +
            f.col("tips") +
            f.col("cbd_congestion_fee"),
            2
        )
    )
    
    df = df.withColumn(
        "wait_time",
        (f.unix_timestamp("pickup_datetime") - f.unix_timestamp("request_datetime"))
    )

    df = (df
        .where(f.col("total_amount") > f.col("driver_pay"))
        .withColumn("company_fees", f.col("total_amount") - f.col("driver_pay"))
    )
    # Tips Range Catefory
    df = df.withColumn("tip_category",
        f.when(f.col("tips") == 0, 0)
        .when(f.col("tips") < 2, 1)
        .when(f.col("tips") < 3, 2)
        .when(f.col("tips") < 5, 3)
        .otherwise(4)
    )

    return df

def add_temporal_columns(df: DataFrame) -> DataFrame:
    """
    Derive useful temporal features.
    """
    df = (
        df
        .withColumn("pickup_hour", f.hour("pickup_datetime"))
        .withColumn("pickup_day_of_week", f.dayofweek("pickup_datetime"))
        .withColumn("pickup_day_name", f.date_format("pickup_datetime", "EEEE"))
        .withColumn("pickup_is_weekend", f.dayofweek("pickup_datetime").isin([1, 7]))
        .withColumn("time_of_day",
            f.when((f.col("pickup_hour") >= 6)  & (f.col("pickup_hour") < 10), "morning_rush")
             .when((f.col("pickup_hour") >= 10) & (f.col("pickup_hour") < 16), "midday")
             .when((f.col("pickup_hour") >= 16) & (f.col("pickup_hour") < 20), "evening_rush")
             .when((f.col("pickup_hour") >= 20) & (f.col("pickup_hour") < 24), "night")
             .otherwise("late_night")
        )
    )
    return df

#==============#
#     SAVE     #
#==============#

def save_data(path: Path, df: DataFrame, columns: list[str] = None) -> None:
    """
    Save data partitioned by Year and Month.

    Format: .parquet with snappy compression.

    Args:
        path: Output path where parquet files will be saved.
        df: DataFrame to be saved.
        columns: Selected columns to be saved. If None, saves all columns.
    """
    
    partition_cols = ["pickup_year", "pickup_month"]
    
    if columns:
        selected_df = df.select(columns)
    else:
        selected_df = df
    
    selected_df.write.parquet(
        path=str(path),
        mode="overwrite",
        compression="snappy",
        partitionBy=partition_cols
    )

#========================#
#     TRANSFORMATION     #
#========================#

def fhvhv_transformation_analysis():
    """
    Transforms and saves fhvhv taxis' trips data for analysis
    
    """

    print("===== SPARK =====")
    findspark.init()

    print("Getting spark session...")
    spark = get_spark()

    print("===== DATA LOADING =====")

    print("Loading TLC data...")
    raw_data = load_fhvhv(spark)

    print("Loading zones data...")
    zones = load_zones(spark)

    print("===== DATA CLEANING =====")

    print("Cleaning raw data...")
    clean_df = clean_data(raw_data)
    print("Cleaned!")

    print("===== BROACAST JOIN =====")

    print("Joing zones...")
    df_with_zones = broadcast_join_zones(clean_df, zones)

    print("===== DATA ENGINEERING =====")

    print("Features engineering for clean data (for analysis)...")
    final_df_clean = engineer_feature(df_with_zones)

    print("===== DATA SAVING =====")

    print(f"Saving clean data (for analysis) in {OUTPUT_CLEAN}...")
    save_data(OUTPUT_CLEAN, final_df_clean)

    spark.stop()

def fhvhv_transformation_model(sample_fraction = 0.01):
    """
    Transforms and saves fhvhv taxis' trips data for Models
    
    """

    print("===== SPARK =====")
    findspark.init()

    print("Getting spark session...")
    spark = get_spark()

    print("===== DATA LOADING =====")

    print("Loading TLC clean data...")

    sampler = TLCSampler(seed=42, spark=spark)
    filter = (
        (f.col("pickup_datetime") >= f.lit(MIN_DATETIME_TRANSFORMED)) &
        (f.col("pickup_datetime") < f.lit(MAX_DATETIME))
    )
    clean_data = sampler.spark.read.parquet(str(OUTPUT_CLEAN))
    clean_data = clean_data.where(filter)

    print("Loading weather data...")
    weather = load_weather(spark)

    print("Loading POIs data...")
    pois = load_pois(spark)

    print("===== DATA SAMPLING =====")

    print(f"Total trips in original dataset (years filtered): {clean_data.count():,}")

    print(f"Sampling...")
    sample_df = sampler.sample_by_hour(
        df=clean_data,
        time_column='pickup_datetime',
        fraction=sample_fraction
    )
    print(f"Total trips in sampled dataset: {sample_df.count():,}")

    print("===== DATA ENGINEERING =====")
    print("Joing POIs...")
    df_joined_pois = join_pois_trips(sample_df, pois, POIS_COL, "id")

    print("Features engineering for transformed data (for model)...")
    final_df_transformed = add_temporal_columns(df_joined_pois)

    print("Adding weather...")
    final_df_transformed = join_weather(final_df_transformed, weather)

    print("===== DATA SAVING =====")

    print(f"Saving transformed data (for model) in {OUTPUT_TRANSFORMED}...")
    save_data(OUTPUT_TRANSFORMED, final_df_transformed)

    sampler.spark.stop()

#==============#
#     MAIN     #
#==============#

def main():
    print("\n" + "="*50)
    print("PIPELINE 1: CLEAN DATA (for analysis)")
    print("="*50)

    #fhvhv_transformation_analysis()

    print("\n" + "="*50)
    print("PIPELINE 2: TRANSFORMED DATA (for model)")
    print("="*50)

    fhvhv_transformation_model()

    print("\n" + "="*50)
    print("BOTH PIPELINES COMPLETED SUCCESSFULLY!")
    print("="*50)
    

if __name__ == "__main__":
    main()
