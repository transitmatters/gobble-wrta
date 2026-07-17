import time

import event
import gtfs
import lookups
import trip_state
import vehicles
from logger import set_up_logging

logger = set_up_logging(__name__)

POLL_SECONDS = 5


def poll_vehicles_forever():
    """The main loop: repeatedly fetches live vehicle positions and processes each one against
    the current GTFS/lookups state, then clears out vehicle states that have gone stale."""
    while True:
        current_lookups = lookups.get_current_lookups()
        gtfs_data = gtfs.get_current_gtfs()

        for vehicle in vehicles.fetch_vehicles():
            event.process_vehicle_update(vehicle, current_lookups, gtfs_data)

        trip_state.cleanup_stale_states()

        time.sleep(POLL_SECONDS)
