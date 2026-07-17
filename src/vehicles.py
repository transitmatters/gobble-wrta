from dataclasses import dataclass
from typing import List, Optional

import swiv


@dataclass
class Vehicle:
    id: int
    id_ligne: int
    destination: str
    # name of the next stop the vehicle is heading to, or None (e.g. off-route/end of trip)
    arret_suiv_name: Optional[str]
    # minutes until arrival at arret_suiv_name, or None if arret_suiv_name is None
    arret_suiv_eta_minutes: Optional[float]
    lat: float
    lng: float
    # compass heading in degrees, or None if unavailable
    bearing: Optional[float]
    # speed in km/h, or None if unavailable
    speed: Optional[float]
    numero_equipement: str
    # rider load as a percent of capacity, or None if unavailable
    taux_remplissage: Optional[float]


def fetch_vehicles() -> List[Vehicle]:
    body = swiv.get_json("/topo/vehicules")

    vehicles = []
    for v in body["vehicule"]:
        conduite = v["conduite"]
        arret_suiv = conduite.get("arretSuiv")
        vehicles.append(
            Vehicle(
                id=v["id"],
                id_ligne=conduite["idLigne"],
                destination=conduite["destination"],
                arret_suiv_name=arret_suiv["nomCommercial"] if arret_suiv else None,
                arret_suiv_eta_minutes=arret_suiv["estimationTemps"] if arret_suiv else None,
                lat=v["localisation"]["lat"],
                lng=v["localisation"]["lng"],
                bearing=v["localisation"].get("cap"),
                speed=conduite.get("vitesse"),
                numero_equipement=v["numeroEquipement"],
                taux_remplissage=v.get("tauxRemplissage"),
            )
        )
    return vehicles
