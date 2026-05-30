"""To run this script, you need the optional project dependencies: `download`"""

import time
from pathlib import Path

import pandas as pd
import geopandas as gpd
from shapely import wkt  

import openmeteo_requests # the API used for data, see https://open-meteo.com/en/docs
import requests_cache
from retry_requests import retry
from tqdm import tqdm

from scripts import utils
from scripts import project_root, TAXI_ZONE


logger = utils.get_logger(__name__)


OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE_HOURLY_VARS=[
        "temperature_2m", 
        "apparent_temperature",
        "precipitation",
        "rain",
        "snowfall",
        "wind_speed_10m",
        "wind_gusts_10m",
        "relative_humidity_2m",
        "weather_code"
    ]
OPEN_METEO_ARCHIVE_DAILY_VARS=[
        "temperature_2m_mean",
        "temperature_2m_max",
        "temperature_2m_min",
        "apparent_temperature_mean",
        "precipitation_sum",
        "rain_sum",
        "snowfall_sum",
        "precipitation_hours",
        "wind_speed_10m_max",
        "wind_gusts_10m_max"
    ]


class OpenMeteoAPI:
    """
    Open-Meteo API client for NYC weather data retrieval and storage.
    Can fetch and store historical weather data. 
    Or fetch recent forecast weather data (yet to be implemented)

    Supports caching the api response, ideal for forecast data

    Usage example:
    >>> api = OpenMeteoAPI(cache=False)
    >>> df = api.store_data('h',lat=40.7128, lon=-74.0060, 
    ...                     start_date="2025-01-01", 
    ...                     end_date="2025-12-31", output_path="data/raw/weather/...")
    """

    def __init__(self, cache: bool =  False, cache_dir: str = '.cache'):
        """
        Initialize Open-Meteo API client for weather data.
        Args:
            cache : Boolean indicatiang if the fetched data from API should be cached
            cache_dir: Directory for caching recent data, will be ignored if cached = False
        """
        self._cache = cache
        self.cache_dir = cache_dir
        self._setup_client()
    
    @property
    def cache(self) -> bool:
        return self._cache
    @cache.setter
    def cache(self,cache: bool):
        if not (self._cache == cache) :
            self._cache = cache
            self._setup_client()

    def store_data(self, type: str, latitude: float, longitude: float, start_date: str, end_date: str, 
                            output_path: str, variables: list[str] = None) -> pd.DataFrame:
        """
        Fetch and store hourly weather data to Parquet
        Args:
            type: String from ['h','d'] indicating whether to retrieve hourly or monthly data
            latitude: Latitude of the requested zone
            longitude: Longitude of the requested zone
            start_date: Start date 'YYYY-MM-DD'
            end_date: End date 'YYYY-MM-DD'
            output_path: Output parquet path (e.g.,  'data/raw/weather/hourly/ZONE/2025.parquet'), will create directory if it doesn't exist
            variables: List of hourly variables (e.g., ['temperature_2m', 'precipitation'])
           
        Returns:
            DataFrame with hourly data
        Raises:
            openmeteo_requests.OpenMeteoRequestsError: error when the API call fails
        """
        
        df = self.fetch_data(type,latitude,longitude,start_date,end_date,variables)
        self._save_data(df,output_path)

        return df


    def fetch_data(self, type: str,latitude: float, longitude: float, start_date: str, end_date: str, 
                            variables: list[str] = None,) -> pd.DataFrame:
        """
        Fetch and store hourly weather data to Parquet
        Args:
            type: String from ['h','d'] indicating whether to retrieve hourly or monthly data
            latitude: Latitude of the requested zone
            longitude: Longitude of the requested zone
            start_date: Start date 'YYYY-MM-DD'
            end_date: End date 'YYYY-MM-DD'
            variables: List of hourly variables (e.g., ['temperature_2m', 'precipitation'])
        Returns:
            DataFrame with hourly data
        Raises:
            openmeteo_requests.OpenMeteoRequestsError: error when the API call fails
        """

        if variables is None:
            variables = (OPEN_METEO_ARCHIVE_HOURLY_VARS if type == 'h' 
                        else OPEN_METEO_ARCHIVE_DAILY_VARS)
        if type not in ['h', 'd']:
            raise ValueError("Type must be 'h' (hourly) or 'd' (daily)")
        key  = "hourly" if type == 'h' else "daily"
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date,
            "end_date": end_date,
            key: variables,
            "timezone": "America/New_York"
        }
        responses = self._client.weather_api(OPEN_METEO_ARCHIVE_URL, params=params)
        response = responses[0]
        response = response.Hourly() if type == 'h' else response.Daily()

        return self._extract_dataframe(response,variables)


    def _setup_client(self):
        """Setup client based on cache setting."""
        if not self._cache:
            self._client = openmeteo_requests.Client()
        else:     
            # Cached session for recent data (1 day expiration)
            cache_session = requests_cache.CachedSession(self.cache_dir, expire_after=86400)
            retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
            self._client = openmeteo_requests.Client(session=retry_session)


    def _extract_dataframe(self,data, variables : list[str]) -> pd.DataFrame :
        '''
        Extract dataframe from the API response
        Args:
            data: response object containing the final data
            variables: List of variable names (e.g., ['temperature_2m', 'precipitation'])
        Returns:
            DataFrame with data
        '''
        df = {
            "datetime": pd.date_range(
                start=pd.to_datetime(data.Time(), unit="s", utc=True),
                end=pd.to_datetime(data.TimeEnd(), unit="s", utc=True),
                freq=pd.Timedelta(seconds=data.Interval()),
                inclusive="left"
            )
        }
         # Extract each variable
        for i, var in enumerate(variables):
            df[var] = data.Variables(i).ValuesAsNumpy()
        return pd.DataFrame(df)


    def _save_data(self,df : pd.DataFrame, output_path : str):
        data_dir : Path = project_root / output_path
        data_dir.parent.mkdir(parents=True, exist_ok=True)

        df.to_parquet(data_dir, index=False, engine='pyarrow', compression='snappy')
        # tqdm.write(f"Stored {len(df)} records to {output_path}")


