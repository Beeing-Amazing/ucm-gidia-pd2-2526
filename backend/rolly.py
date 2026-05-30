from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import APIRouter
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
import datetime
import json
from backend.api import _when_is_today_as_str, demand_predictor, tips_predictor
from backend.stgcn import DemandPredictionModel



router = APIRouter(prefix="/api/rolly", tags=["rolly"])

_WORKDIR = Path(__file__).resolve().parents[1]
_DEMAND_PATH = _WORKDIR / "data" / "clean" / "taxi_zone_demand.parquet"
_EVENTS_PATH = _WORKDIR / "data" / "NYC511" / "events_info_complete.csv"
TAXI_ZONE = _WORKDIR / "data" / "NYC_Taxi_Zones.json"


_demand_history: pd.DataFrame = pd.read_parquet(_DEMAND_PATH)  # loaded once at startup
_events: pd.DataFrame = pd.read_csv(_EVENTS_PATH)
def _load_tip_preds() -> list[dict]:
    pred_today_path = _WORKDIR / "data" / "preds" / f"TIPS-{_when_is_today_as_str()}.json"
    if pred_today_path.exists():
        with open(pred_today_path, "r") as f:
            return json.load(f)["zones"]
    model = tips_predictor()
    output = model.jsonify_output(model.predict(today=_when_is_today_as_str()), TAXI_ZONE)
    pred_today_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pred_today_path, "w") as f:
        json.dump(output, f)
    return output["zones"]
_events['StartDate'] = pd.to_datetime(_events['StartDate'])
_events['EndDate'] = pd.to_datetime(_events['EndDate'])


def get_demand_forecast_data(is_fhvhv:bool):
    model = demand_predictor()

    today_str = _when_is_today_as_str()
    pred_today_path = (
                _WORKDIR / "data" / "preds" / \
                f"DEMAND-forecast_{'fhvhv' if is_fhvhv else 'taxi'}_{_when_is_today_as_str()}.json")
    if pred_today_path.exists():
        with open(pred_today_path, "r") as f:
            return json.load(f)
    pred = model.predict(today=_when_is_today_as_str(), is_fhvhv=is_fhvhv)
    output = model.jsonify_output(pred=pred, taxi_zones=TAXI_ZONE)

    pred_today_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pred_today_path, "w") as f:
        json.dump(output, f)

    return output

# Points to LM Studio running on the host; host.docker.internal resolves
# to the host machine from inside a Docker container.
_llm = ChatOpenAI(
    model="gemma-4-e4b",
    base_url="http://host.docker.internal:1234/v1",
    # base_url="http://localhost:1234/v1",  # use this when running outside Docker
    api_key="lm-studio",
    temperature=0.0,
)

# System prompt moved to backend/ROLLY.md
_SYSTEM_PROMPT = (Path(__file__).parent / "ROLLY.md").read_text()

# HISTORICAL TOOLS

@tool
def get_top_historic_demand_zones(time_of_day: str, is_fhvhv: bool | None = None, top_n: int = 5) -> list[dict]:
    """
    Returns zones with the highest historical pickups.
    time_of_day options: morning (6-12), afternoon (12-18), evening (18-24), night (0-6), any.
    is_fhvhv: True = fhvhv only, False = yellow taxi only, None = combined. Always ask the driver which service they drive.
    top_n: number of zones to return.
    Note: time-of-day breakdown is only available as combined (both services).
    """
    time_col_map = {
        "morning": "pickups_morning",
        "afternoon": "pickups_afternoon",
        "evening": "pickups_evening",
        "night": "pickups_night",
        "any": None,
    }
    time_col = time_col_map.get(time_of_day.lower())

    if time_col:
        sort_col = time_col
    elif is_fhvhv is True:
        sort_col = "trips_fhvhv"
    elif is_fhvhv is False:
        sort_col = "trips_yellow"
    else:
        sort_col = "avg_daily_pickups"

    tip_col = "avg_tip_pct_fhvhv" if is_fhvhv is True else ("avg_tip_pct_yellow" if is_fhvhv is False else "avg_tip_pct")
    trips_col = "trips_fhvhv" if is_fhvhv is True else ("trips_yellow" if is_fhvhv is False else "avg_daily_pickups")

    top = _demand_history.nlargest(top_n, sort_col)[
        ["pickup_zone", "pickup_borough", sort_col, trips_col, tip_col]
    ]
    return top.rename(columns={sort_col: "pickups", trips_col: "total_trips", tip_col: "avg_tip_pct"}).to_dict(orient="records")


