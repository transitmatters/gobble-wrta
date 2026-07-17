import datetime
import pathlib
import shutil
import time
import urllib.request
from dataclasses import dataclass
from threading import Lock, Thread
from typing import List, Optional, Set

import pandas as pd

import util
from logger import set_up_logging

logger = set_up_logging(__name__)

MAIN_DIR = pathlib.Path("./data/")
MAIN_DIR.mkdir(parents=True, exist_ok=True)

GTFS_PREFIX = "https://data.trilliumtransit.com/gtfs/wrta-ma-us/"
GTFS_FILENAME = "wrta-ma-us.zip"

# only fetch required columns from gtfs csv's to reduce memory usage
STOP_TIMES_COLS = [
    "stop_id",
    "trip_id",
    "arrival_time",
    "departure_time",
    "stop_id",
    "stop_sequence",
]

current_gtfs = None
write_gtfs_lock = Lock()

def get_services(date: datetime.date, archive_dir: pathlib.Path) -> List[str]:
    """
    Read calendar.txt to determine which services ran on the given date.
    Also, incorporate exceptions from calendar_dates.txt for holidays, etc.
    """
    dateint = util.to_dateint(date)
    day_of_week = date.strftime("%A").lower()

    cal = pd.read_csv(archive_dir / "calendar.txt")
    current_services = cal[(cal.start_date <= dateint) & (cal.end_date >= dateint)]
    services = current_services[current_services[day_of_week] == 1]["service_id"].tolist()

    exceptions = pd.read_csv(archive_dir / "calendar_dates.txt")
    exceptions = exceptions[exceptions.date == dateint]
    additions = exceptions[exceptions.exception_type == 1]["service_id"].tolist()
    subtractions = exceptions[exceptions.exception_type == 2]["service_id"].tolist()

    services = (set(services) - set(subtractions)) | set(additions)
    return list(services)


@dataclass
class GTFS:
    # All trips on all routes
    trips: pd.DataFrame
    # All stop times on all trips
    stop_times: pd.DataFrame
    # All stops
    stops: pd.DataFrame
    # The current service date
    service_date: datetime.date


def get_gtfs():
    """Downloads and unpacks the current GTFS bundle, returning the directory it was extracted
    to. WRTA publishes only the active bundle with no historical archive, so there's no date
    parameter here -- read_gtfs applies the service-date filtering afterward."""
    gtfs_url = GTFS_PREFIX + GTFS_FILENAME
    gtfs_name = pathlib.Path(gtfs_url).stem

    # download active GTFS
    logger.info(f"Downloading GTFS: {gtfs_url}")
    zipfile, _ = urllib.request.urlretrieve(gtfs_url)
    shutil.unpack_archive(zipfile, extract_dir=(MAIN_DIR / gtfs_name), format="zip")

    # remove temporary zipfile
    urllib.request.urlcleanup()

    return MAIN_DIR / gtfs_name


def read_gtfs(date: datetime.date, routes_filter: Optional[Set[str]] = None) -> GTFS:
    """
    Given a date, this function will:
    - Find the appropriate gtfs archive (downloading if necessary)
    - Determine which services ran on that date
    - Return three dataframes containing just the trips and stop_times that ran on that date,
        and corresponding stop information

    If a route filter is applied, only return trips and stop information relevent to supplied routes.
    Otherwise, return all services.
    """

    archive_dir = get_gtfs()
    services = get_services(date, archive_dir)

    # specify dtypes to avoid warnings
    trips = pd.read_csv(
        archive_dir / "trips.txt", dtype={"trip_short_name": str, "block_id": str}
    )
    trips = trips[trips["service_id"].isin(services)]

    # filter by routes
    if routes_filter:
        trips = trips[trips["route_id"].isin(routes_filter)]

    stops = pd.read_csv(archive_dir / "stops.txt")

    stop_times = pd.read_csv(
        archive_dir / "stop_times.txt",
        dtype={"trip_id": str, "stop_id": str},
        usecols=STOP_TIMES_COLS,
    )
    stop_times = stop_times[stop_times["trip_id"].isin(trips["trip_id"])]
    stop_times["arrival_time"] = pd.to_timedelta(stop_times["arrival_time"])
    stop_times["departure_time"] = pd.to_timedelta(stop_times["departure_time"])

    return GTFS(trips=trips, stop_times=stop_times, stops=stops, service_date=date)


def update_current_gtfs_if_necessary():
    """Compares the current GTFS service date to the current date, downloading and
    processing a new GTFS bundle if needed"""
    global current_gtfs
    global write_gtfs_lock
    with write_gtfs_lock:
        gtfs_service_date = util.service_date(datetime.datetime.now(util.EASTERN_TIME))
        needs_update = (
            current_gtfs is None or current_gtfs.service_date != gtfs_service_date
        )
        if needs_update:
            if current_gtfs is None:
                logger.info(f"Missing GTFS, downloading for {gtfs_service_date}")
            else:
                logger.info(
                    f"Updating GTFS from {current_gtfs.service_date} to {gtfs_service_date}"
                )
            current_gtfs = read_gtfs(gtfs_service_date)


def update_gtfs_thread():
    while True:
        update_current_gtfs_if_necessary()
        time.sleep(10)


def start_watching_gtfs():
    gtfs_thread = Thread(target=update_gtfs_thread, name="update_gtfs")
    gtfs_thread.start()


def get_current_gtfs() -> GTFS:
    global current_gtfs
    if current_gtfs is None:
        update_current_gtfs_if_necessary()

    if current_gtfs is None:
        raise RuntimeError("Unable to get current GTFS")
    return current_gtfs
