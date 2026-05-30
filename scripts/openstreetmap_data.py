"""To run this script, you need the optional project dependencies: `download`"""

import time
from pathlib import Path

import pandas as pd
import geopandas as gpd

import requests
from typing import Optional
from dataclasses import dataclass
from tqdm import tqdm

from scripts import utils
from scripts import project_root, TAXI_ZONE


logger = utils.get_logger(__name__)


NYC_BBOX = "40.50,-74.26,40.92,-73.69"

ENDPOINTS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

RAW_POIS_PATH = project_root / "data" / "raw" / "pois"
CLEAN_POIS_PATH = project_root / "data" / "clean" / "pois"

POI_GROUPS = {
    'transport': [
        'amenity_parking', 'amenity_taxi', 'amenity_fuel',
        'public_transport_station', 'toll_yes'
    ],
    'food_drink': [
        'amenity_restaurant', 'amenity_cafe','amenity_fast_food'
    ],
    'healthcare': [
        'amenity_hospital', 'amenity_clinic', 'amenity_dentist'
    ],
    'entertainment': [
        'amenity_cinema', 'amenity_theatre', 'tourism_museum',
        'amenity_events_venue', 'amenity_music_venue'
    ],
    'tourism':[
        'tourism_attraction', 'tourism_theme_park', 'tourism_zoo',
        'tourism_yes', 'historic_building'
    ],
    'nightlife_alcohol': [
        'amenity_nightclub', 'amenity_pub', 'amenity_biergarten', 'amenity_casino',
        'amenity_stripclub','amenity_bar',
    ],
    'accommodation': [
        'tourism_hotel', 'tourism_motel', 'building_hotel'
    ],
    'education': [
        'amenity_university', 'amenity_college', 'amenity_school', 'amenity_libray'
    ],
    'sports_fitness': [
        'leisure_fitness_centre', 'leisure_stadium'
    ],
    'government': [
        'amenity_courthouse', 'office_diplomatic'
    ],
    'commercial': [
        'shop_mall', 'building_office'
    ]
}

LIFECYCLE_PREFIXES = ('disused:', 'was:', 'demolished:', 'abandoned:', 'removed:')
CONSTRUCTION_KEYS = ('construction:amenity', 'construction:shop', 'construction:tourism')

@dataclass
class OpenStreetMapAPI:
    """
    Class that downloads Points of Interest (POI) from openstreetmap.org
    Could be extended to download other kinds of data.
    """
    user_agent : str = "Mozilla/5.0"
    timeout : int = 150

    def download_pois(
        self, 
        bbox: str,
        tag: str, 
        value: str,
        output_path: str,
        retry_delay: int = 5
    ):
        """
        Downloads all POI inside a bbox and saves to parquet.

        All possible names for tag and value are in: 
        https://wiki.openstreetmap.org/wiki/Map_features

        e.g. If you want to download hospitals you will need to use
        tag = "amenity" and "value" = "hospital".

        :param bbox: bounding box in format "min_lat,min_lon,max_lat,max_lon"
        :param tag: OSM tag (e.g., "amenity", "shop", "tourism")
        :param value: tag value (e.g., "hospital", "restaurant")
        :param retry_delay: seconds to wait before switching endpoints
        """
        query = f"""
        [out:json][timeout:{self.timeout + 30}][bbox:{bbox}];
        (
            node[{tag}={value}];
            way[{tag}={value}];
            relation[{tag}={value}];
        );
        out center tags;
        """

        data = None
        for endpoint in ENDPOINTS:
            try:
                logger.info(f"Trying endpoint: {endpoint}")

                response = requests.get(
                    endpoint,
                    params={"data": query},
                    timeout=self.timeout,
                    headers={"User-Agent": self.user_agent}
                )

                logger.debug(f"Status: {response.status_code}")

                if response.status_code == 200:
                    data = response.json()
                    break

                time.sleep(retry_delay)

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout at {endpoint}")
                time.sleep(retry_delay)
                continue

            except Exception as e:
                logger.error(f"Error at {endpoint}: {e}")
                time.sleep(retry_delay)
                continue

        if data is None:
            logger.info("All endpoints failed")
            return

        output_name = f"{tag}_{value}.parquet"
        df = self._process_elements(data['elements'], value)
        if (len(df) != 0):
            self._save_data(df, output_path, output_name)
        else:
            logger.info(f"Skipping saving of data of len {len(df)} records.")


    def _process_elements(self, elements: list, category: str) -> pd.DataFrame:
        """
        Process OSM json to a pandas DataFrame.

        :returns: DataFrame with columns: category, osm_id, type, lat, lon, name, tags
        """
        records = []

        for elem in elements:
            coords = self._get_element_coords(elem)
            if coords is None:
                continue

            record = {
                'category' : category,
                'osm_id': elem['id'],
                'type': elem['type'],
                'lat': coords[0],
                'lon': coords[1],
                'name': elem.get('tags', {}).get('name', None),
                'tags': elem.get('tags', {})
            }
            records.append(record)

        return pd.DataFrame(records)


    def _save_data(self, df: pd.DataFrame, output_path: str, output_name:str):
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent.parent
        data_path = project_root / output_path / output_name
        data_path.parent.mkdir(parents=True, exist_ok=True)

        df.to_parquet(data_path, index=False, engine='pyarrow', compression='snappy')
        logger.info(f"Stored {len(df)} records to {data_path}")


    def _get_element_coords(self, element: dict) -> Optional[tuple]:
        if element['type'] == 'node':
            return (element['lat'], element['lon'])
        elif 'center' in element:
            return (element['center']['lat'], element['center']['lon'])
        return None