@tool
def get_top_tip_zones(is_fhvhv: bool | None = None, top_n: int = 5) -> list[dict]:
    """
    Returns zones with the highest historical average tip percentage.
    is_fhvhv: True = fhvhv only, False = yellow taxi only, None = combined. Always ask the driver which service they drive.
    top_n: number of zones to return.
    Note: no time-of-day breakdown available for tips. This always returns overall historical averages.
    """
    if is_fhvhv is True:
        tip_pct_col, tip_col, trips_col = "avg_tip_pct_fhvhv", "avg_tip_fhvhv", "trips_fhvhv"
    elif is_fhvhv is False:
        tip_pct_col, tip_col, trips_col = "avg_tip_pct_yellow", "avg_tip_yellow", "trips_yellow"
    else:
        tip_pct_col, tip_col, trips_col = "avg_tip_pct", "avg_tip", "avg_daily_pickups"

    top = _demand_history.nlargest(top_n, tip_pct_col)[
        ["pickup_zone", "pickup_borough", tip_pct_col, tip_col, trips_col]
    ]
    return top.rename(columns={tip_pct_col: "avg_tip_pct", tip_col: "avg_tip", trips_col: "total_trips"}).to_dict(orient="records")


@tool
def get_zone_details(zone_name: str, is_fhvhv: bool | None = None) -> list[dict] | dict:
    """
    Returns historical details for zones matching the name.
    Use broad terms like 'airport' to find all matching zones.
    is_fhvhv: True = fhvhv columns, False = yellow taxi columns, None = all columns.
    """
    res = _demand_history[_demand_history["pickup_zone"].str.contains(zone_name, case=False, na=False)]
    if res.empty:
        return {"error": "Zone not found"}

    base_cols = ["pickup_zone", "pickup_borough", "avg_daily_pickups", "yellow_share_pct"]
    if is_fhvhv is True:
        cols = base_cols + ["trips_fhvhv", "avg_fare_fhvhv", "avg_tip_fhvhv", "avg_tip_pct_fhvhv", "avg_trip_miles_fhvhv", "avg_trip_time_secs_fhvhv"]
    elif is_fhvhv is False:
        cols = base_cols + ["trips_yellow", "avg_fare_yellow", "avg_tip_yellow", "avg_tip_pct_yellow", "avg_trip_miles_yellow", "avg_trip_time_secs_yellow"]
    else:
        cols = res.columns.tolist()

    return res[cols].to_dict(orient="records")

# EVENTS TOOL

@tool
def get_top_events_zones(top_n: int = 3, day: str |None = None) -> list[dict] | dict:
    """Returns the zones most affected by events. 
    'top_n' specifies how many areas to return, by default always give 3 and 'day' filters by a specific date. The date can be
    optional natural language, such as: "today", "June 18th 2026", "2026-06-18".
    If the user gives a date without a year, assume the next upcoming occurrence. The result is calculated using:
    - numbers of events in the area
    - sum of all events in that zones AsistanceLevel
    If the user asked for the names of the events show the list EventNames
    """
    ev = _events.copy()
    if day is not None:
        _today = datetime.date.fromisoformat(_when_is_today_as_str())
        _relative = {"today": _today, "tomorrow": _today + datetime.timedelta(days=1), "yesterday": _today - datetime.timedelta(days=1)}
        if day.lower() in _relative:
            parsed_day = _relative[day.lower()]
        elif day.lower().startswith("next "):
            _weekdays = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
            wd_name = day.lower().replace("next ", "")
            target_wd = _weekdays.get(wd_name)
            if target_wd is not None:
                days_ahead = (target_wd - _today.weekday() + 7) % 7 or 7
                parsed_day = _today + datetime.timedelta(days=days_ahead)
            else:
                parsed_day = pd.to_datetime(day).date()
        else:
            parsed_day = pd.to_datetime(day).date()
        ev = ev[(ev['StartDate'].dt.date <= parsed_day) & (ev['EndDate'].dt.date >= parsed_day)]

    if ev.empty:
        return []
    #agrupación y agregación
    ev = ev.sort_values("AsistanceLevel", ascending=False)
    agg = ev.groupby(['zone', 'CountyName']).agg(
        num_events=("EventName","count"),
        sum_assistance=("AsistanceLevel","sum"),
        list_names=("EventName", lambda x: x.dropna().head(3).tolist())
    ).sort_values(by=["sum_assistance", "num_events"], ascending=False).head(top_n).reset_index()

    result = agg.to_dict(orient="records")
    return result

# PREDICTION TOOLS

