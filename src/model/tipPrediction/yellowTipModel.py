import findspark
import pyspark  
from pathlib import Path
import numpy as np
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as f
from pyspark.ml import Pipeline
from pyspark.ml.feature import StringIndexer, VectorAssembler, OneHotEncoder
from pyspark.ml.evaluation import MulticlassClassificationEvaluator
from xgboost.spark import SparkXGBClassifier
from pyspark.ml.feature import StringIndexer, OneHotEncoder, VectorAssembler
from pyspark.ml import Pipeline, PipelineModel
from pyspark.ml.evaluation import MulticlassClassificationEvaluator
from pyspark.sql.types import StructType, StructField, StringType, DoubleType
from pyspark.sql.functions import udf
from pyspark.ml.functions import vector_to_array

#==============#
#   CONFIGS    #
#==============#

projectRoot = Path.cwd()

YELLOW_DATA_PATH = Path(projectRoot) / "data" / "clean" / "transformed_tlc_trip_record" / "yellow"
MODEL_PATH = Path(projectRoot) / "src" / "model" / "tipPrediction" / "trainedModels" / "yellow_model"

TEST_CUT = "2025-01-01"

# Características numéricas y categóricas
NUMERIC_FEATURES = [
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "rain",
    "snowfall",
    "wind_speed_10m",
    "wind_gusts_10m",
    "relative_humidity_2m",
    "weather_code",
    "pu_poi_education_per_mi2",
    "pu_poi_entertainment_per_mi2",
    "pu_poi_food_drink_per_mi2",
    "pu_poi_healthcare_per_mi2",
    "pu_poi_nightlife_alcohol_per_mi2",
    "pu_poi_tourism_per_mi2",
]

CATEGORICAL_FEATURES = [
    'pickup_borough',
    "PULocationID",
    "pickup_day_of_week",
    "pickup_hour",
    "pickup_service_zone",
    "pickup_year",
    "pickup_month"
]

TARGET = "tip_category"

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

def train_test_split(df: DataFrame, test_cut: str):
    """
    Split data chronologically: train < test
    """
    train = df.where(f.col("pickup_datetime") < f.lit(test_cut))
    test = df.where(f.col("pickup_datetime") >= f.lit(test_cut))
    return train, test

#==============#
#   PIPELINE   #
#==============#

def build_pipeline() -> Pipeline:

    """
    Build pipeline of the multiclassification model
    """

    indexers = [StringIndexer(inputCol=col, outputCol=col + "_index", handleInvalid="keep") 
            for col in CATEGORICAL_FEATURES]

    encoders = [OneHotEncoder(inputCol=col + "_index", outputCol=col + "_encoded") 
                for col in CATEGORICAL_FEATURES]

    feature_cols = NUMERIC_FEATURES + [col + "_encoded" for col in CATEGORICAL_FEATURES]
    assembler = VectorAssembler(inputCols=feature_cols, outputCol="features")

    xgb_classifier = SparkXGBClassifier(
        features_col="features",
        label_col="tip_category",
        num_class=6,
        num_rounds=100,
        max_depth=6,
        eta=0.1,
        missing=0.0,
        seed = 42,
        eval_metric="mlogloss"
    )

    pipeline_xgb = Pipeline(stages=indexers + encoders + [assembler, xgb_classifier])

    return pipeline_xgb

#=======================#
#   TRAIN AND PREDICT   #
#=======================#

def train_model(df: DataFrame) -> PipelineModel:
    pipeline = build_pipeline()

    pipeline_model = pipeline.fit(df)

    pipeline_model.write().overwrite().save(str(MODEL_PATH))

    return pipeline_model

def prediction(df: DataFrame) -> DataFrame:

    pipeline_model = PipelineModel.load(str(MODEL_PATH))

    preds = pipeline_model.transform(df)

    return preds

def fit_transform(train: DataFrame, test: DataFrame) -> DataFrame:

    train_model(train)

    return prediction(test)

#==============#
#   EVALUATE   #
#==============#

def calculate_top_n_accuracy(preds, n = 2):
    """
    Calculate the top n accuracy
    """
    preds = preds.withColumn(
        "probs_array",
        f.array(
            f.col("prob_Rango0_$0"),
            f.col("prob_Rango1_$1-2"),
            f.col("prob_Rango2_$2-3"),
            f.col("prob_Rango3_$3-5"),
            f.col("prob_Rango4_$5+")
        )
    )
    
    preds = preds.withColumn("sorted_probs", f.sort_array(f.col("probs_array"), asc=False))
    preds = preds.withColumn(f"nth_max_prob", f.col("sorted_probs")[n-1])
    
    preds = preds.withColumn(
        "real_class_prob",
        f.when(f.col("tip_category") == 0, f.col("prob_Rango0_$0"))
        .when(f.col("tip_category") == 1, f.col("prob_Rango1_$1-2"))
        .when(f.col("tip_category") == 2, f.col("prob_Rango2_$2-3"))
        .when(f.col("tip_category") == 3, f.col("prob_Rango3_$3-5"))
        .when(f.col("tip_category") == 4, f.col("prob_Rango4_$5+"))
        .otherwise(f.col("prob_Rango4_$5+"))
    )
    
    preds = preds.withColumn(f"is_in_top_{n}", f.col("real_class_prob") >= f.col("nth_max_prob"))
    return preds.filter(f.col(f"is_in_top_{n}") == True).count() / preds.count()

