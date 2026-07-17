from dataclasses import dataclass
from datetime import date, datetime, timedelta
from threading import Lock
from typing import Dict, List, Optional, Tuple, Union, cast

import pandas as pd

import util
from gtfs import GTFS, get_current_gtfs
from logger import set_up_logging
from topology import Topology, get_current_topology

logger = set_up_logging(__name__)

current_lookups = None
write_lookups_lock = Lock()

# defining these columns in particular becasue we use them everywhere
RTE_DIR_STOP = ["route_id", "direction_id", "stop_id"]


# 51 - outbound: "Webster Harrington Hosp.", inbound: "Big Bunny Plaza Southbridge"
# 85 - outbound: "Grafton Train/ Station", inbound: "C Street New Village"
def direction_id_for_destination(route_id: str, destination: str) -> int:
    """Infers direction from a CAD/AVL vehicle's destination string.
    WRTA is mostly hub-and-spoke, save for a few lines that are
    matched manually. Returns 0 if outbound, 1 if inbound"""

    if route_id == "51":
        return 0 if destination == "Webster Harrington Hosp." else 1
    elif route_id == "83":
        return 0
    elif route_id == "85":
        return 0 if destination == "Grafton Train/ Station" else 1
    return 1 if destination == "Central Hub" else 0


def _build_stop_id_by_point_arret(topo: Topology, gtfs_data: GTFS) -> Dict[int, str]:
    """idPointArret -> GTFS stop_id, joined on stopCode/stop_code.

    A handful of topo stops have no corresponding GTFS stop_code (observed: 4 of 1229) --
    these are dropped rather than erroring, since the two sources are independently maintained.
    """
    gtfs_stops = gtfs_data.stops[gtfs_data.stops.stop_code.notna()].copy()
    gtfs_stops["stop_code"] = gtfs_stops.stop_code.astype(int).astype(str)

    topo_stops = topo.stops.copy()
    topo_stops["stopCode"] = topo_stops.stopCode.astype(str)

    merged = topo_stops.merge(
        gtfs_stops[["stop_id", "stop_code"]],
        left_on="stopCode",
        right_on="stop_code",
        how="inner",
    )

    unmatched = len(topo_stops) - len(merged)
    if unmatched:
        logger.warning(f"{unmatched} topo stops have no matching GTFS stop_code")

    return dict(zip(merged.idPointArret, merged.stop_id))


def _build_route_id_by_ligne(topo: Topology) -> Dict[int, str]:
    """idLigne -> GTFS route_id.

    WRTA's route_short_name is identical to its route_id, and topo's mnemo is identical to
    route_short_name, so mnemo IS the route_id"""
    return dict(zip(topo.routes.idLigne, topo.routes.mnemo.astype(str)))


@dataclass
class StopCandidate:
    stop_id: str
    lat: float
    lng: float


def _build_stop_by_route_direction_name(
    gtfs_data: GTFS, topo: Topology, stop_id_by_point_arret: Dict[int, str]
) -> Dict[Tuple[str, int, str], Union[str, List[StopCandidate]]]:
    """(route_id, direction_id, topo stop name) -> GTFS stop_id.

    Built from the GTFS side: for every stop a route actually serves in a given direction
    (per stop_times/trips), look up that stop's topo name via stop_id_by_point_arret (reversed).
    Usually this is a single GTFS stop_id, but a there-and-back loop can pass the same-named
    landmark twice in the *same* direction (observed: 18 of 26 route/direction groups, e.g.
    "Walmart Route 146" on route 11 outbound) -- those keys map to a list of candidates instead,
    with each candidate's coordinates so a caller can break the tie by nearest distance to the
    vehicle's live position (see resolve_stop_id).
    """
    point_arret_by_stop_id = {v: k for k, v in stop_id_by_point_arret.items()}

    topo_stops = topo.stops.copy()
    topo_stops["lat"] = topo_stops.localisation.apply(lambda loc: loc["lat"])
    topo_stops["lng"] = topo_stops.localisation.apply(lambda loc: loc["lng"])
    topo_stops = topo_stops.set_index("idPointArret")

    merged = gtfs_data.stop_times.merge(
        gtfs_data.trips[["trip_id", "route_id", "direction_id"]], on="trip_id"
    )
    pairs = merged[["route_id", "direction_id", "stop_id"]].drop_duplicates().copy()

    pairs["idPointArret"] = pairs.stop_id.map(point_arret_by_stop_id)
    unmatched = pairs.idPointArret.isna().sum()
    if unmatched:
        logger.warning(f"{unmatched} GTFS stops have no matching topo stop")
    pairs = pairs.dropna(subset=["idPointArret"])

    pairs["name"] = pairs.idPointArret.map(topo_stops.nomCommercial)
    pairs["lat"] = pairs.idPointArret.map(topo_stops.lat)
    pairs["lng"] = pairs.idPointArret.map(topo_stops.lng)

    lookup: Dict[Tuple[str, int, str], Union[str, List[StopCandidate]]] = {}
    for (route_id, direction_id, name), group in pairs.groupby(
        ["route_id", "direction_id", "name"]
    ):
        key = (str(route_id), cast(int, direction_id), str(name))
        if len(group) == 1:
            lookup[key] = group.stop_id.iloc[0]
        else:
            lookup[key] = [
                StopCandidate(
                    stop_id=str(row.stop_id),
                    lat=cast(float, row.lat),
                    lng=cast(float, row.lng),
                )
                for row in group.itertuples()
            ]

    return lookup


