import csv
import pathlib
from typing import Any

import pandas as pd

import util
from logger import set_up_logging

logger = set_up_logging(__name__)

MAIN_DIR = pathlib.Path("./data/")

# column order matches the data dashboard's expected CSV schema
CSV_FIELDS = [
    "service_date",
    "route_id",
    "trip_id",
    "direction_id",
    "stop_id",
    "stop_sequence",
    "vehicle_id",
    "vehicle_label",
    "event_type",
    "event_time",
    "scheduled_headway",
    "scheduled_tt",
    "vehicle_consist",
    "occupancy_status",
    "occupancy_percentage",
]


def write_events(events_df: pd.DataFrame) -> None:
    for row in events_df.itertuples():
        _write_row(row)


def _write_row(row) -> None:
    dir_path = MAIN_DIR / util.output_dir_path(
        row.route_id, row.direction_id, row.stop_id, row.event_time
    )
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / "events.csv"

    write_header = not file_path.exists()
    with open(file_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(_row_to_csv_dict(row))


def _row_to_csv_dict(row) -> dict[str, Any]:
    d: dict[str, Any] = {}
    for field in CSV_FIELDS:
        value = getattr(row, field)
        if field == "event_time" and isinstance(value, pd.Timestamp):
            value = value.isoformat()
        elif pd.isna(value):
            value = ""
        d[field] = value
    return d