def _read_gdf(filename : str):
    
    try:
        df = pd.read_csv(project_root / filename)  # Columna 'geometry' con MULTIPOLYGON WKT
    except: 
        logger.error(f"Warning, can't find file '{filename}'")
        exit(1)
    # df = df.rename(columns ={"the_geom" : "geometry", "shape_leng" : "length", "shape_area" : "area", "locationid" : "id"})
    # Convierte WKT → geometría
    df['geometry'] = df['geometry'].apply(wkt.loads) 
    gdf = gpd.GeoDataFrame(df, crs='EPSG:4326')

    gdf_proj = gdf.to_crs('EPSG:2263')
    gdf_proj['centroid'] = gdf_proj.geometry.centroid
    gdf['lat'] = gdf_proj.centroid.to_crs('EPSG:4326').y
    gdf['lon'] = gdf_proj.centroid.to_crs('EPSG:4326').x
    return gdf


def download_weather_data(request_type: str, start_date, end_date, start_id, end_id):
    gdf = _read_gdf(TAXI_ZONE)
    api = OpenMeteoAPI(cache=False)

    downloaded = 0
    existed = 0
    failed = 0

    stop_requested = False

    with tqdm(
        total=(end_id-start_id)+1,
        desc="Fetching data",
        bar_format="{desc:19}: [{bar:30}] {percentage:3.0f}% {n_fmt}/{total_fmt}",
    ) as pbar:
        try:
            for i,id in enumerate(gdf["id"]):
                if stop_requested:
                    break
                if id < start_id:
                    continue
                if id > end_id:
                    break

                # check if the file already exits
                file = f"data/raw/weather/{'hourly' if request_type == 'h' else 'daily'}/{id}/{start_date}_{end_date}.parquet"
                if Path(file).exists():
                    existed += 1
                    pbar.update(1)
                # if not, then try to download
                else:
                    while True:
                        try:
                            api.store_data(
                                request_type,
                                gdf["lat"].iloc[i],
                                gdf["lon"].iloc[i],
                                start_date,
                                end_date,
                                file
                            )
                            downloaded += 1
                            pbar.update(1)
                            break

                        except openmeteo_requests.OpenMeteoRequestsError as e:  # Try capturing Minute limit, in such case we just wait 60 seconds
                            if "Minutely" in str(e):
                                tqdm.write(f"Minutely limit reached, sleeping and retrying in 60 seconds...")
                                for _ in tqdm(
                                    range(60),
                                    desc="Rate limit wait",
                                    leave=False,
                                    bar_format="{desc}: {n_fmt}/{total_fmt}s",
                                ):
                                    time.sleep(1)
                            else:
                                raise
                        except KeyboardInterrupt:
                            if Path(file).exists():
                                Path(file).unlink()
                            stop_requested = True

        except openmeteo_requests.OpenMeteoRequestsError:
            pass

    print(f"\033[92m{"Downloaded":<19}: {downloaded}\033[0m")
    print(f"\033[93m{"Already existed":<19}: {existed}\033[0m")
    print(f"\033[91m{"Failed":<19}: {failed}\033[0m")


if __name__ == "__main__":
    import sys 

    if len(sys.argv) != 6:
        print("Usage: <h|d> <start_date> <end_date> <start_id> <end_id>")
        print("\t This downloads weather data from start_date to end_date at a hourly/daily interval and saves them in 'data/raw/weather/<hourly/daily>/<locationID>/<start_date>_<end_date>.parquet'")
        print("\t You need the file 'data/NYC_Taxi_Zones.csv' to exist \n")
        print("An example usage is 'uv run <path from root project>/openmeteo.py h 2022-01-01 2025-12-31 1 263'")
        exit()
    req_type = sys.argv[1]
    start_date = sys.argv[2]
    end_date = sys.argv[3]
    try:
        start_id = int(sys.argv[4])
        end_id = int(sys.argv[5])
        if end_id < start_id:
            raise ValueError("<end_id> must be greater than <start_id>")
    except Exception as e:
        print(f"Can't parse <start_id> and <end_id>: {e}")
        exit(1)

    download_weather_data(req_type,start_date,end_date,start_id,end_id)

