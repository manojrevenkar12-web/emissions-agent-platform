"""Public reference data: locations by UN/LOCODE-style code with what they can handle.

Both the world and the platform may read this module: it is what anyone could look up, not hidden truth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Location:
    code: str
    name: str
    lat: float
    lon: float
    port: bool = False
    airport: bool = False
    rail: bool = False
    waterway: bool = False


_RAW: list[tuple[str, str, float, float, str]] = [
    # code, name, lat, lon, flags (p=port, a=airport, r=rail terminal, w=inland waterway)
    ("DEHAM", "Hamburg", 53.55, 9.99, "parw"),
    ("DEBRV", "Bremerhaven", 53.54, 8.58, "pr"),
    ("DEBER", "Berlin", 52.52, 13.40, "arw"),
    ("DEMUC", "Munich", 48.14, 11.58, "ar"),
    ("DEFRA", "Frankfurt", 50.11, 8.68, "arw"),
    ("DEDUS", "Düsseldorf", 51.23, 6.78, "arw"),
    ("DEDUI", "Duisburg", 51.43, 6.76, "rw"),
    ("DECGN", "Cologne", 50.94, 6.96, "arw"),
    ("DESTR", "Stuttgart", 48.78, 9.18, "ar"),
    ("DENUE", "Nuremberg", 49.45, 11.08, "arw"),
    ("DELEJ", "Leipzig", 51.34, 12.37, "ar"),
    ("DEHAJ", "Hanover", 52.37, 9.73, "ar"),
    ("DEMHG", "Mannheim", 49.49, 8.47, "rw"),
    ("DEKSF", "Kassel", 51.31, 9.48, ""),
    ("DEBIE", "Bielefeld", 52.02, 8.53, ""),
    ("DEERF", "Erfurt", 50.98, 11.03, "r"),
    ("NLRTM", "Rotterdam", 51.92, 4.48, "prw"),
    ("NLAMS", "Amsterdam", 52.37, 4.90, "parw"),
    ("NLVEN", "Venlo", 51.37, 6.17, "r"),
    ("BEANR", "Antwerp", 51.22, 4.40, "prw"),
    ("BEBRU", "Brussels", 50.85, 4.35, "ar"),
    ("FRPAR", "Paris", 48.86, 2.35, "arw"),
    ("FRLYS", "Lyon", 45.76, 4.84, "arw"),
    ("FRLEH", "Le Havre", 49.49, 0.11, "prw"),
    ("FRMRS", "Marseille", 43.30, 5.37, "par"),
    ("FRSXB", "Strasbourg", 48.57, 7.75, "rw"),
    ("ITMIL", "Milan", 45.46, 9.19, "ar"),
    ("ITGOA", "Genoa", 44.41, 8.93, "pr"),
    ("ITVRN", "Verona", 45.44, 10.99, "r"),
    ("ESMAD", "Madrid", 40.42, -3.70, "ar"),
    ("ESBCN", "Barcelona", 41.39, 2.17, "par"),
    ("ESVLC", "Valencia", 39.47, -0.38, "pr"),
    ("PLWAW", "Warsaw", 52.23, 21.01, "ar"),
    ("PLPOZ", "Poznań", 52.41, 16.93, "r"),
    ("PLGDN", "Gdańsk", 54.35, 18.65, "par"),
    ("CZPRG", "Prague", 50.08, 14.44, "ar"),
    ("ATVIE", "Vienna", 48.21, 16.37, "arw"),
    ("ATLNZ", "Linz", 48.31, 14.29, "rw"),
    ("CHBSL", "Basel", 47.56, 7.59, "arw"),
    ("CHZRH", "Zurich", 47.38, 8.54, "ar"),
    ("DKAAR", "Aarhus", 56.16, 10.20, "pr"),
    ("DKCPH", "Copenhagen", 55.68, 12.57, "par"),
    ("SEGOT", "Gothenburg", 57.71, 11.97, "par"),
    ("HUBUD", "Budapest", 47.50, 19.04, "arw"),
    ("GBFXT", "Felixstowe", 51.96, 1.35, "p"),
    ("CNSHA", "Shanghai", 31.23, 121.47, "pa"),
    ("SGSIN", "Singapore", 1.35, 103.82, "pa"),
    ("USNYC", "New York", 40.71, -74.01, "pa"),
    ("INNSA", "Nhava Sheva", 18.95, 72.95, "p"),
    ("AEDXB", "Dubai", 25.20, 55.27, "pa"),
    ("USORD", "Chicago", 41.88, -87.63, "a"),
    ("CNPVG", "Shanghai Pudong", 31.14, 121.81, "a"),
]

LOCATIONS: dict[str, Location] = {code: Location(code, name, lat, lon, "p" in f, "a" in f, "r" in f, "w" in f) for code, name, lat, lon, f in _RAW}
EUROPE = [c for c, loc in LOCATIONS.items() if -11 < loc.lon < 25 and loc.lat > 35]


def great_circle_km(a: Location, b: Location) -> float:
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


_GCD: dict[tuple[str, str], float] = {}


def gcd_km(a: str, b: str) -> float:
    key = (a, b)
    if key not in _GCD:
        la, lb = LOCATIONS.get(a), LOCATIONS.get(b)
        _GCD[key] = great_circle_km(la, lb) if la and lb else float("nan")
    return _GCD[key]


def gcd_array(origins: np.ndarray, dests: np.ndarray) -> np.ndarray:
    return np.array([gcd_km(str(o), str(d)) for o, d in zip(origins, dests, strict=True)], dtype=float)


def handles(code: str, mode: str) -> bool:
    loc = LOCATIONS.get(code)
    if loc is None:
        return False
    if mode == "sea":
        return loc.port
    if mode == "air":
        return loc.airport
    if mode == "rail":
        return loc.rail
    if mode == "inland_waterway":
        return loc.waterway
    return code in EUROPE
