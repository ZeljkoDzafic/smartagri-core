"""Parcel geometry: validation, geodesic area, centroid. Coordinates are WGS84 (EPSG:4326), lon/lat order."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

EARTH_RADIUS_M = 6371008.8          # mean radius; area error against the ellipsoid stays below about 0.5 %
MIN_AREA_HA, MAX_AREA_HA = 0.05, 200.0
MAX_VERTICES = 500                   # ring positions, the closing one included (the check for crossings is quadratic)
SMALL_PARCEL_HA = 0.3


class GeometryError(ValueError):
    pass


def _ring(geometry: Dict[str, Any]) -> List[Tuple[float, float]]:
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise GeometryError("Geometrija mora biti GeoJSON poligon.")
    coords = geometry.get("coordinates") or []
    if len(coords) != 1:
        raise GeometryError("Poligon sa rupama nije podržan; ucrtajte jednu zatvorenu liniju.")
    if isinstance(coords[0], list) and len(coords[0]) > MAX_VERTICES:
        raise GeometryError("Poligon ima previše temena (najviše %d)." % MAX_VERTICES)
    try:
        ring = [(float(p[0]), float(p[1])) for p in coords[0]]
    except (TypeError, ValueError, IndexError):
        raise GeometryError("Koordinate poligona nisu ispravne.")
    if len(ring) >= 2 and ring[0] != ring[-1]:
        raise GeometryError("Poligon nije zatvoren: prva i poslednja tačka moraju biti iste.")
    if len(ring) < 4:
        raise GeometryError("Poligon mora imati najmanje tri temena.")
    for lon, lat in ring:
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            raise GeometryError("Koordinate moraju biti geografska dužina i širina (WGS84).")
    return ring


def _segments_cross(a, b, c, d) -> bool:
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (v > 0) - (v < 0)
    return orient(a, b, c) != orient(a, b, d) and orient(c, d, a) != orient(c, d, b) \
        and 0 not in (orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b))


def _self_intersects(ring: List[Tuple[float, float]]) -> bool:
    n = len(ring) - 1
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue                      # adjacent through the closing vertex
            if _segments_cross(ring[i], ring[i + 1], ring[j], ring[j + 1]):
                return True
    return False


def area_ha(geometry: Dict[str, Any]) -> float:
    """Geodesic polygon area on a sphere (Chamberlain and Duquette), in hectares."""
    ring = _ring(geometry)
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(ring, ring[1:]):
        total += math.radians(lon2 - lon1) * (2 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2)))
    return abs(total * EARTH_RADIUS_M ** 2 / 2.0) / 10000.0


def centroid(geometry: Dict[str, Any]) -> Dict[str, float]:
    """Planar centroid in degrees; adequate for parcels a few hundred metres across."""
    ring = _ring(geometry)
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if a == 0:
        raise GeometryError("Poligon nema površinu.")
    return {"lat": round(cy / (3 * a), 6), "lon": round(cx / (3 * a), 6)}


def validate(geometry: Dict[str, Any]) -> Dict[str, Any]:
    """Return area, centroid and warnings, or raise GeometryError with a message for the user."""
    ring = _ring(geometry)
    if _self_intersects(ring):
        raise GeometryError("Poligon seče sam sebe; ucrtajte granicu bez ukrštanja.")
    area = area_ha(geometry)
    if area < MIN_AREA_HA or area > MAX_AREA_HA:
        raise GeometryError("Površina parcele je %.2f ha; podržan je opseg od %.2f do %.0f ha."
                            % (area, MIN_AREA_HA, MAX_AREA_HA))
    warnings = []
    if area < SMALL_PARCEL_HA:
        warnings.append("Parcela je manja od 0,3 ha; satelitski podaci su manje pouzdani zbog malog broja piksela.")
    return {"area_ha": round(area, 3), "centroid": centroid(geometry), "warnings": warnings}


def region_class(lat: float, lon: float, elevation_m: Any = None) -> str:
    """Coarse agro-ecological class used by the applicability predicate. Placeholder rule, to be reviewed."""
    if elevation_m is not None and elevation_m >= 500:
        return "hilly_mountain"
    if lat < 43.4:
        return "mediterranean"
    return "pannonian"