def _is_closed(tags: dict, target_date: pd.Timestamp) -> tuple[bool, str]:
    """
    :returns: (True, reason) if the POI should be filtered out, (False, '') otherwise.
    """
    # lifecycle prefix tags with a non-null value
    for key, val in tags.items():
        if val is None:
            continue
        if key.startswith(LIFECYCLE_PREFIXES):
            return True, key
        if key == 'disused' and val:
            return True, 'disused'
        if key in CONSTRUCTION_KEYS:
            return True, key

    # opened after target_date
    for date_key in ('opening_date', 'start_date'):
        raw = tags.get(date_key)
        if not raw:
            continue
        try:
            # Just in case we have weird datetimes.
            opened = parse_date(str(raw), default=pd.Timestamp('1900-01-01'))
            if pd.Timestamp(opened) > target_date:
                return True, f'{date_key}={raw}'
        except Exception:
            pass

    return False, ''


def filter_closed_pois(df: pd.DataFrame, poi_name: str, target_date: str = "2025-11-30") -> pd.DataFrame:
    """
    Removes POIs that are closed, disused, demolished, or not yet open by target_date.
    Logs a summary of what was filtered and why.
    """
    ts = pd.Timestamp(target_date)
    reasons: dict[str, int] = {}
    keep_mask = []

    for tags in df['tags']:
        closed, reason = _is_closed(tags, ts)
        keep_mask.append(not closed)
        if closed:
            reasons[reason] = reasons.get(reason, 0) + 1

    mask = pd.Series(keep_mask, index=df.index)
    filtered = df[mask]
    n_dropped = len(df) - len(filtered)

    if n_dropped:
        logger.info(f"[{poi_name}] dropped {n_dropped}/{len(df)} records: {reasons}")
    else:
        logger.info(f"[{poi_name}] no closed POIs found ({len(df)} records kept)")

    return filtered


def load_taxi_zones(taxi_path: Path = TAXI_ZONE) -> gpd.GeoDataFrame:
    """
    Loads "NYC_Taxi_Zones.csv" in a pandas DataFrame.
    Converts the df in a GeoDataFrame from geopandas.
    """
    zone_pdf = pd.read_csv(taxi_path)
    # zone_pdf = zone_pdf.rename(columns={
    #     "Shape Geometry": "geometry", 
    #     "Shape Length": "length", 
    #     "Shape Area": "area", 
    #     "Location ID": "id", 
    #     "Zone": "zone", 
    #     "Borough": "borough"
    # })
    zone_pdf['geometry'] = zone_pdf['geometry'].apply(wkt.loads)

    gdf = gpd.GeoDataFrame(zone_pdf, crs="EPSG:4326")
    gdf = gdf.drop(columns=["length", "area"])
    # Project to EPSG:2263 to calculate area in feet.
    gdf_pro = gdf.to_crs("EPSG:2263")
    # Convert to miles
    gdf["length_miles"] = gdf_pro.geometry.length / 5280
    gdf["area_miles2"] = gdf_pro.geometry.area / 5280**2

    return gdf


