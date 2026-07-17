from datetime import datetime

import pandas as pd

import disk
import gtfs
import lookups
import trip_state
import util
import vehicle_snapshot
import vehicles
from logger import set_up_logging
from trip_state import VehicleState

logger = set_up_logging(__name__)


def process_vehicle_update(
    vehicle: vehicles.Vehicle,
    current_lookups: lookups.Lookups,
    gtfs_data: gtfs.GTFS,
) -> None:
    """Advances one vehicle's tracked trip state by a single poll's worth of new data: detects
    whether it has passed its previously-seen next stop, emits an ARR/DEP event pair if so, and
    refreshes its live snapshot for the GTFS-RT feed either way."""
    route_id = current_lookups.route_id_by_ligne.get(vehicle.id_ligne)
    if route_id is None:
        return
    direction_id = lookups.direction_id_for_destination(route_id, vehicle.destination)

    now = datetime.now(util.EASTERN_TIME)
    state = trip_state.get_state(vehicle.numero_equipement)

    if (
        state is None
        or state.route_id != route_id
        or state.direction_id != direction_id
        or util.service_date(state.updated_at) != util.service_date(now)
    ):
        state = VehicleState(
            trip_id=None,
            trip_id_is_synthesized=False,
            route_id=route_id,
            direction_id=direction_id,
            stop_sequence=0,
            prev_stop_name=None,
            updated_at=now,
        )

    current_name = vehicle.arret_suiv_name
    if (
        state.prev_stop_name is not None
        and current_name is not None
        and state.prev_stop_name != current_name
    ):
        stop_id = lookups.resolve_stop_id(
            current_lookups,
            route_id,
            direction_id,
            state.prev_stop_name,
            vehicle.lat,
            vehicle.lng,
        )
        if stop_id is not None:
            _emit_event(
                current_lookups, gtfs_data, state, route_id, direction_id, stop_id, vehicle, now
            )

    if current_name is not None:
        state.prev_stop_name = current_name
    state.updated_at = now
    trip_state.set_state(vehicle.numero_equipement, state)

    vehicle_snapshot.update(vehicle, route_id, direction_id, state, current_lookups, now)


def _synthesize_trip_id(
    vehicle: vehicles.Vehicle, route_id: str, direction_id: int, event_time: datetime
) -> str:
    return (
        f"{vehicle.numero_equipement}-{route_id}-{direction_id}-"
        f"{event_time:%Y%m%dT%H%M%S}"
    )


def _emit_event(
    current_lookups: lookups.Lookups,
    gtfs_data: gtfs.GTFS,
    state: VehicleState,
    route_id: str,
    direction_id: int,
    stop_id: str,
    vehicle: vehicles.Vehicle,
    event_time: datetime,
) -> None:
    if state.trip_id is None:
        matched_trip_id = lookups.match_trip_id(
            current_lookups, route_id, direction_id, stop_id, event_time
        )
        if matched_trip_id is not None:
            state.trip_id = matched_trip_id
            state.trip_id_is_synthesized = False
        else:
            state.trip_id = _synthesize_trip_id(vehicle, route_id, direction_id, event_time)
            state.trip_id_is_synthesized = True
            logger.warning(
                f"No GTFS trip match for vehicle={vehicle.numero_equipement} "
                f"route={route_id} direction={direction_id} stop={stop_id}; "
                f"using synthesized trip_id={state.trip_id}"
            )

    if state.trip_id_is_synthesized:
        state.stop_sequence += 1
    else:
        resolved_sequence = lookups.stop_sequence_for(
            current_lookups, state.trip_id, stop_id, state.stop_sequence
        )
        state.stop_sequence = (
            resolved_sequence if resolved_sequence is not None else state.stop_sequence + 1
        )

    base_row = {
        "service_date": util.service_date_iso8601(event_time),
        "route_id": route_id,
        "trip_id": state.trip_id,
        "direction_id": direction_id,
        "stop_id": stop_id,
        "stop_sequence": state.stop_sequence,
        "vehicle_id": "0",
        "vehicle_label": vehicle.numero_equipement,
        "event_time": event_time,
        "vehicle_consist": vehicle.numero_equipement,
        "occupancy_status": None,
        "occupancy_percentage": vehicle.taux_remplissage,
    }
    event_df = pd.DataFrame(
        [
            {**base_row, "event_type": "ARR"},
            {**base_row, "event_type": "DEP"},
        ]
    )

    enriched = lookups.add_gtfs_headways(event_df, gtfs_data.trips, gtfs_data.stop_times)
    disk.write_events(enriched)

    logger.info(
        f"{event_time.isoformat()} ARR/DEP vehicle={vehicle.numero_equipement} "
        f"route={route_id} direction={direction_id} stop={stop_id} "
        f"trip_id={state.trip_id!r} stop_sequence={state.stop_sequence}"
    )