def _build_trip_candidates_by_route_direction_stop(
    gtfs_data: GTFS,
) -> Dict[Tuple[str, int, str], List[Tuple[pd.Timedelta, str]]]:
    """(route_id, direction_id, stop_id) -> that stop's (scheduled arrival_time, trip_id) pairs,
    sorted by arrival_time -- lets match_trip_id find the nearest-scheduled-time trip for an
    observed real-time passage without re-scanning stop_times per event.
    """
    merged = gtfs_data.stop_times.merge(
        gtfs_data.trips[["trip_id", "route_id", "direction_id"]], on="trip_id"
    )

    lookup: Dict[Tuple[str, int, str], List[Tuple[pd.Timedelta, str]]] = {}
    for (route_id, direction_id, stop_id), group in merged.groupby(
        ["route_id", "direction_id", "stop_id"]
    ):
        lookup[(str(route_id), cast(int, direction_id), str(stop_id))] = sorted(
            zip(group.arrival_time, group.trip_id)
        )

    return lookup


def match_trip_id(
    lookups: "Lookups",
    route_id: str,
    direction_id: int,
    stop_id: str,
    event_time: datetime,
    max_diff: timedelta = timedelta(minutes=20),
) -> Optional[str]:
    """Finds the GTFS trip_id whose scheduled arrival at stop_id is nearest event_time, among
    trips on (route_id, direction_id). Returns None if no trip serves that stop on that
    route/direction, or if the nearest match is further than max_diff away.

    Same nearest-scheduled-time comparison add_gtfs_headways uses internally to build its
    scheduled_trip_id map, but used here to resolve trip identity itself rather than as a
    post-hoc enrichment column.
    """
    candidates = lookups.trip_candidates_by_route_direction_stop.get(
        (route_id, direction_id, stop_id)
    )
    if not candidates:
        return None

    service_midnight = pd.Timestamp(util.service_date(event_time)).tz_localize(
        util.EASTERN_TIME
    )
    event_offset = pd.Timestamp(event_time) - service_midnight

    best_time, best_trip_id = min(
        candidates, key=lambda pair: abs(pair[0] - event_offset)
    )
    if abs(best_time - event_offset) > max_diff:
        return None

    return best_trip_id


def _build_stop_sequences_by_trip_stop(gtfs_data: GTFS) -> Dict[Tuple[str, str], List[int]]:
    """(trip_id, stop_id) -> sorted stop_sequence values at which that stop occurs on that trip.

    Usually a single value; loop routes can revisit the same stop_id more than once per trip
    (see _build_stop_by_route_direction_name), hence the list.
    """
    lookup: Dict[Tuple[str, str], List[int]] = {}
    for (trip_id, stop_id), group in gtfs_data.stop_times.groupby(["trip_id", "stop_id"]):
        lookup[(str(trip_id), str(stop_id))] = sorted(group.stop_sequence)
    return lookup