def load_all_pois(pois_path: Path = RAW_POIS_PATH, target_date: str = "2025-11-30") -> gpd.GeoDataFrame:
    """
    Loads all point of interest from 'pois_path' and returns a GeoDataFrame
    with only the necessary columns: geometry, poi_type, osm_id.
    Filters out closed, disused, demolished, or not-yet-open POIs.
    """
    all_pois = []
    parquet_files = list(pois_path.glob("*.parquet"))

    logger.info(f"Filtering POIs closed before {target_date}...")
    for file_path in parquet_files:
        # Extract category from file name
        # Ej: "amenity_bar.parquet" -> main_category="amenity", sub_category="bar"
        filename = file_path.stem  # exclude the extension .parquet
        main_category, sub_category = filename.split('_', 1)

        # Read all columns to access tags for filtering, then drop tags after
        df = pd.read_parquet(file_path, columns=['osm_id', 'lat', 'lon', 'tags'])
        df = filter_closed_pois(df, filename, target_date)
        df = df.drop(columns=['tags'])

        # Add poi_type
        df['poi_type'] = f"{main_category}_{sub_category}"

        all_pois.append(df)

    # Combine all
    combined_df = pd.concat(all_pois, ignore_index=True)

    # Create geometry from lat/lon
    combined_df['geometry'] = combined_df.apply(
        lambda row: Point(row['lon'], row['lat']), axis=1
    )

    # Convert to GeoDataFrame with only necessary columns
    gdf_pois = gpd.GeoDataFrame(
        combined_df[['osm_id', 'poi_type', 'geometry']], 
        crs="EPSG:4326"
    )

    return gdf_pois