@tool
def get_top_predicted_demand_zones(is_fhvhv: bool, top_n: int = 5, hours_from_now: int = 1) -> list[dict] | dict:
    """
    Returns the zones with the highest probability of demand.
    is_fhvhv: if true, data of fhvhv, else taxi data.
    top_n: number of zones to return, default 5.
    hours_from_now: how many hours from now to forecast. Pass exactly what the driver says.
      Examples: "next hour" -> hours_from_now=1, "in 2 hours" -> hours_from_now=2, "in 5 hours" -> hours_from_now=5.
      Default is 1 (next hour). Do NOT subtract 1 — pass the number directly.
    """
    pred_data = get_demand_forecast_data(is_fhvhv)
    hour = hours_from_now - 1  # convert to 0-based forecast index

    forecast = pred_data.get("forecast", [])
    if not forecast:
        return {"error": "Prediction data not found"}

    match = next((f for f in forecast if f['hour'] == hour),None)

    if match is None:
        return {"error": "prediciton data for this hour not found"}
    
    df_zones = pd.DataFrame(match["zones"])

    df_zones = df_zones.sort_values(by="predicted_pickups", ascending=False).head(top_n)

    return df_zones.to_dict("records")


@tool
def get_predicted_demand_for_zone(zone_name: str, is_fhvhv: bool, max_hours: int | None = None) -> list[dict] | dict:
    """
    Returns hourly demand predictions for a specific zone.
    zone_name: partial or full zone name (case-insensitive match).
    is_fhvhv: if true, fhvhv data; else yellow taxi data.
    max_hours: pass exactly what the driver says. "next 5 hours" -> max_hours=5. None = all hours.
    The result field 'next_hour' means: 1 = next hour from now, 2 = two hours from now, etc.
    """
    if _demand_history[_demand_history["pickup_zone"].str.contains(zone_name, case=False, na=False)].empty:
        return {"error": f"Zone '{zone_name}' not found in dataset"}
    
    pred_data = get_demand_forecast_data(is_fhvhv)
    forecast = pred_data.get("forecast", [])
    if not forecast:
        return {"error": "Prediction data not found"}

    results = []
    for entry in forecast:
        if max_hours is not None and entry["hour"] >= max_hours:
            break
        df_zones = pd.DataFrame(entry["zones"])
        match = df_zones[df_zones["zone_name"].str.contains(zone_name, case=False, na=False)]
        for row in match.to_dict("records"):
            row["next_hour"] = entry["hour"] + 1
            results.append(row)

    if not results:
        return {"error": f"Zone '{zone_name}' not found in predictions"}

    return results


@tool
def get_tip_prediction(zone_name: str) -> list[dict] | dict:
    """Returns the model predicted tip breakdown for zones matching the name.
    Includes expected_tip_usd (weighted average) and probability per tip category ($0, $1-2, $2-3, $3-5, $5+).
    Use broad terms like 'airport' to match multiple zones.
    Prefer this over get_top_tip_zones when the driver asks about tips for a specific zone."""
    matches = [z for z in _load_tip_preds() if zone_name.lower() in z["zone_name"].lower()]
    if not matches:
        return {"error": f"No zone found matching '{zone_name}'"}
    return matches


_TOOLS = [
    get_top_predicted_demand_zones,
    get_predicted_demand_for_zone,
    get_top_historic_demand_zones,
    get_top_tip_zones,
    get_tip_prediction,
    get_zone_details,
    get_top_events_zones,
]

_llm_with_tools = _llm.bind_tools(_TOOLS)


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[HistoryMessage] = []
    debug: bool = False
    system_prompt_override: str | None = None  # "" = no system prompt, None = use default


class ChatResponse(BaseModel):
    response: str
    tool_calls_made: list[dict] = []  # populated when debug=True


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    # Rebuild the full message list from scratch on every request
    # the client owns the history, so the backend stays stateless.
    if req.system_prompt_override is None:
        system_prompt = _SYSTEM_PROMPT
    else:
        system_prompt = req.system_prompt_override

    messages: list = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))

    for msg in req.history:
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        else:
            messages.append(AIMessage(content=msg.content))

    messages.append(HumanMessage(content=req.message))

    tool_calls_made: list[dict] = []

    # Agentic loop: keep calling the LLM until it stops requesting tools.
    while True:
        response = _llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            return ChatResponse(
                response=response.content,
                tool_calls_made=tool_calls_made if req.debug else [],
            )

        for tc in response.tool_calls:
            tool_fn = next(t for t in _TOOLS if t.name == tc["name"])
            result = tool_fn.invoke(tc["args"])
            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
            if req.debug:
                tool_calls_made.append({"name": tc["name"], "args": tc["args"]})
