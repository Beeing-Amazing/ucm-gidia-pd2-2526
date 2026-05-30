"""To run this script, you need the optional project dependencies: `download`"""

import os
from pathlib import Path

import pandas as pd
import geopandas as gpd
from shapely import wkt

import json
import requests
import logging

from scripts import utils
from .utils import load_dotenv
from scripts import project_root, TAXI_ZONE


env = load_dotenv(".env")


HTTP_TIMEOUT_SECONDS = 30
NY511_API_URL = "https://511ny.org/api/"
NY511_API_KEY = env['NY511_API_KEY'] if "NY511_API_KEY" in env.keys() else ""

OUTPUT_CAMERAS_PATH_CSV = project_root / "data" / "NYC511"/ "cameras_info_complete.csv"
OUTPUT_CAMERAS_PATH_JSON = project_root / "data" / "NYC511"/ "cameras_data.json"
OUTPUT_EVENTS_PATH_CSV = project_root / "data" / "NYC511"/"events_info_complete.csv"
OUTPUT_EVENTS_PATH_JSON = project_root / "data" /"NYC511"/ "events_info.json"


logger = utils.get_logger(__name__)

#Coordinates of New York City
lat_extreme1 = 40.49
lat_extreme2 = 40.92
long_extreme1 = -74.27
long_extreme2 = -73.70


# The descriptions of the events follow a very similar structure, hence the keywords.
POPULAR_SPORTS = [
    "basketball",
    "baseball",
    "football",
    "soccer",
    "hockey",
    "tennis",
    "wrestling"
]

# the capacity and the location of the different places where events are carried out
CAPACITY_FACILITIES = {
    "madison square garden": 20000, #New York Kniks (NBA),New York Rangers (hockey) and boxing
    "barclays center": 18000, #Brooklyn Nets (NBA), New York Islanders (hockey)
    "citi field": 45000, #New York Mets (MLB queens)
    "arthur ashe stadium": 23000, #tennis
    "yankee stadium": 55000, #New York Yankees(MLB Bronx), New York City FC (soccer)
    "forest hills stadium": 14000, #tennis
    "flushing meadows corona park": 40000, #park
    "pier 17": 3500, #rooftop
    "the beacon theatre": 2100, #entertainment venue,
    "radio city music hall": 6000, #entertainment venue,
    "central park": None #cannot estimate, it dependes on the event
}

EVENT_GROUP = {
    "music": ["concert"],
    "sports" : POPULAR_SPORTS,
    "shows": ["show", "comedy","podcast", "play/show"],
    "open_air_events": ["race event", "race", "parade", "fair", "skating", "festival"],
}

WEEKDAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]



