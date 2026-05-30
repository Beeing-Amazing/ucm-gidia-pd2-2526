import findspark
import pyspark  
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as f
from pathlib import Path
import numpy as np

#==============#
#   CONFIGS    #
#==============#

projectRoot = Path.cwd()

SAMPLE_YELLOW = Path(projectRoot) / "data" / "clean" / "transformed_tlc_trip_record" / "yellow"
SAMPLE_FHVHV = Path(projectRoot) / "data" / "clean" / "transformed_tlc_trip_record" / "fhvhv"

TEST_CUT=  "2025-01-01"

#==============#
#   BASELINE   #
#==============#

class TipPreditionBaseline:
    """
    Class to create and evaluate the baseline
    """

    def __init__(self, train: DataFrame, test: DataFrame, target: str):

        self.train = train
        self.test = test
        self.target = target
        self.means = None
    
    def fit(self):
        """
        Creates baseline model.
        """
        self.means = (
            self.train
            .select(
                'PULocationID',
                self.target
            )
            .groupBy(
                'PULocationID',
            )
            .agg(
                f.avg(self.target).alias('avg_tip')
            )
        )

    def predict(self) -> DataFrame:
        """
        Makes predictions.
        """

        predictions = (
            self.test.select(
                'PULocationID',
                'pickup_datetime',
                'tip_category',
                self.target
            )
            .join(
                self.means,
                on="PULocationID",
                how="left"
            )
            .withColumnRenamed("avg_tip", "predicted_tip")
            .withColumn(
                "predicted_category",
                f.when(f.col("predicted_tip") == 0, 0)
                .when(f.col("predicted_tip") < 2, 1)
                .when(f.col("predicted_tip") < 3, 2)
                .when(f.col("predicted_tip") < 5, 3)
                .otherwise(4)
            )
        )

        return predictions
    
    def evaluate(self, predictions: DataFrame) -> dict:
        """
        Evaluate performance.
        """
        # Top-1 Accuracy 
        total = predictions.count()
        correct = predictions.filter(f.col("tip_category") == f.col("predicted_category")).count()
        top1_accuracy = correct / total if total > 0 else 0
        
        top3_accuracy = top1_accuracy
        print("\n" + "="*50)
        print("BASELINE EVALUATION (CLASIFICACIÓN POR RANGOS)")
        print("="*50)
        print(f"Top-1 Accuracy: {top1_accuracy*100:.1f}%")
        print(f"Top-3 Accuracy: {top3_accuracy*100:.1f}%")
        print("="*50)
        
        return {
            "top1_accuracy": top1_accuracy,
            "top3_accuracy": top3_accuracy
        }

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
#    SPLIT     #
#==============#

def train_test_split(df: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Split data chronologically for time series.
    """
    cut_filter = (
        (f.col("pickup_datetime") < f.lit(TEST_CUT))
    )
    df_train = (
        df.where(
            cut_filter
        )
    )

    df_test = (
        df.where(
            ~cut_filter
        )
    )
    return df_train, df_test

#==============#
#     MAIN     #
#==============#

def main():
    spark = get_spark()

    print("\n" + "="*50)
    print("YELLOW BASELINE")
    print("="*50)

    print("Loading dataset...")
    yellow_df = spark.read.parquet(str(SAMPLE_YELLOW))
    print("Spliting...")
    yellow_train, yellow_test = train_test_split(yellow_df)

    print(yellow_df.count())

    print("Creating model...")
    yellow_baseline = TipPreditionBaseline(yellow_train, yellow_test, 'tip_amount')

    yellow_baseline.fit()

    yellow_pred = yellow_baseline.predict()

    yellow_pred.show(10)

    print("Evaluating...")

    yellow_metrics = yellow_baseline.evaluate(yellow_pred)

    print("\n" + "="*50)
    print("FHVHV BASELINE")
    print("="*50)

    print("Loading dataset...")
    fhvhv_df = spark.read.parquet(str(SAMPLE_FHVHV))
    print(fhvhv_df.count())

    print("Spliting...")
    fhvhv_train, fhvhv_test = train_test_split(fhvhv_df)

    print("Creating model...")
    fhvhv_baseline = TipPreditionBaseline(fhvhv_train, fhvhv_test, 'tips')

    fhvhv_baseline.fit()

    fhvhv_pred = fhvhv_baseline.predict()

    fhvhv_pred.show(10)
    print("Evaluating...")

    fhvhv_metrics = fhvhv_baseline.evaluate(fhvhv_pred)

    spark.stop()

if __name__ == "__main__":
    main()