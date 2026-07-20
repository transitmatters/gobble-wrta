import time
from dataclasses import dataclass
from threading import Lock, Thread
from typing import Any, List

import pandas as pd

import swiv
from logger import set_up_logging

logger = set_up_logging(__name__)

# how often to poll /config/version to see if /topo needs re-fetching
VERSION_POLL_SECONDS = 60

current_topology = None
write_topology_lock = Lock()


def get_topology_version() -> int:
    """The vendor's change counter for /topo -- an unchanged value means /topo hasn't changed."""
    body = swiv.get_json("/config/version")
    return body["version"][0]["valeur"]


@dataclass
class Topology:
    # All stops, keyed by the vendor's own idPointArret (not a GTFS id)
    stops: pd.DataFrame
    # All routes, keyed by the vendor's own idLigne (not a GTFS id)
    routes: pd.DataFrame
    # Active service deviations/detours; schema not yet needed downstream, kept raw
    deviations: List[dict[str, Any]]
    # The /config/version value this topology was fetched at
    version: int


def fetch_topology() -> Topology:
    """Fetches the vendor's current stops/routes/deviations and shapes them into a Topology."""
    logger.info("Fetching topology")
    body = swiv.get_json("/topo")
    topo = body["topo"][0]

    return Topology(
        stops=pd.DataFrame(topo["pointArret"]),
        routes=pd.DataFrame(topo["ligne"]),
        deviations=topo["deviation"],
        version=get_topology_version(),
    )


def update_current_topology_if_necessary():
    """Compares the current topology's version to the live /config/version,
    fetching a new topology if the vendor's data has changed."""
    global current_topology
    global write_topology_lock
    with write_topology_lock:
        latest_version = get_topology_version()
        needs_update = (
            current_topology is None or current_topology.version != latest_version
        )
        if needs_update:
            if current_topology is None:
                logger.info("Missing topology, fetching")
            else:
                logger.info(
                    f"Updating topology from version {current_topology.version} to {latest_version}"
                )
            current_topology = fetch_topology()


def update_topology_thread():
    while True:
        try:
            update_current_topology_if_necessary()
        except Exception:
            logger.exception("Error updating topology; will retry next cycle")
        time.sleep(VERSION_POLL_SECONDS)


def start_watching_topology():
    topology_thread = Thread(target=update_topology_thread, name="update_topology")
    topology_thread.start()


def get_current_topology() -> Topology:
    global current_topology
    if current_topology is None:
        update_current_topology_if_necessary()

    if current_topology is None:
        raise RuntimeError("Unable to get current topology")
    return current_topology
