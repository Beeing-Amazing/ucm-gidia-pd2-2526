"""To run this script, you need the optional project dependencies: `download`"""

import calendar
import io
import requests
from pathlib import Path
from typing import Type
from enum import Enum
from dataclasses import dataclass
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import choice
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
import pandas as pd

from scripts import utils
from .tlc_trip_record_data import download_trip_data
from .openmeteo_data import download_weather_data
from .openstreetmap_data import download_poi_data
from .cameras_511nyc import download_data_interactive
from .rollingsales_nyc_data import download_rolling_sales
from scripts import project_root, TAXI_ZONE, CLEAN_COL_NAMES, TAXI_ZONE_GEOJSON


logger = utils.get_logger("download")

kb = KeyBindings()

style = Style.from_dict({
    "selected-option": "fg:ansiblue",
})


@kb.add("j")
def _(event):
    event.current_buffer.auto_down()

@kb.add("k")
def _(event):
    event.current_buffer.auto_up()

@kb.add("q")
def _(event):
    event.app.exit(result=None)
    exit()


# ENDPOINT MENU
# ---


class Endpoint(Enum):
    """
    TLC_TRIP_RECORD_DATA: 
    - Calls sequentially given a date range
    - Ignores fails
    - Does not handle rate limits

    OPENMETEO_DATA:
    - Calls sequentially given a date range, for a list of locations
    - Retries on fail
    - Awaits rate limits
    - May partially exit if rate-limited

    OPENSTREETMAP_DATA:
    - Calls sequentially to query all POI types
    - Retries on a different endpoint on fail
    """

    TLC_TRIP_RECORD_DATA = 0 # https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
    NY511_EVENT_DATA = 1
    OPENMETEO_DATA = 2 # https://archive-api.open-meteo.com/v1/archive
    OPENSTREETMAP_DATA = 3 # https://overpass-api.de/api/interpreter
    NY511_CAMERAS_DATA = 4
    ROLLING_SALES_DATA = 5 # https://www.nyc.gov/site/finance/property/property-rolling-sales-data.page


def get_formatted_choices(labels: list[str], enum_type: Type[Enum]) -> list[tuple[Endpoint, str]]:
    """
    Indent multiline strings as left-aligned choices.

    :param labels: List of strings to use as choices' text
    :param enum_type: Members should be in the same order as choices
    :returns: Tuples as expected by toolkit_prompt choice options.

    Usage example:
    >>> labels = [
    ...     "Choice 1\\nDesc 1",
    ...     "Choice 2\\nDesc 2",
    ... ]
    >>> choices = get_formatted_choices(raw_labels, {...})
    >>> choice(
    ...     message=...,
    ...     options=choices
    ... )
    """

    choices = []
    for i, label in enumerate(labels):
        lines = label.split("\n")
        indented = lines[0] + "".join(
            "\n" + " " * 6 + line for line in lines[1:]
        )

        choices.append(
            (enum_type(i), indented)
        )
    return choices


def endpoint_choice() -> Endpoint:
    """Download endpoint choice menu"""

    raw_labels = [
        "TLC Trip Record Data\nTaxi and FHV trip record data",
        "511NY Alerts\nTraffic alerts event dataset",
        "Open-Meteo\nWeather condition data",
        "OpenStreetMap\nPoint of Interest location data",
        "511NY CamerasEvents\nTraffic cameras and future events datasets",
        "Rolling Sales NYC\nProperty rolling sales data for all 5 boroughs",
    ]
    choices = get_formatted_choices(raw_labels, Endpoint)

    try:
        result = choice(
            message="Choose endpoint:",
            options=choices,
            style=style,
            key_bindings=kb,
        )
    except KeyboardInterrupt:
        exit()

    return result


# GENERAL MENU FUNCS
# ---


@dataclass
class DateRange:
    start_year : int
    start_month : int
    end_year : int
    end_month : int


