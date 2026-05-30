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
from pyspark.ml.evaluation import MulticlassClassificationEvaluator, BinaryClassificationEvaluator
from pyspark.sql.types import StructType, StructField, StringType, DoubleType
from pyspark.ml.functions import vector_to_array
from pyspark.sql.functions import udf

#==============#
#   CONFIGS    #
#==============#

projectRoot = Path.cwd()

FHVHV_DATA_PATH = Path(projectRoot) / "data" / "clean" / "transformed_tlc_trip_record" / "fhvhv"
BINARY_MODEL_PATH = Path(projectRoot) / "src" / "model" / "tipPrediction" / "trainedModels" / "fhvhv_model" / "binary"
MULTICLASS_MODEL_PATH = Path(projectRoot) / "src" / "model" / "tipPrediction" / "trainedModels" / "fhvhv_model" / "multiclass"

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
    "trip_miles",
    "total_amount",
    "pu_poi_education_per_mi2",
    "pu_poi_entertainment_per_mi2",
    "pu_poi_food_drink_per_mi2",
    "pu_poi_healthcare_per_mi2",
    "pu_poi_nightlife_alcohol_per_mi2",
    "pu_poi_tourism_per_mi2",
    "do_poi_education_per_mi2",
    "do_poi_entertainment_per_mi2",
    "do_poi_food_drink_per_mi2",
    "do_poi_healthcare_per_mi2",
    "do_poi_nightlife_alcohol_per_mi2",
    "do_poi_tourism_per_mi2",
]

