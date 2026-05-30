import json
import datetime
from pathlib import Path

from pyspark import SparkContext
from pyspark.sql import functions as F
from pyspark.sql import DataFrame, SparkSession
from pyspark.ml import Pipeline, PipelineModel
from pyspark.ml.functions import vector_to_array

from xgboost.spark import SparkXGBClassifier


WORKDIR = Path(__file__).resolve().parents[1]
MODEL_PATH = WORKDIR / "data" / "yellow_model"
YELLOW_DATA_PATH = WORKDIR / "data" / "clean" / "transformed_tlc_trip_record" / "yellow"


class TipsPredictionModel:
    
    def __init__(self):
        self.spark = SparkSession.builder.getOrCreate()
        self.xgboost_yellow = PipelineModel.load(str(MODEL_PATH))
        self.df = self.spark.read.parquet(str(YELLOW_DATA_PATH))

    def _filter(self, start_date : str, end_date : str) -> DataFrame:
        return self.df.where(F.col("pickup_datetime") < F.lit(end_date)) \
                .where(F.col("pickup_datetime") >= F.lit(start_date))

    def predict(self, today : str) -> DataFrame:
        today_date = datetime.datetime.strptime(today, "%Y-%m-%d")
        start_date = (today_date - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

        df = self._filter(
                start_date=start_date,
                end_date=today_date,
            )

        preds = self.xgboost_yellow.transform(df)
        preds = preds.withColumn(
            "prob_array", 
            vector_to_array(F.col("probability"))
        )
        for i in range(5):
            preds = preds.withColumn(f"prob_class_{i}", F.col("prob_array")[i])

        preds = preds.withColumnRenamed("PULocationID", "zone_id")

        return preds.select(
            "zone_id",
            "prediction",
            "prob_class_0",
            "prob_class_1",
            "prob_class_2",
            "prob_class_3",
            "prob_class_4"
        )


    def jsonify_output(self, pred: DataFrame, taxi_zones: str | Path) -> dict:
        with open(taxi_zones, "r") as file:
            zones = json.load(file)

        class_names = ["$0","$1-2","$2-3","$3-5","$5+"]
        values = {
            "prob_class_0": 0.0,
            "prob_class_1": 1.5,
            "prob_class_2": 2.5,
            "prob_class_3": 4.0,
            "prob_class_4": 6.0
        }

        pretty = []
        pred_dict = { row["zone_id"]: row.asDict() for row in pred.collect() }

        for feature in zones["features"]:
            props = feature["properties"]

            zone_id = props.get("id")
            zone_name = props.get("zone")
            borough = props.get("borough")

            row = pred_dict.get(zone_id, {})
            expected_tip = sum(
                row.get(k, 0.0) * v for k, v in values.items()
            )
            prediction = row.get("prediction")

            pretty.append({
                "zone_id": zone_id,
                "zone_name": zone_name,
                "borough": borough,
                "top_category": class_names[int(prediction)] if prediction is not None else "$0",
                "expected_tip_usd": expected_tip,
                "probabilities": {
                    "$0": row.get("prob_class_0"),
                    "$1-2": row.get("prob_class_1"),
                    "$2-3": row.get("prob_class_2"),
                    "$3-5": row.get("prob_class_3"),
                    "$5+": row.get("prob_class_4"),
                }
            })

        return {"zones": pretty}