def general_date_range() -> DateRange:
    """Date range prompt"""

    try:
        while True:
            try:
                start_year_text = "Start year"
                start_year_def = "[2020]"
                start_year_visible = f"{start_year_text} {start_year_def}"
                start_year_padded = f"{start_year_visible:<19}"
                start_year_styled = start_year_padded.replace(start_year_def, f"<gray>{start_year_def}</gray>")
                start_year = prompt(HTML(f"{start_year_styled}: ")).strip()
                if start_year == "":
                    start_year = 2020
                if type(start_year) is int \
                    or (start_year.isdigit() and int(start_year) >= 2009):
                    start_year = int(start_year)
                    break
            except TypeError:
                continue
        while True:
            try:
                start_month_text = "Start month"
                start_month_def = "[1]"
                start_month_visible = f"{start_month_text} {start_month_def}"
                start_month_padded = f"{start_month_visible:<19}"
                start_month_styled = start_month_padded.replace(start_month_def, f"<gray>{start_month_def}</gray>")
                start_month = prompt(HTML(f"{start_month_styled}: ")).strip()
                if start_month == "":
                    start_month = 1
                if type(start_month) is int \
                    or (start_month.isdigit() \
                    and int(start_month) >= 1 \
                    and int(start_month) <= 12):
                    start_month = int(start_month)
                    break
            except TypeError:
                continue
        while True:
            try:
                end_year_text = "End year"
                end_year_def = f"[{start_year}]"
                end_year_visible = f"{end_year_text} {end_year_def}"
                end_year_padded = f"{end_year_visible:<19}"
                end_year_styled = end_year_padded.replace(end_year_def, f"<gray>{end_year_def}</gray>")
                end_year = prompt(HTML(f"{end_year_styled}: ")).strip()
                if end_year == "":
                    end_year = start_year
                if type(end_year) is int \
                    or (end_year.isdigit() \
                    and int(end_year) >= start_year):
                    end_year = int(end_year)
                    break
            except TypeError:
                continue
        while True:
            try:
                end_month_text = "End month"
                end_month_def = "[12]"
                end_month_visible = f"{end_month_text} {end_month_def}"
                end_month_padded = f"{end_month_visible:<19}"
                end_month_styled = end_month_padded.replace(end_month_def, f"<gray>{end_month_def}</gray>")
                end_month = prompt(HTML(f"{end_month_styled}: ")).strip()
                if end_month == "":
                    end_month = 12
                if type(end_month) is int \
                    or (end_month.isdigit() \
                    and int(end_month) >= 1 \
                    and int(end_month) <= 12):
                    end_month = int(end_month)
                    break
            except TypeError:
                continue
    except KeyboardInterrupt:
        exit()
    
    return DateRange(
        start_year=start_year,
        start_month=start_month,
        end_year=end_year,
        end_month=end_month
    )


# TLC TRIP RECORD
# ---


def tlc_trip_kind() -> str:
    """TLC vehicle kind choice menu"""

    choices = [
        ("yellow", "Yellow Taxis"),
        ("green", "Green Taxis"),
        ("fhv", "For-Hire Vehicles"),
        ("fhvhv", "High Volume For-Hire Vehicles"),
    ]
    try:
        result = choice(
            message="Select trip dataset:",
            options=choices,
            style=style,
            key_bindings=kb,
        )
    except KeyboardInterrupt:
        exit()

    return result


# OPENMETEO
# ---


def nyc_taxi_zones_geometry(dest : Path, override = False):
    """
    Download NYC Zone Polygons dataset

    :raises ConnectionError:
    :raises HTTPError:
    """

    # https://data.cityofnewyork.us/Transportation/NYC-Taxi-Zones/8meu-9t5y/about_data
    url_lookup_table = "https://data.cityofnewyork.us/resource/8meu-9t5y.csv"
    if not dest.exists() or override:
        response = requests.get(url_lookup_table, timeout=30)
        response.raise_for_status()
        logger.debug(f"fetched zone geometry")

        zones_df = pd.read_csv(io.StringIO(response.content.decode("utf-8")))
        zones_df.columns = CLEAN_COL_NAMES
        zones_df["id"] = zones_df.index + 1 # ids are already ordered, but some values are duplicate

        logger.debug(f"writing zone geometry to file: '{dest}'")
        zones_df.to_csv(dest, index=False, mode="w+") 


def openmeteo_request_type() -> str:
    """
    Open-Meteo request type prompt

    :returns: Either "d" or "h"
    """

    choices = [
        ("d", "Daily"),
        ("h", "Hourly"),
    ]
    try:
        result = choice(
            message="Select data precision:",
            options=choices,
            style=style,
            key_bindings=kb,
        )
    except KeyboardInterrupt:
        exit()

    return result