def stop_sequence_for(
    lookups: "Lookups", trip_id: str, stop_id: str, prev_sequence: int
) -> Optional[int]:
    """Resolves stop_id's position within trip_id's stop pattern. If the stop appears more than
    once on the trip (loop routes revisiting a landmark), picks the sequence greater than
    prev_sequence -- i.e. keeps moving forward -- falling back to the smallest if none is
    greater (e.g. the trip has wrapped around).
    """
    candidates = lookups.stop_sequences_by_trip_stop.get((trip_id, stop_id))
    if not candidates:
        return None

    greater = [seq for seq in candidates if seq > prev_sequence]
    return min(greater) if greater else min(candidates)


def resolve_stop_id(
    lookups: "Lookups",
    route_id: str,
    direction_id: int,
    name: str,
    vehicle_lat: float,
    vehicle_lng: float,
) -> Optional[str]:
    """Resolves a live vehicle's next-stop name to a GTFS stop_id, breaking ties between
    same-named stops by nearest distance to the vehicle's own position."""
    match = lookups.stop_by_route_direction_name.get((route_id, direction_id, name))
    if match is None:
        return None
    if isinstance(match, str):
        return match

    nearest = min(
        match, key=lambda c: (c.lat - vehicle_lat) ** 2 + (c.lng - vehicle_lng) ** 2
    )
    return nearest.stop_id


def add_gtfs_headways(
    event_df: pd.DataFrame, all_trips: pd.DataFrame, all_stops: pd.DataFrame
) -> pd.DataFrame:
    """Matches each event to its scheduled GTFS headway and travel time by nearest time-of-day,
    via pandas merge_asof. Adapted from historical bus headway calculations:
    https://github.com/transitmatters/t-performance-dash/blob/ebecaca071b39d8140296545f2e5b287915bc60d/server/bus/gtfs_archive.py#L90

    All times must be in US/Eastern.
    """
    if len(event_df) > 1:
        return batch_add_gtfs_headways(event_df, all_trips, all_stops)

    service_date = event_df.service_date.iloc[0]
    route_id = event_df.route_id.iloc[0]
    # filter out the trips of interest
    relevant_trips = all_trips[all_trips.route_id == route_id]

    # take only the stops from those trips (adding route and dir info)
    trip_info = relevant_trips[["trip_id", "route_id", "direction_id"]]
    gtfs_stops = all_stops.merge(trip_info, on="trip_id", how="right")

    # calculate gtfs headways
    gtfs_stops = gtfs_stops.sort_values(by="arrival_time")
    headways = gtfs_stops.groupby(RTE_DIR_STOP).arrival_time.diff()
    # the first stop of a trip doesnt technically have a real scheduled headway, so we set to empty string
    headways = headways.fillna("")
    gtfs_stops["scheduled_headway"] = headways.dt.seconds

    # calculate gtfs traveltimes
    trip_start_times = gtfs_stops.groupby("trip_id").arrival_time.transform("min")
    gtfs_stops["scheduled_tt"] = (gtfs_stops.arrival_time - trip_start_times).dt.seconds

    # assign each actual timepoint a scheduled headway
    # merge_asof 'backward' matches the previous scheduled value of 'arrival_time'
    event_df["arrival_time"] = event_df.event_time - pd.Timestamp(
        service_date
    ).tz_localize(util.EASTERN_TIME)
    augmented_event = pd.merge_asof(
        event_df,
        gtfs_stops[RTE_DIR_STOP + ["arrival_time", "scheduled_headway"]],
        on="arrival_time",
        direction="backward",
        by=RTE_DIR_STOP,
    )

    # exact merge, not another nearest-time match: trip_id is already the real matched GTFS
    # trip (see match_trip_id), and stop_sequence disambiguates loop routes revisiting a stop.
    # Synthesized (non-GTFS) trip_ids correctly get NaN here -- there's no real trip to match.
    scheduled_tt_keys = RTE_DIR_STOP + ["trip_id", "stop_sequence"]
    augmented_event = pd.merge(
        augmented_event,
        gtfs_stops[scheduled_tt_keys + ["scheduled_tt"]],
        how="left",
        on=scheduled_tt_keys,
    )

    return augmented_event


