"""To run this script, you need the optional project dependencies: `download`"""

import sys
import requests
from pathlib import Path

from tqdm import tqdm

from scripts import utils
from scripts import project_root


logger = utils.get_logger(__name__)


BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"

def download_trip_data(
    start_year : int, 
    start_month : int, 
    end_year : int, 
    end_month : int, 
    kind : str, 
    save_dir : str,
):
    """
    Script that downloads the data from:
    https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page    
    """

    valid_kinds = {"yellow", "green", "fhv", "fhvhv"}

    if kind not in valid_kinds:
        raise ValueError(f"kind invalid. Use: {valid_kinds}")

    try:
        data_dir = project_root / save_dir

        data_dir.mkdir(parents=True, exist_ok=True)
    except:
        logger.error("bad destination dir")
        raise OSError("bad destination dir")

    downloaded = 0
    existed = 0
    failed = 0

    with tqdm(
        total=((end_year*12+end_month)-(start_year*12+start_month)+1),
        desc="Fetching data",
        bar_format="{desc:19}: [{bar:30}] {percentage:3.0f}% {n_fmt}/{total_fmt}"
    ) as pbar:
        for year in range(start_year, end_year + 1):
            for month in range(start_month, end_month + 1):
                filename = f"{kind}_tripdata_{year}-{month:02d}.parquet"
                url = f"{BASE_URL}/{filename}"
                destination = data_dir / filename

                if destination.exists():
                    existed += 1
                    pbar.update(1)
                else:
                    try:
                        with requests.get(url, stream=True, timeout=30) as response:
                            response.raise_for_status()
                            total_size = int(response.headers.get("content-length", 0))

                            with tqdm(
                                total=total_size,
                                unit="B",
                                unit_scale=True,
                                unit_divisor=1024,
                                desc=filename,
                                bar_format="{desc:32}: [{bar:17}] {percentage:3.0f}% {n_fmt}/{total_fmt}",
                                leave=False,
                                position=1
                            ) as file_pbar:
                                with open(destination, "wb") as f:
                                    for chunk in response.iter_content(chunk_size=8192):
                                        if chunk:
                                            f.write(chunk)
                                            file_pbar.update(len(chunk))
                            downloaded += 1

                    except requests.RequestException:
                        failed += 1
                        if destination.exists():
                            destination.unlink()
                    finally:
                        pbar.update(1)

    print(f"\033[92m{"Downloaded":<19}: {downloaded}\033[0m")
    print(f"\033[93m{"Already existed":<19}: {existed}\033[0m")
    print(f"\033[91m{"Failed":<19}: {failed}\033[0m")


if __name__ == "__main__":

    # Example:
    # uv run tlc_trip_record_data.py 2024 1 2024 2 yellow data/tlc_trip_record/yellow
    # Downloads the data from 2024 january and february of yellow cabs 
    # and saves it in data/tlc_trip_record/yellow

    if len(sys.argv) != 7:
        print("Usage: <start_year> <start_month> <end_year> <end_month> <kind> <save_dir>")
        sys.exit(1)
    
    start_year = int(sys.argv[1])
    start_month = int(sys.argv[2])
    end_year = int(sys.argv[3])
    end_month = int(sys.argv[4])
    kind = sys.argv[5]
    save_dir = sys.argv[6]

    download_trip_data(start_year, start_month,end_year,end_month, kind, save_dir)