def openmeteo_zone_range() -> tuple[int,int]:
    """Zone range (by Location ID) prompt"""
    try:
        while True:
            try:
                start_id_text = "Start ID"
                start_id_def = "[1]"
                start_id_visible = f"{start_id_text} {start_id_def}"
                start_id_padded = f"{start_id_visible:<19}"
                start_id_styled = start_id_padded.replace(start_id_def, f"<gray>{start_id_def}</gray>")
                start_id = prompt(HTML(f"{start_id_styled}: ")).strip()
                if start_id == "":
                    start_id = 1
                if type(start_id) is int \
                    or (start_id.isdigit() and int(start_id) >= 1 and int(start_id) <= 263):
                    start_id = int(start_id)
                    break
            except TypeError:
                continue
        while True:
            try:
                end_id_text = "End ID"
                end_id_def = "[263]"
                end_id_visible = f"{end_id_text} {end_id_def}"
                end_id_padded = f"{end_id_visible:<19}"
                end_id_styled = end_id_padded.replace(end_id_def, f"<gray>{end_id_def}</gray>")
                end_id = prompt(HTML(f"{end_id_styled}: ")).strip()
                if end_id == "":
                    end_id = 263
                if type(end_id) is int \
                    or (end_id.isdigit() and int(end_id) >= start_id and int(end_id) <= 263):
                    end_id = int(end_id)
                    break
            except TypeError:
                continue
    except KeyboardInterrupt:
        exit()

    return (start_id, end_id)


# CAMERAS
# ---

def cameras_or_events_selection_dataset() -> str:
    """
    511NYC or getEvents or getCameras

    :returns: Either "cam" or "ev"
    """

    choices = [
        ("cam", "Traffic Cameras"),
        ("ev", "Future Events in NYC"),
    ]
    try:
        result = choice(
            message="Select data type:",
            options=choices,
            style=style,
            key_bindings=kb,
        )
    except KeyboardInterrupt:
        exit()

    return result

def cameras_futureEvents_request_type() -> str:
    """
    511NYC request type prompt

    :returns: Either "csv" or "json"
    """

    choices = [
        ("csv", "Complete CSV dataset"),
        ("json", "JSON file"),
    ]
    try:
        result = choice(
            message="Select data type:",
            options=choices,
            style=style,
            key_bindings=kb,
        )
    except KeyboardInterrupt:
        exit()

    return result


def main() -> None:
    match endpoint_choice():
        case Endpoint.TLC_TRIP_RECORD_DATA:
            kind : str = tlc_trip_kind()
            dates : DateRange = general_date_range()
            save_dir : str = f"data/raw/tlc_trip_record/{kind}"
            
            download_trip_data(
                start_year=dates.start_year,
                start_month=dates.start_month,
                end_year=dates.end_year,
                end_month=dates.end_month,
                kind=kind,
                save_dir=save_dir,
            )

        case Endpoint.OPENMETEO_DATA:
            req_type : str = openmeteo_request_type()
            dates : DateRange = general_date_range()
            id_range : tuple[int,int] = openmeteo_zone_range()
            save_dir : str = "data/raw/weather"

            # download and store taxi zone polygons if not already there
            nyc_taxi_zones_geometry(project_root / TAXI_ZONE)
            utils.write_nyc_taxi_zones_geojson(TAXI_ZONE_GEOJSON)

            download_weather_data(
                request_type=req_type, 
                start_date=f"{dates.start_year}-{dates.start_month:02}-01", 
                end_date=f"{dates.end_year}-{dates.end_month:02}-{calendar.monthrange(dates.end_year, dates.end_month)[1]}", 
                start_id=id_range[0], 
                end_id=id_range[1]
            )

        case Endpoint.OPENSTREETMAP_DATA:
            download_poi_data()

        case Endpoint.NY511_CAMERAS_DATA:
            dataset_choice = cameras_or_events_selection_dataset()
            req_type : str = cameras_futureEvents_request_type()

            # download and store taxi zone polygons if not already there
            nyc_taxi_zones_geometry(project_root / TAXI_ZONE)
            utils.write_nyc_taxi_zones_geojson(TAXI_ZONE_GEOJSON)

            download_data_interactive(dataset_choice,req_type)

        case Endpoint.ROLLING_SALES_DATA:
            download_rolling_sales()

        case _:
            pass


if __name__ == "__main__":
    main()
