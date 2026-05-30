from datetime import datetime
from pathlib import Path

from airflow.decorators import dag, task

from scripts.cli_download import nyc_taxi_zones_geometry
from scripts.utils import write_nyc_taxi_zones_geojson, get_logger
from scripts.cameras_511nyc import download_cameras_interactive

from scripts import TAXI_ZONE, TAXI_ZONE_GEOJSON


# TODO: fetch:
# - [x] taxi zones
# - [x] cameras
# - [ ] events
# - [ ] pois

@dag(
    start_date=datetime(2026, 1, 1),
    schedule="@monthly",
    max_consecutive_failed_dag_runs=3,
    default_args={
        "owner": "museekar",
        "retries": 0,
    },
    is_paused_upon_creation=True,
    catchup=False,
)
def nyc_general_etl():
    """"""

    logger = get_logger("airflow.task")

    @task
    def fetch_taxi_zones():
        """
        Download NYC Taxi Zone Polygons.
        Write to CSV and JSON.

        :raises ConnectionError:
        :raises HTTPError:
        """

        dest_csv : Path = TAXI_ZONE
        dest_json : Path = TAXI_ZONE_GEOJSON

        try:
            # logger.info("started task")
            nyc_taxi_zones_geometry(
                dest=dest_csv,
                override=False
            )
        except Exception as ex:
            logger.warning(f"cannot reach endpoint")
            logger.error("error when handling taxi zones geometry", exc_info=True)
            raise ex

        write_nyc_taxi_zones_geojson(
            dest=dest_json,
            override=False
        )


    @task
    def fetch_cameras():
        """
        Download 511NY camera metadata and url.
        Write to CSV and JSON.
        """

        try:
            download_cameras_interactive("csv")
            download_cameras_interactive("json")
        except Exception as ex:
            logger.error("error when handling cameras data", exc_info=True)
            raise ex


    # dependencies
    # ---

    fetch_taxi_zones()
    fetch_cameras()


nyc_general_etl()
