import os
from pathlib import Path

project_root : Path = Path(os.getenv(
    "AIRFLOW_HOME",
    Path(__file__).resolve().parents[1])
)
TAXI_ZONE : Path = project_root / "data" / "NYC_Taxi_Zones.csv"
CLEAN_COL_NAMES : list[str] = ["geometry","length","area","zone","id","borough"]
TAXI_ZONE_GEOJSON : Path = project_root / "data" / "NYC_Taxi_Zones.json"

LOG_DIR : Path = project_root / "logs"
LOG_LEVEL : str = "INFO"