#########################
#   CAMERAS FUNCTIONS   #
#########################
def fetch_511events_cameras():
    """
    Fetches data from the 511NY API: the cameras that are located in the area of New York City and that are not disabled. 
    The area is defined by the latitude and longitude extremes.
    """
    try:
        cameras_result: list[dict] = []
        #GETCAMERAS
        response = requests.get(NY511_API_URL+"getcameras?", params={"key": NY511_API_KEY, "format": "json"}, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        response_data = response.json()
        camaras_result = []
        for d in response_data:
            lat = d.get("Latitude", "Unknown")
            long = d.get("Longitude", "Unknown")
            disable = d.get("Disabled", True)
            bloqued = d.get("Blocked", True)
            if lat != "Unknown" and lat >= lat_extreme1 and lat<= lat_extreme2 and \
            long != "Unknown" and long >= long_extreme1 and long <= long_extreme2 and \
            disable == False and bloqued == False:
                cameras_result.append(d)

    except:
        logger.error("error when pulling cameras from 511NY API", exc_info=True)
        raise

    return cameras_result


def _read_gdf_new_df(filename : str, cam: list[dict])-> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Function that reads the taxi zones file and the cameras list of dictionaries. Then it does a spatial join
    to get in what zone are the cameras located.

    Args: 
        filename (str): The name of the file that contains the taxi zones information.
        cam (list[dict]): The list of dictionaries that contains the cameras information.

    Returns:
        tuple[gpd.GeoDataFrame (cameras), gpd.GeoDataFrame (zones)]
    """
    try:
        df = pd.read_csv(project_root / filename)  # 'geometry' column with MULTIPOLYGON WKT
    except: 
        print(f"Warning, can't find file '{filename}'")
        exit(1)
    df = df.rename(columns ={"the_geom" : "geometry", "shape_leng" : "length", "shape_area" : "area", "locationid" : "id"})
    # Converts WKT → geometry
    df['geometry'] = df['geometry'].apply(wkt.loads)
    gdf = gpd.GeoDataFrame(df, crs='EPSG:4326')
    cam_df = pd.DataFrame(cam)
    cameras_gdf = gpd.GeoDataFrame(cam_df, 
                                    geometry=gpd.points_from_xy(cam_df['Longitude'], cam_df['Latitude']),
                                    crs = 'EPSG:4326')
    #spatial join to get in what zone are the cameras located
    join_inner_df = cameras_gdf.sjoin(gdf, how="inner")
    return join_inner_df, gdf


def _group_cams_in_zones(cam_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    # Group the cameras by zone and count the number of cameras in each zone, 
    # also creating a list of the camera ids and video urls in each zone
    cam_gdf['id_cam'] = cam_gdf['Url'].apply(lambda x: x.split('/')[-1] if x else None)
    df_count = cam_gdf.groupby(["id", "zone", "borough"]).agg(
        num_cameras=('id', 'count'),
        cameras_ids=('id_cam', list),
        video_urls= ('VideoUrl', list)
    ).reset_index()

    # instead of [nan] -> None
    df_count['video_urls'] = df_count['video_urls'].apply(lambda x: x if isinstance(x, list) and not pd.isna(x).all() else None)
    df_count['cameras_ids'] = df_count['cameras_ids'].apply(lambda x: x if isinstance(x, list) and not pd.isna(x).all() else None)

    return df_count


def replace_nan_in_dict(x):
    if isinstance(x, dict):
        return {k: replace_nan_in_dict(v) for k,v in x.items()}
    elif isinstance(x, list):
        return [replace_nan_in_dict(v) for v in x]
    elif pd.isna(x):
        return None
    
    return x
    

def _cams_in_dict(cam_gdf: gpd.GeoDataFrame):
    cam_gdf['id_url_cam'] = cam_gdf['Url'].apply(lambda x: x.split('/')[-1] if x else None)
    cam_gdf = cam_gdf.where(cam_gdf.notna(), None)
    dict_info = (cam_gdf.groupby("id").apply(
        lambda x: x[["ID","RoadwayName", "DirectionOfTravel", "id_url_cam","VideoUrl", "Latitude", "Longitude"]].to_dict("records")
    ).to_dict())

    dict_info = replace_nan_in_dict(dict_info)

    return dict_info


def save_cam(path: Path, cam_gdf: gpd.GeoDataFrame, columns: list[str] = None, grouped = False):
    if grouped:
        #group by zone the cameras
        info_cam_df = _group_cams_in_zones(cam_gdf)
    else:
        info_cam_df = cam_gdf

    if columns:
        selected_df = info_cam_df[columns]
    else:
        selected_df = info_cam_df

    os.makedirs(os.path.dirname(path), exist_ok=True)
    selected_df.to_csv(path, index=False)


def save_cam_to_json(path: Path, cam_gdf: gpd.GeoDataFrame, columns: list[str] = None):
    data = _cams_in_dict(cam_gdf)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def download_cameras_interactive(type_download: str):
    cam = fetch_511events_cameras()
    cam_zones, gdf = _read_gdf_new_df(TAXI_ZONE, cam)
    if type_download == "csv":
        save_cam(OUTPUT_CAMERAS_PATH_CSV, cam_zones)
    elif type_download == "json":
        save_cam_to_json(OUTPUT_CAMERAS_PATH_JSON, cam_zones)


#########################
#   EVENTS FUNCTIONS   #
#########################
def fetch_511events_data():
    """
    Fetches data from the 511NY API, specifically the special events that happen in the area of New York City.
    """
    try:
        events_results: list[dict] = []
        response = requests.get(NY511_API_URL+"getevents?", params={"key": NY511_API_KEY, "format": "json"}, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        response_data = response.json()
        # filtering special events that happen in the area of New York City
        events_result = [d for d in response_data if ((d.get("EventType", "Unknown") == "specialEvents") and (d.get("RegionName", "Unknown") == "New York City Area"))]
    except:
        logger.error("Error al obtener datos para getEvents", exc_info=True)

    return events_result

def _nyc_important_cultural_locations_levels(name : str)-> int |None :
    """
    Returns the level of importance for a cultural location in New York City based on its capacity.
    """
    name = name.lower()
    if name not in CAPACITY_FACILITIES:
        return None
    
    capacity = CAPACITY_FACILITIES[name]

    if capacity is None:
        return None
    if capacity >= 20000:
        return int(3)
    if capacity >= 10000:
        return int(2)
    if capacity < 10000:
        return int(1)
    return None

def _nyc_event_group_selection(name: str) -> str:
    """
    Returns the group of the event based on its name, if it does not belong to any group, it returns the name of the event.
    """
    name = name.lower()
    names = name.split()
    for k, v in EVENT_GROUP.items():
        for n in names:
            if n in v:
                return k
    return name

def _is_the_row_of_the_event(row):
    """
    Returns True if the row corresponds to an event, False otherwise. We consider that a row corresponds to an event if 
    the description of the event contains the name of any of the important cultural locations in New York City.
    """
    places = CAPACITY_FACILITIES.keys()
    road = row['RoadwayName'].lower()
    if road in places:
        return True
    return False

def _separate_events_traffic(df):
    #Separates the events from the traffic impacts
    events = df[df.apply(_is_the_row_of_the_event, axis = 1)].copy()
    traffic_impact = df[~df.apply(_is_the_row_of_the_event, axis = 1)].copy() #due to the events
    return events, traffic_impact

def _search_venue_in_desc(text: str):
    text = text.lower()
    venues = CAPACITY_FACILITIES.keys()
    for venue in venues:
        if venue in text:
            return venue
    return None

def _get_event_name_from_description(text: str):
    """
    Function that infers the name of the event from the description
    Args:
        text (str): The description of the event.
    Returns:
        str: The name of the event
    """

    text = str(text).strip().lower()

    #The description normally follows 2 structures
    #First, the name appears before "Closures are at the discretion of the NYPD."
    #And after at (New York)
    if ("closures are" in text) and ("nypd" in text):
        idx_closures = text.find("closures")
        first_part = text[:idx_closures]

        idx_place = first_part.rfind(")")
        if idx_place != -1:
            name = first_part[idx_place + 1:]
            name = name.rstrip(".").strip()
            if name:
                return name
            else:
                return None
            
    #Cases where in the description the date is indicated
    #(location) Name of the event. Date
    idx_min = 100000000
    day_final = ""
    for day in WEEKDAYS:
        idx_day = text.find(day)
        if idx_day != -1 and idx_day < idx_min:
            idx_min = idx_day
            day_final = day

    if idx_min == -1 or idx_min == 100000000:
        return None
    else:
        first_part = text[:idx_min]

    idx_place = first_part.rfind(")")
    if idx_place != -1:
        name = first_part[idx_place + 1:]
        name = name.rstrip(", ").strip()
        if name:
            return name
        else:
            return None
    return None

def _second_try_event_match(unmatched_impacts: pd.DataFrame) -> pd.DataFrame:
    """
    Function that tries to match the unmatched impacts with the events by infering the name of the event
    """
    #We create a new column with the possible name of the event extracted form description 
    cols_for_group = ["EventType","EventSubType", "StartDate", "EventName"]

    df_group = unmatched_impacts.groupby(cols_for_group)

    rows_list = []
    for cols, df in df_group:
        topRow = df.iloc[0].copy()

        #STREET DICTIONARY
        street_dict = {}
        for idx, row in df.iterrows():
            street = row["RoadwayName"]
            if street not in street_dict:
                street_dict[street] = {
                    "Street": street,
                    "Latitude": row["Latitude"],
                    "Longitude": row["Longitude"]
                }
        list_of_streets = list(street_dict.values())
        count_roads = len(list_of_streets)

        if count_roads > 1:
            topRow["RoadwayName"] = "SEVERAL STREETS"
            topRow["Latitude"] = df["Latitude"].mean()
            topRow["Longitude"] = df["Longitude"].mean()
            topRow["RoadsAffected"] = list_of_streets
            topRow["CountRoadsAffected"] = count_roads

        rows_list.append(topRow) 
    df_final = pd.DataFrame(rows_list)
    #df_final = df_final.drop("EventName", axis = 1)       

    return df_final

def add_roadways(events: pd.DataFrame, impact: pd.DataFrame) -> pd.DataFrame:
    """
    Function that adds the roadways affected by the events to the events dataframe. It tries to match the events with the impacts by infering the name of the event from the description of the impact.
    If it finds a match, it adds the     roadway to the list of roadways affected by the event and updates the count of roadways affected. If it does not find a match, it adds the impact to a list of unmatched impacts that will be processed later.
    Args: 
        events (pd.DataFrame): The dataframe that contains the actual events information.
        impact (pd.DataFrame): The dataframe that contains the impacts of the event information.
    Returns:
        pd.DataFrame: The dataframe that contains the actual events information with the roadways that are affected.
    """
    impact["inferred_venue"] = impact["Description"].apply(_search_venue_in_desc)
    rows_not_matched = []
    #print(events.shape, impact.shape)
    #we can iterate through the df because of its small size
    for idx, row in impact.iterrows():
        venue = row["inferred_venue"]
        start_date = row["StartDate"]

        if venue is None:
            rows_not_matched.append(row)
            continue


        matches = events[
            (events["RoadwayName"].str.lower()==venue) & (events["StartDate"]==start_date)
        ]

        if len(matches) == 1:
            idx_event = matches.index[0]
            list_roads = events.loc[idx_event, "RoadsAffected"]
            new_road = row["RoadwayName"]
            num_roads = int(events.at[idx_event, "CountRoadsAffected"])

            if num_roads == 0:
                list_roads = []

            street_dict = {d['Street']: d for d in list_roads}   

            if new_road not in street_dict:
                street_dict[new_road] = {
                    "Street": new_road,
                    "Latitude": row["Latitude"],
                    "Longitude": row["Longitude"]
                }

                list_roads = list(street_dict.values())
                events.at[idx_event, "RoadsAffected"] = list_roads
                events.at[idx_event, "CountRoadsAffected"] = num_roads + 1

        else:
            rows_not_matched.append(row)

    #Now we iterate through the different rows that did not match an event to see if there exists any pattern between some of them
    unmatched_impacts = pd.DataFrame(rows_not_matched)

    unmatched_impacts = unmatched_impacts.drop("inferred_venue", axis = 1)
    unmatched_impacts = _second_try_event_match(unmatched_impacts)
    df_final = pd.concat([events, unmatched_impacts])

    return df_final

def events_transformations(df: pd.DataFrame, filename:str) -> pd.DataFrame:
    """
    Function that transforms the events dataframe by:
     - selecting the relevant columns
     - filtering the events that are not cultural events
     - adding the level of importance of the event based on the location where it is carried out
     - inferring the name of the event from the description and separating the actual events from the traffic impacts. 
     - adding the roadways affected by each event.
    """
    column_selection = ["ID", "EventType", "EventSubType", "RoadwayName", "Latitude", "Longitude",
                        "CountyName","Schedule", "Description"]
    df_transform = df[column_selection]
    #ignore opertational activities to only get the cultural ones
    df_transform = df_transform[df_transform['EventSubType'] != "Operational activity"]
    df_transform = df_transform[~df_transform['EventSubType'].str.contains("Special event")]

    # 3 if the events happens in a facility with a lot of capacity, 2 is intermediate and 1 is a smaller place
    df_transform["AsistanceLevel"] = df_transform['RoadwayName'].apply(_nyc_important_cultural_locations_levels).astype("Int64")
    
    # start and end of the events
    time_format = "%d/%m/%Y %H:%M:%S"
    df_transform['StartDate'] = df_transform['Schedule'].apply(lambda x: x[0]['Start'] if x else None)
    df_transform["EventName"] = df_transform["Description"].apply(_get_event_name_from_description)
    df_transform["EventName"] = df_transform["EventName"].str.strip().str.lower()
    
    df_transform['StartDate'] = pd.to_datetime(df_transform['StartDate'], format=time_format)
    df_transform['EndDate'] = df_transform['Schedule'].apply(lambda x: x[0]['End'] if x else None)
    df_transform['EndDate'] = pd.to_datetime(df_transform['EndDate'], format=time_format)
    df_transform = df_transform.drop(columns = 'Schedule')

    df_transform['EventType'] = df_transform['EventSubType'].apply(_nyc_event_group_selection)
    df_transform['RoadsAffected'] = df_transform['ID'].apply(lambda x: [])
    if "CountRoadsAffected" not in df_transform.columns:
        df_transform['CountRoadsAffected'] = 0

    real_event, road_impacts = _separate_events_traffic(df_transform)
    df_final = add_roadways(real_event, road_impacts)

    #add_zones
    try:
        df_zones = pd.read_csv(project_root / filename)  # 'geometry' column with MULTIPOLYGON WKT
    except: 
        print(f"Warning, can't find file '{filename}'")
        exit(1)
    # Converts WKT → geometry
    df_zones['geometry'] = df_zones['geometry'].apply(wkt.loads)
    gdf = gpd.GeoDataFrame(df_zones, geometry = "geometry", crs = 'EPSG:4326')
    df_points = gpd.GeoDataFrame(df_final, geometry=gpd.points_from_xy(df_final['Longitude'], df_final['Latitude']),
                                crs = 'EPSG:4326')
    df_final = df_points.sjoin(gdf, how="inner")
    df_final = pd.DataFrame(df_final)
    
    select_cols = ["EventName", "EventType", "EventSubType", "StartDate","EndDate", "Latitude","Longitude","RoadwayName", "id", "zone",
                    "CountyName", "AsistanceLevel", "CountRoadsAffected", "RoadsAffected"]
    df_final = df_final[select_cols]



    return df_final




def save_events(path: Path, ev: list[dict]):
    df = pd.DataFrame(ev)
    df = events_transformations(df, TAXI_ZONE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    df.to_csv(path, index=False)

def save_events_to_json(path: Path, ev: list[dict]):
    df = pd.DataFrame(ev)
    df = events_transformations(df)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_json(path,orient='records',indent= 4, date_format='iso', force_ascii=False)


###########################
#         RESULTS         #
###########################


def download_events_interactive(type_download: str):
    ev = fetch_511events_data()
    if type_download == "csv":
        save_events(OUTPUT_EVENTS_PATH_CSV, ev)
    elif type_download == "json":
        save_events_to_json(OUTPUT_EVENTS_PATH_JSON, ev)

def download_data_interactive(choice: str, type_download: str):
    if choice == "cam":
        download_cameras_interactive(type_download)
    else:
        download_events_interactive(type_download)


def display_results(events : list[dict], display_type: str):
    """
    Displays the results of the API calls, showing only the first 10 events or cameras, depending on the type.

    Args:
        events (list[dict]): The list of events or cameras to display.
        type (str): The type of data to display ("ev" for events, "cam" for cameras).
    """
    if len(events) > 0:
        print(len(events))
        for x in events[:10]:
            if display_type == "ev":
                print("TIPO DE EVENTO:", x.get("EventType", "Unknown"))
                print("NOMBRE REGIÓN:", x.get("RegionName", "Unknown"))
                print("NOMBRE COUNTY:", x.get("CountyName", "Unknown"))
                print("DESCRIPCIÓN:", x.get("Description", "Unknown"))
                print("FECHA INICIO:", x.get("StartDate", "Unknown"))
                print("FECHA FIN:", x.get("EndDate", "Unknown"))
                print("ESTADO:", x.get("LanesStatus", "Unknown"))
                print("SEVERIDAD:", x.get("Severity", "Unknown"))

            else:
                print("CARRETERA:", x.get("RoadwayName", "Unknown"))
                print("DIRECCIÓN:", x.get("DirectionOfTravel", "Unknown"))
                print("CAMARAS:", x.get("Url", "Unknown"))
                print("CAMARAS VIDEO:", x.get("VideoUrl", "Unknown"))
                print("DESCRIPCIÓN:", x.get("Name", "Unknown"))
                print("UBICACIÓN", x.get("Latitude"), x.get("Longitude"))



if __name__ == "__main__":
    import sys
    cams_or_event = sys.argv[1]
    req_type = sys.argv[2]

    download_data_interactive(cams_or_event,req_type)
