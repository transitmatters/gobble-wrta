from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Dict, List, Optional

import lookups
import vehicles
from trip_state import VehicleState


@dataclass
class VehicleSnapshot:
    vehicle_label: str
    route_id: Optional[str]
    direction_id: Optional[int]
    trip_id: Optional[str]
    trip_id_is_synthesized: bool
    lat: float
    lng: float
    bearing: Optional[float]
    speed: Optional[float]
    next_stop_id: Optional[str]
    next_stop_sequence: Optional[int]
    eta_minutes: Optional[float]
    occupancy_percentage: Optional[float]
    updated_at: datetime


_snapshots: Dict[str, VehicleSnapshot] = {}
_lock = Lock()


def update(
    vehicle: vehicles.Vehicle,
    route_id: str,
    direction_id: int,
    state: VehicleState,
    current_lookups: lookups.Lookups,
    now: datetime,
) -> None:
    """Refreshes the live snapshot for this vehicle -- called every poll cycle, regardless of
    whether a stop-passage was detected this cycle, since position/bearing/speed/ETA change
    continuously. Reuses state.trip_id/trip_id_is_synthesized as resolved by event.py rather
    than re-deriving identity here.
    """
    next_stop_id = None
    next_stop_sequence = None
    if vehicle.arret_suiv_name is not None:
        next_stop_id = lookups.resolve_stop_id(
            current_lookups,
            route_id,
            direction_id,
            vehicle.arret_suiv_name,
            vehicle.lat,
            vehicle.lng,
        )
        if (
            next_stop_id is not None
            and state.trip_id is not None
            and not state.trip_id_is_synthesized
        ):
            next_stop_sequence = lookups.stop_sequence_for(
                current_lookups, state.trip_id, next_stop_id, state.stop_sequence
            )

    snapshot = VehicleSnapshot(
        vehicle_label=vehicle.numero_equipement,
        route_id=route_id,
        direction_id=direction_id,
        trip_id=state.trip_id,
        trip_id_is_synthesized=state.trip_id_is_synthesized,
        lat=vehicle.lat,
        lng=vehicle.lng,
        bearing=vehicle.bearing,
        speed=vehicle.speed,
        next_stop_id=next_stop_id,
        next_stop_sequence=next_stop_sequence,
        eta_minutes=vehicle.arret_suiv_eta_minutes,
        occupancy_percentage=vehicle.taux_remplissage,
        updated_at=now,
    )
    with _lock:
        _snapshots[vehicle.numero_equipement] = snapshot


def get_all_snapshots() -> List[VehicleSnapshot]:
    with _lock:
        return list(_snapshots.values())
