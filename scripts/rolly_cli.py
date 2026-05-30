# DEPRECATED: 

# rolly_cli.py was used for testing purposes before backend/rolly.py

from pathlib import Path

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from pprint import pprint as pp


_WORKDIR = Path(__file__).resolve().parent

# Mockup data
_DEMAND_PATH = _WORKDIR.parent / "data" / "clean" / "taxi_zone_demand.parquet"
_EVENTS_PATH = _WORKDIR.parent / "data" / "NYC511" / "events_info_complete.csv"


print(f"Loading data from: {_DEMAND_PATH}")
try:
    _demand: pd.DataFrame = pd.read_parquet(_DEMAND_PATH)
    print("Data loaded successfully")
except Exception as e:
    print(f"Error loading data: {e}")
    exit(1)

print(f"Loading data from: {_EVENTS_PATH}")
try:
    _events: pd.DataFrame = pd.read_csv(_EVENTS_PATH)
    _events['StartDate'] = pd.to_datetime(_events['StartDate'])
    _events['EndDate'] = pd.to_datetime(_events['EndDate'])
    print("Data loaded successfully")
except Exception as e:
    print(f"Error loading data: {e}")
    exit(1)

today = "2025-04-01"
today_day_of_week = "friday"
print(f"Today is {today}")

_llm = ChatOpenAI(
    model="gemma-4-e4b",
    base_url="http://localhost:1234/v1",
    api_key="lm-studio",
    temperature=0.0, # default = 0.8
)

# Fixed: "give me top 5 zones with highest tips and their zone details" 
# Rolly sometimes only calls get_top_tip_zones, but not get_zone_details.
# Rolly sometimes calls all tools needed (above) but only prints get_top_tip_zones
# information and he is unable to retrieve get_zone_details information.

_SYSTEM_PROMPT = """You are Rolly, a data assistant for NYC yellow taxi and rideshare drivers.

## TOOL USE — MANDATORY RULES
You MUST call tools before answering ANY question about zones, tips, or demand.
Chain tools when needed: call ALL required tools first, then give ONE final answer.
Never answer from memory. Never skip a tool call if data is missing. Think step by step.

If the driver asks for top tip zones AND their details -> call get_top_tip_zones THEN get_zone_details for each result.
If the driver asks for demand AND tips -> call both get_top_demand_zones AND get_top_tip_zones.
If the driver asks for event impact -> call get_top_events_zones with the right filters.
Only speak after all tool results are in hand.

## OUTPUT FORMAT
- 1-2 sentences max unless the driver asks for more or you think the query needs more sentences.
- Always include: zone name, borough, and the key metric (tip %, pickups, etc.).
- Never use zone IDs. Use names and boroughs only.
- Respond in the same language the driver uses.

## PERSONA
You are brief. You are behind the wheel with the driver. Every word counts.
"""

# Tools 

@tool
def get_top_demand_zones(time_of_day: str, top_n: int = 5) -> list[dict]:
    """
    Returns the zones with the highest average daily pickups.
    time_of_day options: morning (6-12), afternoon (12-18), evening (18-24), night (0-6), any.
    top_n: number of zones to return.
    """
    col_map = {
        "morning": "pickups_morning",
        "afternoon": "pickups_afternoon",
        "evening": "pickups_evening",
        "night": "pickups_night",
        "any": "avg_daily_pickups",
    }
    col = col_map.get(time_of_day.lower(), "avg_daily_pickups")

    if col not in _demand.columns:
        return [{"error": f"Column {col} not found in data"}]

    top = _demand.nlargest(top_n, col)[
        ["PULocationID", "pickup_zone", "pickup_borough", col, "avg_tip_pct"]
    ]
    # pp(f"   DEBUG: {top.rename(columns={col: "pickups"}).to_dict(orient="records")}")
    return top.rename(columns={col: "pickups"}).to_dict(orient="records")


@tool
def get_top_tip_zones(top_n: int = 5) -> list[dict]:
    """Returns the zones with the highest average tip percentage."""
    top = _demand.nlargest(top_n, "avg_tip_pct")[
        ["PULocationID", "pickup_zone", "pickup_borough", "avg_tip_pct", "avg_tip", "avg_daily_pickups"]
    ]
    # pp(f"   DEBUG: {top.to_dict(orient="records")}")
    return top.to_dict(orient="records")


@tool
def get_zone_details(zone_name: str) -> list[dict] | dict:
    """Returns details for one or more zones matching the name. 
    Use broad terms like 'airport' to find all matching zones."""
    res = _demand[_demand['pickup_zone'].str.contains(zone_name, case=False, na=False)]
    if res.empty:
        return {"error": "Zone not found"}
    # pp(f"   DEBUG: {res.to_dict(orient="records")}")
    return res.to_dict(orient="records")


@tool
def get_top_events_zones(top_n: int = 3, day: str |None = None) -> list[dict] | dict:
    """Returns the zones most affected by events. 
    'top_n' specifies how many areas to return, by default always give 3 and 'day' filters by a specific date. The date can be
    optional natural language date, such as: "today", "June 18th 2026", "2026-06-18".
    If the user gives a date without a year, assume the next upcoming occurrence. The result is calculated using:
    - numbers of events in the area
    - sum of all events in that zones AsistanceLevel
    If the user asked for the names of the events show the list EventNames
    """
    ev = _events.copy()
    if day is not None:
        day = pd.to_datetime(day).date()
        ev = ev[(ev['StartDate'].dt.date <= day) & (ev['EndDate'].dt.date >= day)]

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




_TOOLS = [get_top_demand_zones, get_top_tip_zones, get_zone_details, get_top_events_zones]
_llm_with_tools = _llm.bind_tools(_TOOLS)

# Terminal Execution Logic

def run_terminal_chat():
    print("\n" + "="*50)
    print("ROLLY: Museekar's assistant is online.")
    print("Type 'exit' or 'quit' to stop the conversation.")
    print("="*50 + "\n")

    print(_SYSTEM_PROMPT)

    messages = [SystemMessage(content=_SYSTEM_PROMPT)]

    while True:
        user_input = input("Driver: ").strip()

        if user_input.lower() in ["exit", "quit", "bye"]:
            print("Rolly: Safe driving! Goodbye.")
            break

        if not user_input:
            continue

        messages.append(HumanMessage(content=user_input))

        try:
            while True:
                response = _llm_with_tools.invoke(messages)

                print(f"    [Debug] tool_calls: {[tc['name'] for tc in response.tool_calls]}")
                messages.append(response)

                if not response.tool_calls:
                    print(f"\nRolly: {response.content}\n")
                    break

                for tool_call in response.tool_calls:
                    print(f"    [System: Rolly is checking data for {tool_call['name']}...]")

                    tool_fn = next(t for t in _TOOLS if t.name == tool_call["name"])
                    result = tool_fn.invoke(tool_call["args"])

                    messages.append(ToolMessage(
                        content=str(result),
                        tool_call_id=tool_call["id"],
                    ))

                    # messages.append(HumanMessage(
                    #     content="Do you have ALL the information needed to fully answer my question?"
                    #     "If not, call the necessary tools before responding."
                    # ))

        except Exception as e:
            print(f"\n[Error]: {e}")
            messages.append(HumanMessage(content="The assistant encountered an error. Please try again."))

if __name__ == "__main__":
    run_terminal_chat()
    
