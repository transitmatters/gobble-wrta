import json
import pathlib
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Dict, Optional

from logger import set_up_logging
from util import EASTERN_TIME

logger = set_up_logging(__name__)

MAIN_DIR = pathlib.Path("./data/")
MAIN_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = MAIN_DIR / "vehicle_states.json"

# any vehicle not updated in this long is dropped from memory -- bounds memory use, assumes
# no single vehicle run lasts longer than this
STALE_AFTER = timedelta(hours=5)


@dataclass
class VehicleState:
    trip_id: Optional[str]  # None until the first passage of this run is matched
    trip_id_is_synthesized: bool  # True if match_trip_id found no real GTFS trip
    route_id: str
    direction_id: int
    stop_sequence: int
    prev_stop_name: Optional[str]
    updated_at: datetime


_states: Dict[str, VehicleState] = {}
_lock = Lock()


def _serialize(state: VehicleState) -> dict[str, Any]:
    d = asdict(state)
    d["updated_at"] = state.updated_at.isoformat()
    return d


def _deserialize(d: dict[str, Any]) -> VehicleState:
    d = dict(d)
    d["updated_at"] = datetime.fromisoformat(d["updated_at"])
    return VehicleState(**d)


def _load() -> None:
    global _states
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            raw = json.load(f)
        _states = {key: _deserialize(value) for key, value in raw.items()}
        logger.info(f"Loaded {len(_states)} vehicle states")


def _save() -> None:
    with open(STATE_PATH, "w") as f:
        json.dump({key: _serialize(value) for key, value in _states.items()}, f)


def get_state(vehicle_key: str) -> Optional[VehicleState]:
    with _lock:
        return _states.get(vehicle_key)


def set_state(vehicle_key: str, state: VehicleState) -> None:
    with _lock:
        _states[vehicle_key] = state
        _save()


def cleanup_stale_states() -> None:
    with _lock:
        now = datetime.now(EASTERN_TIME)
        stale_keys = [
            key for key, state in _states.items() if now - state.updated_at > STALE_AFTER
        ]
        if not stale_keys:
            return
        for key in stale_keys:
            del _states[key]
        logger.info(f"Dropped {len(stale_keys)} stale vehicle states")
        _save()


_load()
