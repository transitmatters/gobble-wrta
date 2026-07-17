from datetime import timedelta
from typing import List

from google.transit import gtfs_realtime_pb2 as gtfs_rt

from vehicle_snapshot import VehicleSnapshot

GTFS_RT_VERSION = "2.0"


def _feed_header(timestamp: int) -> gtfs_rt.FeedHeader:
    header = gtfs_rt.FeedHeader()
    header.gtfs_realtime_version = GTFS_RT_VERSION
    header.incrementality = gtfs_rt.FeedHeader.FULL_DATASET
    header.timestamp = timestamp
    return header


def build_vehicle_positions(snapshots: List[VehicleSnapshot]) -> gtfs_rt.FeedMessage:
    """One VehiclePosition entity per tracked vehicle, regardless of whether it has a resolved
    trip yet -- position data is still valid on its own. current_status is always IN_TRANSIT_TO
    since WRTA gives no discrete stopped/moving signal."""
    feed = gtfs_rt.FeedMessage()
    if not snapshots:
        feed.header.CopyFrom(_feed_header(0))
        return feed

    latest = max(int(s.updated_at.timestamp()) for s in snapshots)
    feed.header.CopyFrom(_feed_header(latest))

    for snapshot in snapshots:
        entity = feed.entity.add()
        entity.id = snapshot.vehicle_label

        vp = entity.vehicle
        vp.vehicle.id = snapshot.vehicle_label
        vp.vehicle.label = snapshot.vehicle_label
        vp.position.latitude = snapshot.lat
        vp.position.longitude = snapshot.lng
        if snapshot.bearing is not None:
            vp.position.bearing = snapshot.bearing
        if snapshot.speed is not None:
            vp.position.speed = snapshot.speed
        vp.current_status = gtfs_rt.VehiclePosition.IN_TRANSIT_TO
        vp.timestamp = int(snapshot.updated_at.timestamp())
        if snapshot.occupancy_percentage is not None:
            vp.occupancy_percentage = int(snapshot.occupancy_percentage)

        if snapshot.trip_id is not None and not snapshot.trip_id_is_synthesized:
            vp.trip.trip_id = snapshot.trip_id
            if snapshot.route_id is not None:
                vp.trip.route_id = snapshot.route_id
            if snapshot.direction_id is not None:
                vp.trip.direction_id = snapshot.direction_id
        if snapshot.next_stop_id is not None:
            vp.stop_id = snapshot.next_stop_id
        if snapshot.next_stop_sequence is not None:
            vp.current_stop_sequence = snapshot.next_stop_sequence

    return feed


def build_trip_updates(snapshots: List[VehicleSnapshot]) -> gtfs_rt.FeedMessage:
    """One TripUpdate entity per vehicle with a real (non-synthesized) matched GTFS trip --
    synthesized trip_ids don't correspond to a static-GTFS trip, so publishing a TripUpdate
    against one would mislead consumers trying to join against GTFS. Each TripUpdate carries a
    single StopTimeUpdate for the immediate next stop only (from arretSuiv.estimationTemps) --
    full remaining-trip predictions are deferred."""
    feed = gtfs_rt.FeedMessage()
    if not snapshots:
        feed.header.CopyFrom(_feed_header(0))
        return feed

    latest = max(int(s.updated_at.timestamp()) for s in snapshots)
    feed.header.CopyFrom(_feed_header(latest))

    for snapshot in snapshots:
        if snapshot.trip_id is None or snapshot.trip_id_is_synthesized:
            continue
        if (
            snapshot.next_stop_id is None
            or snapshot.next_stop_sequence is None
            or snapshot.eta_minutes is None
        ):
            continue

        entity = feed.entity.add()
        entity.id = snapshot.trip_id

        tu = entity.trip_update
        tu.trip.trip_id = snapshot.trip_id
        if snapshot.route_id is not None:
            tu.trip.route_id = snapshot.route_id
        if snapshot.direction_id is not None:
            tu.trip.direction_id = snapshot.direction_id
        tu.vehicle.id = snapshot.vehicle_label
        tu.vehicle.label = snapshot.vehicle_label
        tu.timestamp = int(snapshot.updated_at.timestamp())

        stop_time_update = tu.stop_time_update.add()
        stop_time_update.stop_id = snapshot.next_stop_id
        stop_time_update.stop_sequence = snapshot.next_stop_sequence
        predicted_arrival = snapshot.updated_at + timedelta(minutes=snapshot.eta_minutes)
        stop_time_update.arrival.time = int(predicted_arrival.timestamp())

    return feed