def batch_add_gtfs_headways(
    events_df: pd.DataFrame, trips: pd.DataFrame, stop_times: pd.DataFrame
) -> pd.DataFrame:
    """A batch implementation of add_gtfs_headways--this will probably never be used, but we include it just in case."""
    results = []

    # we have to do this day-by-day because gtfs changes so often
    for service_date, days_events in events_df.groupby("service_date"):
        # filter out the trips of interest
        relevant_trips = trips[trips.route_id.isin(days_events.route_id)]

        # take only the stops from those trips (adding route and dir info)
        trip_info = relevant_trips[["trip_id", "route_id", "direction_id"]]
        gtfs_stops = stop_times.merge(trip_info, on="trip_id", how="right")

        # calculate gtfs headways
        gtfs_stops = gtfs_stops.sort_values(by="arrival_time")
        headways = gtfs_stops.groupby(RTE_DIR_STOP).arrival_time.diff()
        # the first stop of a trip doesnt technically have a real scheduled headway, so we set to empty string
        headways = headways.fillna("")
        gtfs_stops["scheduled_headway"] = headways.dt.seconds

        # calculate gtfs traveltimes
        trip_start_times = gtfs_stops.groupby("trip_id").arrival_time.transform("min")
        gtfs_stops["scheduled_tt"] = (
            gtfs_stops.arrival_time - trip_start_times
        ).dt.seconds

        # assign each actual timepoint a scheduled headway
        # merge_asof 'backward' matches the previous scheduled value of 'arrival_time'
        days_events["arrival_time"] = days_events.event_time - pd.Timestamp(
            str(service_date)
        ).tz_localize(util.EASTERN_TIME)
        augmented_events = pd.merge_asof(
            days_events.sort_values(by="arrival_time"),
            gtfs_stops[RTE_DIR_STOP + ["arrival_time", "scheduled_headway"]],
            on="arrival_time",
            direction="backward",
            by=RTE_DIR_STOP,
        )

        # exact merge, not another nearest-time match: trip_id is already the real matched GTFS
        # trip (see match_trip_id), and stop_sequence disambiguates loop routes revisiting a stop.
        # Synthesized (non-GTFS) trip_ids correctly get NaN here -- there's no real trip to match.
        scheduled_tt_keys = RTE_DIR_STOP + ["trip_id", "stop_sequence"]
        augmented_events = pd.merge(
            augmented_events,
            gtfs_stops[scheduled_tt_keys + ["scheduled_tt"]],
            how="left",
            on=scheduled_tt_keys,
        )

        # finally, put all the days together
        results.append(augmented_events)

    return pd.concat(results)


@dataclass
class Lookups:
    stop_id_by_point_arret: Dict[int, str]
    route_id_by_ligne: Dict[int, str]
    stop_by_route_direction_name: Dict[
        Tuple[str, int, str], Union[str, List[StopCandidate]]
    ]
    trip_candidates_by_route_direction_stop: Dict[
        Tuple[str, int, str], List[Tuple[pd.Timedelta, str]]
    ]
    stop_sequences_by_trip_stop: Dict[Tuple[str, str], List[int]]

    # identity of the sources this was built from, so we know when to rebuild
    gtfs_service_date: date
    topology_version: int


def _build_lookups(gtfs_data: GTFS, topo: Topology) -> Lookups:
    logger.info("Building lookups")
    stop_id_by_point_arret = _build_stop_id_by_point_arret(topo, gtfs_data)
    return Lookups(
        stop_id_by_point_arret=stop_id_by_point_arret,
        route_id_by_ligne=_build_route_id_by_ligne(topo),
        stop_by_route_direction_name=_build_stop_by_route_direction_name(
            gtfs_data, topo, stop_id_by_point_arret
        ),
        trip_candidates_by_route_direction_stop=_build_trip_candidates_by_route_direction_stop(
            gtfs_data
        ),
        stop_sequences_by_trip_stop=_build_stop_sequences_by_trip_stop(gtfs_data),
        gtfs_service_date=gtfs_data.service_date,
        topology_version=topo.version,
    )


def get_current_lookups() -> Lookups:
    """Returns the current lookups, rebuilding them if either the underlying GTFS or
    topology has changed since they were last computed."""
    global current_lookups
    global write_lookups_lock
    with write_lookups_lock:
        gtfs_data = get_current_gtfs()
        topo = get_current_topology()
        needs_update = (
            current_lookups is None
            or current_lookups.gtfs_service_date != gtfs_data.service_date
            or current_lookups.topology_version != topo.version
        )
        if needs_update:
            current_lookups = _build_lookups(gtfs_data, topo)

    if current_lookups is None:
        raise RuntimeError("Unable to get current lookups")
    return current_lookups
