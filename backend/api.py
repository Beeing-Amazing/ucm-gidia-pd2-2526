import json
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse

from backend.stgcn import DemandPredictionModel
from backend.taxi_tips import TipsPredictionModel


router = APIRouter(prefix="/api", tags=["mobile-api"])

WORKDIR = Path(__file__).resolve().parents[1]
TAXI_ZONE = WORKDIR / "data" / "NYC_Taxi_Zones.json"
CAMERAS_FILE = WORKDIR / "data" / "NYC511" / "cameras_data.json"
# TIP_PREDICTIONS_FILE = WORKDIR / "data" / "preds" / "tip_predictions.json"

model_demand = None
model_tips = None


def _when_is_today_as_str():
    return "2025-04-01"

@router.get("/health")
def checkhealth():
    return {"ok": True}


# DEMAND
# ---

def demand_predictor() -> DemandPredictionModel:
    global model_demand
    if not model_demand:
        model_demand = DemandPredictionModel()
    return model_demand


@router.get("/predictions/demand")
async def predict_demand(is_fhvhv: bool):
    if ( pred_today_path := (
                WORKDIR / "data" / "preds" / \
                f"DEMAND-forecast_{'fhvhv' if is_fhvhv else 'taxi'}_{_when_is_today_as_str()}.json")
            ).exists():
        return FileResponse(pred_today_path)

    model = demand_predictor()
    pred = model.predict(today=_when_is_today_as_str(), is_fhvhv=is_fhvhv)
    output = model.jsonify_output(pred=pred, taxi_zones=TAXI_ZONE)

    if not pred_today_path.exists():
        pred_today_path.parent.mkdir(parents=True, exist_ok=True)
        with open(pred_today_path, "w") as f:
            json.dump(output, f)

    return output


# TIPS
# ---

def tips_predictor() -> DemandPredictionModel:
    global model_tips
    if not model_tips:
        model_tips = TipsPredictionModel()
    return model_tips


@router.get("/predictions/tips")
async def predict_tips():
    if ( pred_today_path := (
                WORKDIR / "data" / "preds" / \
                f"TIPS-{_when_is_today_as_str()}.json")
            ).exists():
        return FileResponse(pred_today_path)

    model = tips_predictor()
    pred = model.predict(today=_when_is_today_as_str())
    output = model.jsonify_output(pred, TAXI_ZONE)

    if not pred_today_path.exists():
        pred_today_path.parent.mkdir(parents=True, exist_ok=True)
        with open(pred_today_path, "w") as f:
            json.dump(output, f)
    return output


# DATA INSIGHTS
# ---

@router.get("/data/taxi_zone_lookup")
async def fetch_taxi_zones():
    return FileResponse(TAXI_ZONE)


@router.get("/data/nyc_traffic_cameras")
async def fetch_traffic_cameras():
    return FileResponse(CAMERAS_FILE)


@router.get("/insights/overview")
async def get_insights_overview(is_fhvhv: bool = False):
    cache_path = WORKDIR / "data" / "preds" / f"insights_overview_{'fhvhv' if is_fhvhv else 'taxi'}.json"
    if cache_path.exists():
        return FileResponse(cache_path)

    import pandas as pd
    df = pd.read_parquet(WORKDIR / "data" / "clean" / "taxi_zone_demand.parquet")

    src = "fhvhv" if is_fhvhv else "yellow"

    if is_fhvhv:
        df["_rank"] = df["trips_fhvhv"]
        df["_avg_daily"] = df["avg_daily_pickups"] * (1 - df["yellow_share_pct"] / 100)
        total = int(df["trips_fhvhv"].sum())
        share = 1 - df["yellow_share_pct"] / 100
    else:
        df["_rank"] = df["trips_yellow"]
        df["_avg_daily"] = df["avg_daily_pickups"] * df["yellow_share_pct"] / 100
        total = int(df["trips_yellow"].sum())
        share = df["yellow_share_pct"] / 100

    top = (
        df.nlargest(15, "_rank")[[
            "PULocationID", "pickup_zone", "pickup_borough",
            "_avg_daily", f"avg_fare_{src}", f"avg_tip_{src}", f"avg_tip_pct_{src}",
            f"avg_trip_miles_{src}", f"avg_trip_time_secs_{src}",
            "pickups_morning", "pickups_afternoon", "pickups_evening", "pickups_night",
        ]]
        .rename(columns={
            "_avg_daily": "avg_daily_pickups",
            f"avg_fare_{src}": "avg_fare",
            f"avg_tip_{src}": "avg_tip",
            f"avg_tip_pct_{src}": "avg_tip_pct",
            f"avg_trip_miles_{src}": "avg_trip_miles",
            f"avg_trip_time_secs_{src}": "avg_trip_time_secs",
        })
        .to_dict(orient="records")
    )

    output = {
        "total_trips": total,
        "avg_fare": round(float(df[f"avg_fare_{src}"].mean()), 2),
        "avg_tip_pct": round(float(df[f"avg_tip_pct_{src}"].mean()), 1),
        "avg_trip_miles": round(float(df[f"avg_trip_miles_{src}"].mean()), 1),
        "avg_trip_time_min": round(float(df[f"avg_trip_time_secs_{src}"].mean()) / 60, 1),
        "time_pattern": {
            band: round(float((df[f"pickups_{band}"] * share).sum()))
            for band in ("morning", "afternoon", "evening", "night")
        },
        "top_zones": top,
    }

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(output, f)

    return output