CATEGORICAL_FEATURES = [
    'pickup_borough',
    "PULocationID",
    "pickup_day_of_week",
    "pickup_hour",
    "pickup_service_zone",
    "pickup_year",
    "pickup_month",
    "DOLocationID"
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

def build_pipeline_binary() -> Pipeline:

    """
    Build pipeline of the binary model
    """


    indexers_binary = [StringIndexer(inputCol=col, outputCol=col + "_index_binary", handleInvalid="keep") 
                   for col in CATEGORICAL_FEATURES]

    encoders_binary = [OneHotEncoder(inputCol=col + "_index_binary", outputCol=col + "_encoded_binary") 
                    for col in CATEGORICAL_FEATURES]

    feature_cols_binary = NUMERIC_FEATURES + [col + "_encoded_binary" for col in CATEGORICAL_FEATURES]
    assembler_binary = VectorAssembler(inputCols=feature_cols_binary, outputCol="features_binary")

    binary_classifier = SparkXGBClassifier(
        features_col="features_binary",
        label_col="has_tip",
        num_workers=4,
        num_round=100,
        max_depth=6,
        learning_rate=0.1,
        probability_col="prob_has_tip"
    )

    pipeline_binary = Pipeline(stages=indexers_binary + encoders_binary + [assembler_binary, binary_classifier])

    return pipeline_binary

def build_pipeline_multiclass() -> Pipeline:
    """
    Build pipeline of the multiclassification model
    """

    indexers_multi = [StringIndexer(inputCol=col, outputCol=col + "_index_multi", handleInvalid="keep") 
                  for col in CATEGORICAL_FEATURES]

    encoders_multi = [OneHotEncoder(inputCol=col + "_index_multi", outputCol=col + "_encoded_multi") 
                    for col in CATEGORICAL_FEATURES]

    feature_cols_multi = NUMERIC_FEATURES + [col + "_encoded_multi" for col in CATEGORICAL_FEATURES]
    assembler_multi = VectorAssembler(inputCols=feature_cols_multi, outputCol="features_multi")


    multiclass_classifier = SparkXGBClassifier(
        features_col="features_multi",
        label_col="tip_category",
        num_class=6,
        num_rounds=100,
        max_depth=6,
        eta=0.1,
        missing=0.0,
        seed = 42,
        eval_metric="mlogloss"
    )

    pipeline_multiclass = Pipeline(stages=indexers_multi + encoders_multi + [assembler_multi,  multiclass_classifier])

    return pipeline_multiclass

#=======================#
#   TRAIN AND PREDICT   #
#=======================#

## BINARY MODEL

def train_binary_model(df: DataFrame):

    pipeline = build_pipeline_binary()

    pipeline_model = pipeline.fit(df)

    pipeline_model.write().overwrite().save(str(BINARY_MODEL_PATH))

def binary_prediction(df: DataFrame) -> DataFrame:

    pipeline_model = PipelineModel.load(str(BINARY_MODEL_PATH))

    preds = pipeline_model.transform(df)

    return preds

## MULTICLASS MODEL

def prepare_data_multiclass(train: DataFrame, test: DataFrame) -> tuple[DataFrame, DataFrame, int]:
    """
    Prepares data for multiclassification model
    """
    train_multiclass = (
        train
        .filter(f.col("tip_category") > 0)
        .withColumn(
            "tip_category_indexed", 
            (f.col("tip_category") - 1).cast("int")
        )
    )

    test_with_tip = test.filter(f.col("prediction") == 1)

    test_multiclass = (
        test_with_tip
        .filter(f.col("tip_category") > 0)
        .withColumn(
            "tip_category_indexed", 
            (f.col("tip_category") - 1).cast("int")
        )
    )

    fn = test_with_tip.filter(f.col("tip_category") == 0).count()

    return train_multiclass, test_multiclass, fn

def train_multiclass_model(df: DataFrame):

    pipeline = build_pipeline_multiclass()

    pipeline_model = pipeline.fit(df)

    pipeline_model.write().overwrite().save(str(MULTICLASS_MODEL_PATH))

def multiclass_prediction(df: DataFrame) -> DataFrame:

    pipeline_model = PipelineModel.load(str(MULTICLASS_MODEL_PATH))

    preds = pipeline_model.transform(df)

    return preds

#==============#
#   EVALUATE   #
#==============#

def binary_evaluation(preds:DataFrame, k: int = 2):

    test_no_tip = preds.filter(f.col("prediction") == 0)
    test_with_tip = preds.filter(f.col("prediction") == 1)

    print(f"Muestras sin propina predicha: {test_no_tip.count()}")
    print(f"Muestras con propina predicha: {test_with_tip.count()}")

    metrics = {
        "accuracy": MulticlassClassificationEvaluator(labelCol="has_tip", predictionCol="prediction", metricName="accuracy").evaluate(preds),
        "precision": MulticlassClassificationEvaluator(labelCol="has_tip", predictionCol="prediction", metricName="precisionByLabel").evaluate(preds),
        "recall": MulticlassClassificationEvaluator(labelCol="has_tip", predictionCol="prediction", metricName="recallByLabel").evaluate(preds),
        "f1": MulticlassClassificationEvaluator(labelCol="has_tip", predictionCol="prediction", metricName="f1").evaluate(preds),
        "auc": BinaryClassificationEvaluator(labelCol="has_tip", rawPredictionCol="rawPrediction", metricName="areaUnderROC").evaluate(preds)
    }

    print("\n".join([f"{k}: {v:.4f}" for k, v in metrics.items()]))

def calculate_top_n_accuracy(preds, n, fn):
    """
    Calculates top n accuracy
    """
    preds = preds.withColumn(
            "probs_array",
            f.array(
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
        f.when(f.col("tip_category") == 1, f.col("prob_Rango1_$1-2"))
        .when(f.col("tip_category") == 2, f.col("prob_Rango2_$2-3"))
        .when(f.col("tip_category") == 3, f.col("prob_Rango3_$3-5"))
        .when(f.col("tip_category") == 4, f.col("prob_Rango4_$5+"))
        .otherwise(f.col("prob_Rango4_$5+"))
    )
    
    preds = preds.withColumn(f"is_in_top_{n}", f.col("real_class_prob") >= f.col("nth_max_prob"))
    return (preds.filter(f.col(f"is_in_top_{n}") == True).count()) / (preds.count() + fn)

def multiclass_evaluation(preds:DataFrame, k: int = 2, fn: int = 0):

    preds = preds.withColumn(
        "prob_array", 
        vector_to_array(f.col("probability_multi"))
    )

    for i in range(4):
        preds = preds.withColumn(f"prob_class_{i + 1}", f.col("prob_array")[i])

    preds = preds.withColumnRenamed("prob_class_1", "prob_Rango1_$1-2")
    preds = preds.withColumnRenamed("prob_class_2", "prob_Rango2_$2-3")
    preds = preds.withColumnRenamed("prob_class_3", "prob_Rango3_$3-5")
    preds = preds.withColumnRenamed("prob_class_4", "prob_Rango4_$5+")


    acc = calculate_top_n_accuracy(preds, k, fn)
    print(f"Top-{k}: {acc*100:.1f}%")

    # Log Loss
    logloss_evaluator = MulticlassClassificationEvaluator(
        labelCol="tip_category_indexed", 
        predictionCol="prediction",
        probabilityCol="probability_multi",
        metricName="logLoss"
    )
    log_loss = logloss_evaluator.evaluate(preds)
    print(f"Log Loss: {log_loss:.4f}")

    preds.select(
        "tip_category_indexed", 
        "prediction",
        "prob_Rango1_$1-2",
        "prob_Rango2_$2-3",
        "prob_Rango3_$3-5",
        "prob_Rango4_$5+"
    ).show(10, truncate=False)

#==============#
#    OUTPUT    #
#==============#

def generate_output(multi_preds: DataFrame, binary_preds: DataFrame) -> tuple[DataFrame, DataFrame]:
    """
    Create outputs
    """
    df = multi_preds.withColumn(
        "prob_array", 
        vector_to_array(f.col("probability_multi"))
    )
    
    for i in range(4):
        df = df.withColumn(f"prob_class_{i + 1}", f.col("prob_array")[i])
    

    df = df.withColumnRenamed("prob_class_1", "prob_Rango1_$1-2")
    df = df.withColumnRenamed("prob_class_2", "prob_Rango2_$2-3")
    df = df.withColumnRenamed("prob_class_3", "prob_Rango3_$3-5")
    df = df.withColumnRenamed("prob_class_4", "prob_Rango4_$5+")
    
    @udf(StringType())
    def get_top(p1, p2, p3, p4):
        probs = [p1, p2, p3, p4]
        rangos = ["$1-2", "$2-3", "$3-5", "$5+"]
        
        indices = list(range(4))
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
        f.col("prob_Rango1_$1-2"),
        f.col("prob_Rango2_$2-3"),
        f.col("prob_Rango3_$3-5"),
        f.col("prob_Rango4_$5+")
    ))
    
    return df.select("top_predictions"), None