def evaluation(preds:DataFrame, k: int = 2):
    """
    Model evaluation
    """

    preds = preds.withColumn(
        "prob_array", 
        vector_to_array(f.col("probability"))
    )

    for i in range(5):
        preds = preds.withColumn(f"prob_class_{i}", f.col("prob_array")[i])

    preds = preds.withColumnRenamed("prob_class_0", "prob_Rango0_$0")
    preds = preds.withColumnRenamed("prob_class_1", "prob_Rango1_$1-2")
    preds = preds.withColumnRenamed("prob_class_2", "prob_Rango2_$2-3")
    preds = preds.withColumnRenamed("prob_class_3", "prob_Rango3_$3-5")
    preds = preds.withColumnRenamed("prob_class_4", "prob_Rango4_$5+")


    acc = calculate_top_n_accuracy(preds, k)
    print(f"Top-{k}: {acc*100:.1f}%")

    # Log Loss
    logloss_evaluator = MulticlassClassificationEvaluator(
        labelCol="tip_category", 
        predictionCol="prediction", 
        metricName="logLoss"
    )
    log_loss = logloss_evaluator.evaluate(preds)
    print(f"Log Loss: {log_loss:.4f}")

    preds.select(
        "tip_category", 
        "prediction",
        "prob_Rango0_$0",
        "prob_Rango1_$1-2",
        "prob_Rango2_$2-3",
        "prob_Rango3_$3-5",
        "prob_Rango4_$5+"
    ).show(10, truncate=False)

#==============#
#    OUTPUT    #
#==============#

def generate_output(df: DataFrame) -> DataFrame:
    """
    Create outputs
    """
    df = df.withColumn(
        "prob_array", 
        vector_to_array(f.col("probability"))
    )
    
    for i in range(5):
        df = df.withColumn(f"prob_class_{i}", f.col("prob_array")[i])
    

    df = df.withColumnRenamed("prob_class_0", "prob_Rango0_$0")
    df = df.withColumnRenamed("prob_class_1", "prob_Rango1_$1-2")
    df = df.withColumnRenamed("prob_class_2", "prob_Rango2_$2-3")
    df = df.withColumnRenamed("prob_class_3", "prob_Rango3_$3-5")
    df = df.withColumnRenamed("prob_class_4", "prob_Rango4_$5+")
    
    @udf(StringType())
    def get_top(p0, p1, p2, p3, p4):
        probs = [p0, p1, p2, p3, p4]
        rangos = ["$0", "$1-2", "$2-3", "$3-5", "$5+"]
        
        indices = list(range(5))
        indices.sort(key=lambda i: probs[i], reverse=True)
        top_indices = indices[:2]
        top_indices.sort()
        
        if top_indices[0] - top_indices[1] == 1:
            return f"{rangos[top_indices[1]]} & {rangos[top_indices[0]]}: {probs[top_indices[0]] + probs[top_indices[1]]}"
        elif top_indices[0] - top_indices[1] == -1:
            return f"{rangos[top_indices[0]]} & {rangos[top_indices[1]]}: {probs[top_indices[0]] + probs[top_indices[1]]}"
        else:
            return f"{rangos[top_indices[0]]}: {probs[top_indices[0]]} | {rangos[top_indices[1]]}: {probs[top_indices[1]]} "
    
    df = df.withColumn("top_predictions", get_top(
        f.col("prob_Rango0_$0"),
        f.col("prob_Rango1_$1-2"),
        f.col("prob_Rango2_$2-3"),
        f.col("prob_Rango3_$3-5"),
        f.col("prob_Rango4_$5+")
    ))
    
    return df.select("top_predictions")
    
#==============#
#     MAIN     #
#==============#

def main():

    findspark.init()

    spark = get_spark()

    print(YELLOW_DATA_PATH)

    print("Loading dataset...")
    df = spark.read.parquet(str(YELLOW_DATA_PATH))

    print("Splitting...")
    train, test = train_test_split(df, TEST_CUT)
    print(f"Train: {train.count():,}, Test: {test.count():,}")

    print("Building pipeline and training model...")
    model = train_model(train)

    print("Predicting...")
    preds = prediction(test)

    print("Evaluating...")
    evaluation(preds)

    print("Generating output...")
    generate_output(preds).show(truncate= False, n = 10)

    spark.stop()

if __name__ == "__main__":
    main()