def zone_poi_counts(zones_gdf: gpd.GeoDataFrame, pois_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Counts how many of each POI are in a taxi zone.

    Returns:
        DataFrame: zone, borough, geometry + columns for each POI
    """

    # Spatial join: each POI is assigned to a zone.
    pois_with_zones = gpd.sjoin(
        pois_gdf[['geometry', 'poi_type']], 
        zones_gdf[['id', 'zone', 'borough', 'geometry']], 
        how='left', 
        predicate='within'
    )

    # count POIs by zone and type
    counts = pois_with_zones.groupby(['id', 'poi_type']).size().reset_index(name='count')

    # Pivot to get a column for each type of POI
    counts_pivot = counts.pivot(index='id', columns='poi_type', values='count').fillna(0).astype(int)

    result = zones_gdf[['id', 'zone', 'borough', 'geometry', 'length_miles', 'area_miles2']].merge(
        counts_pivot, 
        left_on='id', 
        right_index=True, 
        how='left'
    )

    # Fill zones with Nan POI with zero.
    poi_columns = counts_pivot.columns.tolist()
    result[poi_columns] = result[poi_columns].fillna(0).astype(int)

    # Convert to WKT so coordinates are human readable
    result['geometry'] = result['geometry'].apply(lambda geom: geom.wkt)

    return result


def zone_poi_groups(zones_gdf: gpd.GeoDataFrame, pois_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Counts how many of each group of POI are in a taxi zone.

    :returns: DataFrame: zone, borough, geometry + columns for each group of POI
    """

    poi_groups = POI_GROUPS

    poi_to_group = {}
    for group_name, poi_types in poi_groups.items():
        for poi_type in poi_types:
            poi_to_group[poi_type] = group_name

    pois_gdf['poi_group'] = pois_gdf['poi_type'].map(poi_to_group)

    # Just in case.
    pois_gdf['poi_group'] = pois_gdf['poi_group'].fillna('other')

    pois_with_zones = gpd.sjoin(
        pois_gdf[['geometry', 'poi_group']], 
        zones_gdf[['id', 'zone', 'borough', 'geometry']], 
        how='left', 
        predicate='within'
    )

    # Counts how many group of POI are in each zone
    counts = pois_with_zones.groupby(['id', 'poi_group']).size().reset_index(name='count')

    # Pivot to get a column for each group of POI
    counts_pivot = counts.pivot(index='id', columns='poi_group', values='count').fillna(0).astype(int)

    result = zones_gdf[['id', 'zone', 'borough', 'geometry', 'length_miles', 'area_miles2']].merge(
        counts_pivot, 
        left_on='id', 
        right_index=True, 
        how='left'
    )

    # Fill zones with Nan POI with zero.
    group_columns = counts_pivot.columns.tolist()
    result[group_columns] = result[group_columns].fillna(0).astype(int)

    # Convert to WKT so coordinates are human readable
    result['geometry'] = result['geometry'].apply(lambda geom: geom.wkt)    
    return result


def density(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates POI density per square mile for each zone.
    Returns a new DataFrame with only base columns + density columns.

    :param df: DataFrame with POI counts and 'area_miles2' column
    :returns: DataFrame with base columns + density columns only
    """
    # Base columns to keep
    base_columns = ['id', 'zone', 'borough', 'geometry', 'length_miles', 'area_miles2']

    # Identify POI columns
    poi_columns = [col for col in df.columns if col not in base_columns]

    # Start with base columns
    result = df[base_columns].copy()

    # Calculate density for each POI column
    for col in poi_columns:
        density_col = f"{col}_per_mi2"
        # Replace 0 area with NaN to avoid division by zero, then fill with 0
        result[density_col] = df[col] / df['area_miles2'].replace(0, float('nan'))
        result[density_col] = result[density_col].fillna(0)
        # Round to 2 decimals for readability
        result[density_col] = result[density_col].round(2)

    return result


def clean_pois():
    CLEAN_POIS_PATH.mkdir(parents=True, exist_ok=True)
    zones_gdf = load_taxi_zones()
    
    pois_gdf = load_all_pois()
    
    with tqdm(
        total=4,
        desc="Transforming data",
        bar_format="{desc:19}: [{bar:30}] {percentage:3.0f}% {n_fmt}/{total_fmt}"
    ) as pbar:
        pbar.update(1)
        pbar.write("\n1/4 Generating individual counts...")
        zones_individual_counts = zone_poi_counts(zones_gdf, pois_gdf)
        output_file_1 = CLEAN_POIS_PATH / "zones_with_poi_counts.parquet"
        zones_individual_counts.to_parquet(output_file_1, index=False)
        logger.debug(f"Saved: {output_file_1}")
        logger.debug(f"Shape: {zones_individual_counts.shape}")

        pbar.update(1)
        pbar.write("\n2/4 Generating individual density...")
        zones_individual_density = density(zones_individual_counts)
        output_file_2 = CLEAN_POIS_PATH / "zones_with_poi_density.parquet"
        zones_individual_density.to_parquet(output_file_2, index=False)
        logger.debug(f"Saved: {output_file_2}")
        logger.debug(f"Shape: {zones_individual_density.shape}")

        pbar.update(1)
        pbar.write("\n3/4 Generating grouped counts...")
        zones_grouped_counts = zone_poi_groups(zones_gdf, pois_gdf)
        output_file_3 = CLEAN_POIS_PATH / "zones_with_poi_groups.parquet"
        zones_grouped_counts.to_parquet(output_file_3, index=False)
        logger.debug(f"Saved: {output_file_3}")
        logger.debug(f"Shape: {zones_grouped_counts.shape}")
        
        pbar.update(1)
        pbar.write("\n4/4 Generating grouped density...")
        zones_grouped_density = density(zones_grouped_counts)
        output_file_4 = CLEAN_POIS_PATH / "zones_with_poi_group_density.parquet"
        zones_grouped_density.to_parquet(output_file_4, index=False)
        logger.debug(f"Saved: {output_file_4}")
        logger.debug(f"Shape: {zones_grouped_density.shape}")


def download_poi_data(bbox : str = NYC_BBOX, poi_groups: dict[str, list[str]] = POI_GROUPS):
    """
    Script that downloads data from OpenStreetMap

    :param bbox: bounding box in format "min_lat,min_lon,max_lat,max_lon"
    :param poi_groups: dict with OSM tags, grouped inside categories. all values should be of the shape "tag_value"
    """

    output_dir = "data/raw/pois"
    downloader = OpenStreetMapAPI()
    all_tags = sorted({x for v in poi_groups.values() for x in v})

    for raw_tag in tqdm(
        all_tags,
        desc="Fetching data",
        bar_format="{desc:19}: [{bar:30}] {percentage:3.0f}% {n_fmt}/{total_fmt}"
    ):
        tag, value = raw_tag.split("_", maxsplit=1)
        downloader.download_pois(
            bbox=bbox,
            tag=tag,
            value=value,
            output_path=output_dir
        )

    clean_pois()


# Usage example
if __name__ == "__main__":
    downloader = OpenStreetMapAPI()

    downloader.download_pois(
        bbox=NYC_BBOX,
        tag="amenity",
        value="parking",
        output_path="data/raw/pois"
    )