#==============#
#     MAIN     #
#==============#

def main():

    findspark.init()

    spark = get_spark()

    print(FHVHV_DATA_PATH)

    print("Loading dataset...")
    df = spark.read.parquet(str(FHVHV_DATA_PATH))

    print("Splitting...")
    train, test = train_test_split(df, TEST_CUT)
    print(f"Train: {train.count():,}, Test: {test.count():,}")

    train_binary = train.withColumn("has_tip", (f.col("tip_category") > 0).cast("int"))
    test_binary = test.withColumn("has_tip", (f.col("tip_category") > 0).cast("int"))

    print("== BINARY MODEL ==")

    print("Building and training binary model...")
    #train_binary_model(train_binary)

    print(test_binary.count())
    print("Predicting...")
    binary_preds = binary_prediction(test_binary)

    print("Evaluating...")
    binary_evaluation(binary_preds)

    print("== PREPARE MULTICLASS ==")

    print("Prepare data...")
    train_multi, test_multi, fn = prepare_data_multiclass(train_binary, binary_preds)

    if test_multi:
        print("== MULTICLASS MODEL ==")

        print("Building and training binary model...")
        #train_multiclass_model(train_multi)

        print("Predicting...")
        multiclass_preds = multiclass_prediction(test_multi)

        print("Evaluating...")
        multiclass_evaluation(multiclass_preds, fn = fn)

    output, _ = generate_output(multiclass_preds, binary_preds)

    output.show(truncate= False, n = 10)

    spark.stop()

if __name__ == "__main__":
    main()