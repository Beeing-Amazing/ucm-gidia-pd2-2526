import findspark
import pyspark  
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as f
from pathlib import Path

#==============#
#   CONFIGS    #
#==============#

projectRoot = Path.cwd()

TRIPS_DATA_YELLOW = Path(projectRoot) / "data" / "clean" / "clean_tlc_trip_record" / "yellow"
TRIPS_DATA_FHVFHV = Path(projectRoot) / "data" / "clean" / "clean_tlc_trip_record" / "fhvhv"

SAMPLE_YELLOW = Path(projectRoot) / "data" / "clean" / "sampled_tlc_trip_record" / "yellow"
SAMPLE_FHVHV = Path(projectRoot) / "data" / "clean" / "sampled_tlc_trip_record" / "fhvhv"

MIN_DATETIME = "2022-01-01"
MAX_DATETIME =  "2026-01-01"

#==============#
#   SAMPLING   #
#==============#

class TLCSampler:
    """
    Class for stratified sampling by hour in TLC datasets.
    """

    def __init__(self, spark, seed: int = 42):
        """
        Initializes the sampler with a seed for reproducibility.
        
        Args:
            spark: Spark session (optional, creates one if not provided)
            seed: Seed for random numbers
        """
        self.spark = spark
        self.seed = seed

    def sample_by_hour(self, df: DataFrame, time_column: str, fraction: float) -> DataFrame:
        """
        Stratified sampling by hour.
        
        Args:
            df: DataFrame with trip data
            time_column: Column with timestamp ('pickup_datetime')
            fraction: Fraction to sample (e.g., 0.1 for 10%)
        
        Returns:
            Sampled DataFrame preserving hourly distribution
        """

        # Create hopur stratum (YYYY-MM-DD HH)
        df_with_hour = df.withColumn(
            '_hour_stratum',
            f.date_format(f.col(time_column), "yyyy-MM-dd HH")
        )

        # Calculate fractions per hour (same for all hours)
        hour_counts = df_with_hour.groupBy('_hour_stratum').count()
        fractions = {
            row['_hour_stratum']: fraction for row in hour_counts.collect()
        }

        # Stratified sampling
        sampled = df_with_hour.stat.sampleBy(
            '_hour_stratum', 
            fractions, 
            self.seed
        ).drop('_hour_stratum')

        return sampled.orderBy('pickup_datetime')


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
        .master("local[6]")  
        .config("spark.driver.memory", "8g")
        .config("spark.executor.memory", "8g")
        .config("spark.sql.shuffle.partitions", "100")
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

#==============#
#     MAIN     #
#==============#

def main():
    spark = get_spark()

    sampler = TLCSampler(seed=42, spark=spark)
    filter = (
        (f.col("pickup_datetime") >= f.lit(MIN_DATETIME)) &
        (f.col("pickup_datetime") < f.lit(MAX_DATETIME))
    )

    print("Sampling Yellow Cabs Trips...")
    print(f"Reading data from: {TRIPS_DATA_YELLOW}")
    yellow_df = sampler.spark.read.parquet(str(TRIPS_DATA_YELLOW))
    yellow_df = yellow_df.where(filter)

    print(f"Total trips in original dataset: {yellow_df.count():,}")

    print(f"Sampling Yellow...")
    sample_yellow = sampler.sample_by_hour(
        df=yellow_df,
        time_column='pickup_datetime',
        fraction=0.005
    )
    print(f"Total trips in sampled dataset: {sample_yellow.count():,}")

    print(f"Saving...")
    save_data(str(SAMPLE_YELLOW), sample_yellow)

    print("Sampling FHVHV Trips...")
    print(f"Reading data from: {TRIPS_DATA_FHVFHV}")
    fhvhv_df = sampler.spark.read.parquet(str(TRIPS_DATA_FHVFHV))
    fhvhv_df = fhvhv_df.where(filter)
    print(f"Total trips in original dataset: {fhvhv_df.count():,}")

    print(f"Sampling FHVHV...")
    sample_fhvhv = sampler.sample_by_hour(
        df=fhvhv_df,
        time_column='pickup_datetime',
        fraction=0.0005
    )
    print(f"Total trips in sampled dataset: {sample_fhvhv.count():,}")

    print(f"Saving...")
    save_data(str(SAMPLE_FHVHV), sample_fhvhv)

    print(f"Finished!")

    sampler.spark.stop()
    
if __name__ == "__main__":
    main()