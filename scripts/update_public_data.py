#!/usr/bin/env python3
"""Actualiza datos públicos que pueden obtenerse sin credenciales.

Fuentes:
- Aragón Hoy: último parte oficial, estado, superficie, evacuaciones,
  carreteras y cronología.
- AEMET: predicción horaria municipal, observación de Bailo-Puyalto y
  precipitación diaria de Bailo-Puyalto y Jaca.
- ICEARAGON: perímetro oficial, únicamente cuando exista un registro de 2026
  cuyo nombre contenga "Riglos".
- CartoCiudad/IGN: puntos kilométricos oficiales cuando no están disponibles
  en el servicio autonómico de ICEARAGON.
- EFFIS/Copernicus: área quemada satelital, separada del perímetro operativo.

El script no fabrica valores ni geometrías: conserva separadas las capas oficiales
y las estimaciones satelitales publicadas por sus proveedores.
"""

from __future__ import annotations

import csv
import heapq
import io
import json
import math
import os
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TZ = ZoneInfo("Europe/Madrid")
MUNICIPALITY_ID = "22173"
STATIONS = (
    {
        "idema": "9211F",
        "nombre": "Bailo, Puyalto",
        "altitud_m": 722,
        "coordenadas": [42.5141666667, -0.8172222222],
    },
    {
        "idema": "9201X",
        "nombre": "Jaca",
        "altitud_m": 832,
        "coordenadas": [42.5797222222, -0.545],
    },
)
STATION = STATIONS[0]
# Coordenadas de referencia de núcleos y establecimientos públicos. Se fijan
# aquí para que las actualizaciones automáticas no eliminen los marcadores.
# Formato Leaflet: [latitud, longitud]. Localización contrastada con
# OpenStreetMap/Nominatim; no representa domicilios ni posiciones operativas.
EVACUATION_COORDINATES = {
    "Villalangua": [42.4190976, -0.8026854],
    "Salinas de Jaca": [42.4124840, -0.7890940],
    "Ena": [42.4471445, -0.6928043],
    "Centenero": [42.4257012, -0.6679114],
    "Santa María de la Peña": [42.3933908, -0.7426006],
    "Triste": [42.3866520, -0.7184828],
    "La Peña Estación": [42.3813638, -0.6961110],
    "Yeste": [42.3862128, -0.6913218],
    "Bailo": [42.5095870, -0.8117949],
    "Larués": [42.5166028, -0.8483146],
    "Arbués": [42.5071151, -0.7840507],
    "Alastuey": [42.5208359, -0.7602318],
    "Botaya": [42.4932554, -0.6522858],
    "Osia": [42.4522522, -0.6362717],
    "Santa Cruz de la Serós": [42.5239494, -0.6741522],
    "Binacua": [42.5470272, -0.6983497],
    "Atarés": [42.5323732, -0.6242681],
    "Anzánigo": [42.4032036, -0.6430785],
    "Bernués": [42.4781362, -0.5859853],
    "Camping Pirineos": [42.5563413, -0.7557998],
    "Campamento de Anzánigo": [42.4070208, -0.6468327],
    "Camping Anzánigo": [42.4070208, -0.6468327],
}

# Punto orientativo situado en el entorno del tramo indicado en el parte. No
# pretende sustituir una geometría lineal ni la información de tráfico de DGT.
ROAD_REFERENCE_COORDINATES = {
    "A-1205": [42.4258022, -0.6269305],
    "A-132": [42.3981902, -0.7550811],
    "N-240": [42.5577012, -0.7123532],
    "A-1603": [42.4900, -0.6600],
    "A-2602": [42.5170978, -0.8478855],
    "HU-V-3001": [42.3712182, -0.6309061],
    "HU-V-3003": [42.4079018, -0.5279721],
    "HF-0262-BA": [42.5275, -0.6305],
}
DGT_ROAD_ALIASES = {"HF-0262-BA": "HF0262BA"}
DGT_ROAD_LOCATIONS = {
    "A-1205": "Jaca – Santa María",
    "A-1603": "Bernués – Botaya",
    "A-2602": "Bailo",
    "HF-0262-BA": "Áscara – Atarés",
    "HU-V-3001": "Yeste – Rasal",
    "HU-V-3003": "Javierrelatre – Osia",
    "N-240": "Abay – Puente la Reina de Jaca",
    "A-132": "Murillo de Gállego – Puente la Reina de Jaca",
}
INCIDENT_BBOX = (-1.15, 42.10, -0.25, 42.72)
INCIDENT_START = "2026-08-09"
EFFIS_WFS = "https://maps.effis.emergency.copernicus.eu/effis"
DGT_FIRE_ROADS_PDF = "https://www.dgt.es/estaticos/movilidad/CarreterasCortadasIncendios.pdf?origen=app"
ICEARAGON_PK_ARCGIS = "https://idearagon.aragon.es/servicios/rest/services/CARRETERAS/PK_ARAGON/MapServer/0/query"
ICEARAGON_ROADS_WFS = "https://idearagon.aragon.es/Visor2D"
ICEARAGON_PK_INFO = "https://idearagon.aragon.es/servicios/rest/services/CARRETERAS/PK_ARAGON/MapServer"
ICEARAGON_ROADS_INFO = "https://opendata.aragon.es/ckan/dataset/carreteras"
CARTOCIUDAD_GEOCODER = "https://www.cartociudad.es/geocoder/api/geocoder/candidates"
CARTOCIUDAD_INFO = "https://www.cartociudad.es/web/portal/directorio-de-servicios/geoprocesamiento"
ARAGON_HOY = "https://www.aragonhoy.es"
ARAGON_HOY_PAGES = (
    f"{ARAGON_HOY}/",
    f"{ARAGON_HOY}/hacienda-interior-administracion-publica",
)
CONSOLIDATED_HISTORY = (
    {
        "fecha": "2026-08-12T10:39:19+02:00",
        "value": 50,
        "fiabilidad": "oficial",
        "nombre": "Gobierno de Aragón / Aragón Hoy",
        "url": (
            "https://www.aragonhoy.es/hacienda-interior-administracion-publica/"
            "operativo-logra-perimetrar-50-incendio-penas-riglos-106081"
        ),
        "patron": r"(?:perimetrar\s+el\s+50|mitad\s+del\s+perimetro)",
    },
)
PERIMETER_LENGTH_HISTORY = (
    {
        "fecha": "2026-08-12T10:39:19+02:00",
        "value": 41.9,
        "fiabilidad": "oficial",
        "nombre": "Gobierno de Aragón / Aragón Hoy",
        "url": (
            "https://www.aragonhoy.es/hacienda-interior-administracion-publica/"
            "operativo-logra-perimetrar-50-incendio-penas-riglos-106081"
        ),
        "patron": r"perimetro\s+de\s+41[,.]9\s+kilometros",
    },
    {
        "fecha": "2026-08-14T20:59:00+02:00",
        "value": 58,
        "fiabilidad": "oficial",
        "nombre": "Gobierno de Aragón / Aragón Hoy",
        "url": (
            "https://www.aragonhoy.es/hacienda-interior-administracion-publica/"
            "aragon-mantiene-activo-operativo-600-efectivos-luchar-incendio-penas-riglos-106107"
        ),
        "patron": r"perimetro\s+de\s+58\s+kilometros",
    },
)
SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def fetch_bytes(url: str, attempts: int = 2, user_agent: str = "incendio-riglos-panel/1.0") -> bytes:
    last_error = None
    for attempt in range(attempts):
        request = Request(url, headers={"User-Agent": user_agent})
        try:
            with urlopen(request, timeout=20) as response:
                return response.read()
        except Exception as error:  # La fuente externa puede fallar temporalmente.
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2)
    raise RuntimeError(f"No se pudo consultar {url}: {last_error}") from last_error


def decode_xml(payload: bytes) -> str:
    declaration = payload[:160].decode("ascii", errors="ignore")
    match = re.search(r"encoding=['\"]([^'\"]+)", declaration, re.I)
    encoding = match.group(1) if match else "utf-8"
    return payload.decode(encoding)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def clean_html(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return " ".join(unescape(text).split())


def spanish_integer(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def first_integer(text: str, patterns: tuple[str, ...]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return spanish_integer(match.group(1))
    return None


def first_decimal(text: str, patterns: tuple[str, ...]) -> float | int | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = match.group(1).strip()
            value = value.replace(".", "").replace(",", ".") if "," in value else value
            try:
                parsed = float(value)
                return int(parsed) if parsed.is_integer() else parsed
            except ValueError:
                continue
    return None


def official_meta(published_at: str, url: str, *, reliability: str = "oficial") -> dict:
    return {
        "fecha_hora": published_at,
        "fiabilidad": reliability,
        "fuente": {"nombre": "Gobierno de Aragón / Aragón Hoy", "url": url},
    }


def find_latest_official_article() -> dict:
    links = set()
    errors = []
    try:
        sources = read_json(DATA / "fuentes.json")
        previous = next(
            (item.get("url") for item in sources.get("fuentes", []) if item.get("id") == "aragon-hoy-ultimo-parte"),
            None,
        )
        if previous:
            links.add(previous.rstrip("/"))
    except Exception as error:
        errors.append(f"fuente anterior: {error}")
    for page_url in ARAGON_HOY_PAGES:
        try:
            page = fetch_bytes(page_url).decode("utf-8")
        except Exception as error:
            errors.append(str(error))
            continue
        for href in re.findall(r'href=["\']([^"\']+)["\']', page, re.I):
            url = urljoin(ARAGON_HOY, unescape(href))
            normalized = normalize_text(url)
            if (
                "/hacienda-interior-administracion-publica/" in url
                and ("incendio" in normalized or "extincion" in normalized)
                and "riglos" in normalized
                and re.search(r"-\d{5,}/?$", url)
            ):
                links.add(url.rstrip("/"))
    if not links:
        raise RuntimeError("No se localizaron partes de Riglos en Aragón Hoy: " + "; ".join(errors))

    articles = []
    for url in sorted(links, key=lambda item: int(item.rsplit("-", 1)[-1]), reverse=True)[:20]:
        try:
            raw = fetch_bytes(url).decode("utf-8")
            published_match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', raw)
            title_match = re.search(r'"headline"\s*:\s*"([^"]+)"', raw)
            paragraphs = [clean_html(item) for item in re.findall(
                r'<p\b[^>]*class=["\'][^"\']*\bparagraph\b[^"\']*["\'][^>]*>(.*?)</p>',
                raw,
                re.I | re.S,
            )]
            captions = [clean_html(item) for item in re.findall(
                r'<figcaption\b[^>]*>(.*?)</figcaption>',
                raw,
                re.I | re.S,
            )]
            body = " ".join(item for item in paragraphs if item)
            if not published_match or "penas de riglos" not in normalize_text(body):
                continue
            published_at = datetime.fromisoformat(published_match.group(1)).astimezone(TZ).isoformat()
            if published_at[:10] < INCIDENT_START:
                continue
            articles.append({
                "url": url,
                "title": clean_html(title_match.group(1)) if title_match else "Parte oficial de Aragón Hoy",
                "published_at": published_at,
                "paragraphs": paragraphs,
                "body": body,
                "normalized": normalize_text(body),
                # Aragón Hoy identifica algunas reuniones del CECOPI únicamente
                # en el pie de la fotografía principal, no en los párrafos.
                "mentions_cecopi": bool(re.search(
                    r"\bcecopi\b",
                    normalize_text(" ".join((body, *captions))),
                )),
            })
        except Exception as error:
            errors.append(f"{url}: {error}")
    if not articles:
        raise RuntimeError("No se pudo leer un parte oficial verificable: " + "; ".join(errors))
    latest = max(articles, key=lambda item: item["published_at"])
    cecopi_articles = [item for item in articles if item["mentions_cecopi"]]
    if not cecopi_articles:
        raise RuntimeError("No se localizó un informe oficial que mencione expresamente al CECOPI")
    cecopi = max(cecopi_articles, key=lambda item: item["published_at"])
    latest["ultimo_informe_cecopi"] = {
        "titulo": cecopi["title"],
        "fecha_hora": cecopi["published_at"],
        "url": cecopi["url"],
        "fuente": "Gobierno de Aragón / Aragón Hoy",
    }
    return latest


def explicit_fire_status(normalized: str) -> str | None:
    checks = (
        ("Extinguido", r"incendio.{0,80}(?:queda|se da por|esta) extinguido"),
        ("Controlado", r"incendio.{0,80}(?:queda|se da por|esta) controlado"),
        ("Estabilizado", r"incendio.{0,80}(?:queda|se da por|esta) estabilizado"),
        ("Activo", r"incendio.{0,80}(?:permanece|continua|sigue) activo"),
    )
    return next((label for label, pattern in checks if re.search(pattern, normalized)), None)


def parse_closed_roads(article: dict) -> list[dict] | None:
    road_pattern = re.compile(r"\b(?:[A-Z]{1,3}(?:-[A-Z])?-\d+(?:-[A-Z]{2})?|N-\d+)\b", re.I)
    paragraph = next((
        item for item in article["paragraphs"]
        if "cortad" in normalize_text(item) and len(road_pattern.findall(item)) >= 3
    ), None)
    if not paragraph:
        return None
    sentence = paragraph.split(".", 1)[0]
    source = {"nombre": "Gobierno de Aragón / CECOPI", "url": article["url"]}
    records = []
    for item in re.split(r";", sentence):
        match = road_pattern.search(item)
        if not match:
            continue
        road = match.group(0).upper()
        section = item[match.end():].strip(" ,.;")
        section = re.sub(r"\s+(?:y\s+)?(?:la\s+)?(?:carretera\s+local\s+)?$", "", section, flags=re.I).strip(" ,.;")
        record = {
            "carretera": road,
            "tramo": section or "Tramo indicado en el parte oficial",
            "estado": "Cortada",
            "fecha_hora": article["published_at"],
            "fuente": source,
        }
        if road in ROAD_REFERENCE_COORDINATES:
            record["coordenadas"] = ROAD_REFERENCE_COORDINATES[road]
            record["ubicacion_aproximada"] = True
        records.append(record)
    unique = {item["carretera"]: item for item in records}
    return list(unique.values()) if 3 <= len(unique) <= 30 else None


def format_pk(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value).replace(".", ",")


def geographic_distance_m(first: tuple[float, float], second: tuple[float, float]) -> float:
    """Distancia aproximada entre dos coordenadas GeoJSON (longitud, latitud)."""
    lon1, lat1 = map(math.radians, first)
    lon2, lat2 = map(math.radians, second)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def fetch_icearagon_pk(road: str) -> list[dict]:
    params = {
        "where": f"CODIGO_VIA='{road}'",
        "outFields": "CODIGO_VIA,PK",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    data = json.loads(fetch_bytes(f"{ICEARAGON_PK_ARCGIS}?{urlencode(params)}"))
    return sorted(
        (
            {
                "pk": float(feature["properties"]["PK"]),
                "coordenadas": tuple(map(float, feature["geometry"]["coordinates"][:2])),
            }
            for feature in data.get("features", [])
            if feature.get("geometry", {}).get("type") == "Point"
            and feature.get("properties", {}).get("PK") is not None
        ),
        key=lambda item: item["pk"],
    )


def fetch_cartociudad_pk(road: str, targets: tuple[float, float]) -> list[dict]:
    """Obtiene hitos oficiales del IGN próximos a los PK publicados por DGT."""
    requested = {
        candidate
        for target in targets
        for candidate in (math.floor(float(target)), math.ceil(float(target)))
    }
    normalized_road = re.sub(r"[^A-Z0-9]", "", road.upper())
    markers: dict[float, dict] = {}
    for pk in sorted(requested):
        params = {"q": f"{road} {pk}", "limit": "20"}
        candidates = json.loads(fetch_bytes(f"{CARTOCIUDAD_GEOCODER}?{urlencode(params)}"))
        for item in candidates:
            address = str(item.get("address") or "")
            address_road = address.split(" km ", 1)[0]
            if (
                item.get("provinceCode") != "22"
                or item.get("type") != "portal"
                or re.sub(r"[^A-Z0-9]", "", address_road.upper()) != normalized_road
                or item.get("portalNumber") is None
            ):
                continue
            value = float(item["portalNumber"])
            markers[value] = {
                "pk": value,
                "coordenadas": (float(item["lng"]), float(item["lat"])),
            }
    return sorted(markers.values(), key=lambda item: item["pk"])


def fetch_icearagon_road(road: str) -> list[dict]:
    code = DGT_ROAD_ALIASES.get(road, road)
    params = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": "VISOR2D:RedCarCod",
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "CQL_FILTER": f"codigo='{code}'",
    }
    data = json.loads(fetch_bytes(f"{ICEARAGON_ROADS_WFS}?{urlencode(params)}"))
    return data.get("features", [])


def road_graph(features: list[dict]) -> tuple[dict, dict]:
    graph: dict[tuple[float, float], list[tuple[tuple[float, float], float]]] = {}
    coordinates: dict[tuple[float, float], tuple[float, float]] = {}
    for feature in features:
        geometry = feature.get("geometry") or {}
        raw_lines = [geometry.get("coordinates", [])] if geometry.get("type") == "LineString" else geometry.get("coordinates", [])
        if geometry.get("type") not in {"LineString", "MultiLineString"}:
            continue
        for raw_line in raw_lines:
            line = [tuple(map(float, coordinate[:2])) for coordinate in raw_line]
            for first, second in zip(line, line[1:]):
                first_key = (round(first[0], 6), round(first[1], 6))
                second_key = (round(second[0], 6), round(second[1], 6))
                if first_key == second_key:
                    continue
                coordinates.setdefault(first_key, first)
                coordinates.setdefault(second_key, second)
                distance = geographic_distance_m(first, second)
                graph.setdefault(first_key, []).append((second_key, distance))
                graph.setdefault(second_key, []).append((first_key, distance))
    return graph, coordinates


def shortest_road_path(features: list[dict], start: tuple[float, float], end: tuple[float, float]) -> tuple[list[list[float]], float]:
    graph, coordinates = road_graph(features)
    if not coordinates:
        raise RuntimeError("ICEARAGON no ha devuelto una geometría lineal utilizable")
    start_key = min(coordinates, key=lambda key: geographic_distance_m(coordinates[key], start))
    end_key = min(coordinates, key=lambda key: geographic_distance_m(coordinates[key], end))
    if geographic_distance_m(coordinates[start_key], start) > 500 or geographic_distance_m(coordinates[end_key], end) > 500:
        raise RuntimeError("los PK no encajan con el eje oficial de la carretera")

    distances = {start_key: 0.0}
    previous: dict[tuple[float, float], tuple[float, float]] = {}
    pending = [(0.0, start_key)]
    while pending:
        current_distance, current = heapq.heappop(pending)
        if current == end_key:
            break
        if current_distance != distances.get(current):
            continue
        for neighbor, edge_distance in graph.get(current, []):
            candidate = current_distance + edge_distance
            if candidate < distances.get(neighbor, math.inf):
                distances[neighbor] = candidate
                previous[neighbor] = current
                heapq.heappush(pending, (candidate, neighbor))
    if end_key not in distances:
        raise RuntimeError("los PK pertenecen a componentes inconexas del eje viario")

    keys = [end_key]
    while keys[-1] != start_key:
        keys.append(previous[keys[-1]])
    keys.reverse()
    path = [[round(coordinates[key][1], 7), round(coordinates[key][0], 7)] for key in keys]
    return simplify_leaflet_path(path), distances[end_key]


def full_road_path(features: list[dict]) -> tuple[list[list[float]], float]:
    """Devuelve el recorrido completo cuando el intervalo DGT abarca toda la vía."""
    graph, coordinates = road_graph(features)
    endpoints = [key for key, neighbors in graph.items() if len(neighbors) == 1]
    if len(endpoints) < 2:
        raise RuntimeError("el eje oficial no tiene extremos cartográficos inequívocos")
    best: tuple[float, tuple[float, float], tuple[float, float], dict] | None = None
    for start_key in endpoints:
        distances = {start_key: 0.0}
        previous: dict[tuple[float, float], tuple[float, float]] = {}
        pending = [(0.0, start_key)]
        while pending:
            current_distance, current = heapq.heappop(pending)
            if current_distance != distances.get(current):
                continue
            for neighbor, edge_distance in graph.get(current, []):
                candidate = current_distance + edge_distance
                if candidate < distances.get(neighbor, math.inf):
                    distances[neighbor] = candidate
                    previous[neighbor] = current
                    heapq.heappush(pending, (candidate, neighbor))
        for end_key in endpoints:
            distance = distances.get(end_key)
            if distance is not None and (best is None or distance > best[0]):
                best = (distance, start_key, end_key, previous)
    if best is None:
        raise RuntimeError("el eje oficial no forma un recorrido completo")
    distance, start_key, end_key, previous = best
    keys = [end_key]
    while keys[-1] != start_key:
        keys.append(previous[keys[-1]])
    keys.reverse()
    path = [[round(coordinates[key][1], 7), round(coordinates[key][0], 7)] for key in keys]
    return simplify_leaflet_path(path), distance


def simplify_leaflet_path(path: list[list[float]], tolerance_m: float = 6) -> list[list[float]]:
    """Reduce el peso del JSON manteniendo la forma del eje viario al aproximar el mapa."""
    if len(path) < 3:
        return path
    mean_latitude = math.radians(sum(point[0] for point in path) / len(path))

    def projected(point: list[float]) -> tuple[float, float]:
        return point[1] * 111_320 * math.cos(mean_latitude), point[0] * 110_540

    projected_path = [projected(point) for point in path]

    def segment_distance(point, start, end) -> float:
        dx, dy = end[0] - start[0], end[1] - start[1]
        if dx == 0 and dy == 0:
            return math.hypot(point[0] - start[0], point[1] - start[1])
        fraction = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)))
        nearest = start[0] + fraction * dx, start[1] + fraction * dy
        return math.hypot(point[0] - nearest[0], point[1] - nearest[1])

    keep = {0, len(path) - 1}
    pending = [(0, len(path) - 1)]
    while pending:
        first, last = pending.pop()
        maximum, selected = 0.0, None
        for index in range(first + 1, last):
            distance = segment_distance(projected_path[index], projected_path[first], projected_path[last])
            if distance > maximum:
                maximum, selected = distance, index
        if selected is not None and maximum > tolerance_m:
            keep.add(selected)
            pending.extend(((first, selected), (selected, last)))
    return [path[index] for index in sorted(keep)]


def attach_official_road_traces(records: list[dict]) -> list[dict]:
    """Añade trazados con ejes oficiales y PK de ICEARAGON o CartoCiudad."""
    for record in records:
        start = record.get("pk_inicio")
        end = record.get("pk_fin")
        if start is None or end is None:
            record["trazado_no_disponible"] = "El parte oficial no publica un intervalo de puntos kilométricos."
            continue
        if math.isclose(float(start), float(end)):
            record["trazado_no_disponible"] = "DGT publica un corte puntual, sin intervalo lineal que pueda representarse."
            continue
        road = record["carretera"]
        try:
            road_features = fetch_icearagon_road(road)
            markers = fetch_icearagon_pk(road)
            marker_source = "ICEARAGON"
            if len(markers) < 2:
                markers = fetch_cartociudad_pk(road, (float(start), float(end)))
                marker_source = "CartoCiudad/IGN"
            start_marker = min(markers, key=lambda item: abs(item["pk"] - float(start)))
            end_marker = min(markers, key=lambda item: abs(item["pk"] - float(end)))
            if abs(start_marker["pk"] - float(start)) > 1.5 or abs(end_marker["pk"] - float(end)) > 1.5:
                raise RuntimeError("no hay hitos oficiales próximos a los PK comunicados")
            path, length_m = shortest_road_path(road_features, start_marker["coordenadas"], end_marker["coordenadas"])
            expected_m = abs(float(end) - float(start)) * 1_000
            if not 0.65 * expected_m <= length_m <= 1.35 * expected_m:
                raise RuntimeError(f"longitud cartográfica incoherente ({length_m / 1000:.1f} km para {expected_m / 1000:.1f} km)")
            record["trazado"] = path
            record["trazado_aproximado"] = True
            record["trazado_metodo"] = "pk_oficiales"
            record["trazado_pk_referencia"] = {
                "inicio": start_marker["pk"],
                "fin": end_marker["pk"],
            }
            record["trazado_fuente"] = {
                "nombre": f"ICEARAGON — eje viario · {marker_source} — puntos kilométricos",
                "url": ICEARAGON_PK_INFO if marker_source == "ICEARAGON" else CARTOCIUDAD_INFO,
                "catalogo": ICEARAGON_ROADS_INFO,
            }
            print(
                f"Cartografía oficial: trazado {road} PK {format_pk(start_marker['pk'])}–{format_pk(end_marker['pk'])} "
                f"({length_m / 1000:.1f} km)"
            )
        except Exception as error:
            try:
                expected_m = abs(float(end) - float(start)) * 1_000
                if not math.isclose(float(start), 0.0) or expected_m <= 0:
                    raise error
                path, length_m = full_road_path(fetch_icearagon_road(road))
                if not 0.65 * expected_m <= length_m <= 1.35 * expected_m:
                    raise RuntimeError("la longitud del eje completo no coincide con el intervalo de DGT")
                record["trazado"] = path
                record["trazado_aproximado"] = True
                record["trazado_metodo"] = "eje_oficial_completo"
                record["trazado_pk_referencia"] = {"inicio": float(start), "fin": float(end)}
                record["trazado_fuente"] = {
                    "nombre": "ICEARAGON — eje viario oficial completo",
                    "url": ICEARAGON_ROADS_INFO,
                }
                print(f"Cartografía oficial: trazado completo {road} ({length_m / 1000:.1f} km)")
            except Exception as fallback_error:
                record["trazado_no_disponible"] = f"No hay correspondencia cartográfica oficial suficiente: {fallback_error}."
                print(f"AVISO: no se dibuja el tramo de {road}: {fallback_error}")
    return records


def fetch_dgt_fire_road_closures(official_roads: list[dict] | None) -> list[dict] | None:
    """Contrasta las vías del parte con el cuadro vigente de cortes por incendio de DGT.

    Devuelve ``None`` si el PDF no puede validarse, para conservar el último
    parte oficial. Una lista vacía es válida: significa que ninguna de las vías
    del incendio continúa en el cuadro actualizado de DGT.
    """
    if official_roads is None:
        return None
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise RuntimeError("Falta la dependencia pypdf para consultar DGT") from error

    payload = fetch_bytes(f"{DGT_FIRE_ROADS_PDF}&_={int(time.time())}")
    reader = PdfReader(io.BytesIO(payload))
    text = " ".join(" ".join((page.extract_text() or "").split()) for page in reader.pages)
    if "CARRETERAS CORTADAS POR INCENDIO" not in text:
        raise RuntimeError("el PDF de DGT no contiene el encabezado esperado")

    generated_match = re.search(
        r"Fecha de generaci.n del PDF:\s*(\d{2})-(\d{2})-(\d{4})\s+(\d{2}):(\d{2})",
        text,
        re.I,
    )
    if not generated_match:
        raise RuntimeError("el PDF de DGT no contiene una fecha de generación reconocible")
    day, month, year, hour, minute = map(int, generated_match.groups())
    generated_at = datetime(year, month, day, hour, minute, tzinfo=TZ)
    now = datetime.now(TZ)
    if generated_at > now + timedelta(hours=1) or now - generated_at > timedelta(hours=24):
        raise RuntimeError(f"el cuadro de DGT no es reciente ({generated_at.isoformat()})")

    source = {
        "nombre": "DGT — carreteras cortadas por incendio",
        "url": DGT_FIRE_ROADS_PDF,
    }
    records = []
    for official in official_roads:
        road = official["carretera"]
        alias = re.escape(DGT_ROAD_ALIASES.get(road, road))
        match = re.search(
            rf"Arag.n\s+(?:Zaragoza\s+-\s+Huesca|Huesca)\s+{alias}\s+"
            r"(?P<start>\d+(?:\.\d+)?)\s+(?P<end>\d+(?:\.\d+)?)\s+"
            r"(?P<body>.*?)\s+NEGRO",
            text,
            re.I,
        )
        if not match:
            continue
        body = match.group("body")
        if re.match(r"AMBOS SENTIDOS\b", body, re.I):
            direction = "Ambos sentidos"
        elif re.match(r"CRECIENTE DE LA KILOMETRACI.N\b", body, re.I):
            direction = "Sentido creciente de la kilometración"
        elif re.match(r"DECRECIENTE DE LA KILOMETRACI.N\b", body, re.I):
            direction = "Sentido decreciente de la kilometración"
        else:
            raise RuntimeError(f"sentido no reconocido para {road}: {body}")
        start = float(match.group("start"))
        end = float(match.group("end"))
        location = DGT_ROAD_LOCATIONS.get(road, "Tramo indicado por DGT")
        record = {
            "carretera": road,
            "pk_inicio": start,
            "pk_fin": end,
            "tramo": f"entre los pk {format_pk(start)} y {format_pk(end)} · {location}",
            "sentido": direction,
            "localizacion": location,
            "estado": "Cortada",
            "fecha_hora": generated_at.isoformat(timespec="seconds"),
            "fuente": source,
        }
        if road in ROAD_REFERENCE_COORDINATES:
            record["coordenadas"] = ROAD_REFERENCE_COORDINATES[road]
            record["ubicacion_aproximada"] = True
        records.append(record)
    return records


def mark_sources_checked(source_ids: tuple[str, ...], checked_at: str, updates: dict | None = None) -> bool:
    """Marca únicamente fuentes cuya respuesta se ha validado en esta ejecución."""
    path = DATA / "fuentes.json"
    data = read_json(path)
    data["ultima_revision"] = max(data.get("ultima_revision") or "", checked_at)
    for source in data.get("fuentes", []):
        if source.get("id") in source_ids:
            source["ultima_consulta"] = checked_at
            if updates and source.get("id") in updates:
                source.update(updates[source["id"]])
    return write_json_if_changed(path, data)


def update_sources(article: dict, checked_at: str) -> bool:
    path = DATA / "fuentes.json"
    data = read_json(path)
    data["ultima_revision"] = checked_at
    for source in data.get("fuentes", []):
        if source.get("id") == "aragon-hoy-ultimo-parte":
            source["url"] = article["url"]
            source["ultima_consulta"] = checked_at
        elif source.get("id") == "aragon-hoy-busqueda":
            source["ultima_consulta"] = checked_at
    data["fuentes"] = [source for source in data.get("fuentes", []) if source.get("tipo") == "oficial"]
    return write_json_if_changed(path, data)


def verify_consolidated_history() -> list[dict]:
    """Revalida los porcentajes fechados antes de incorporarlos a la serie."""
    verified = []
    for item in CONSOLIDATED_HISTORY:
        try:
            raw = fetch_bytes(
                item["url"],
                user_agent="Mozilla/5.0 (compatible; incendio-riglos-panel/1.0)",
            ).decode("utf-8", errors="replace")
            if not re.search(item["patron"], normalize_text(clean_html(raw)), re.I):
                raise RuntimeError("la cifra esperada ya no aparece en la publicación")
            verified.append(item)
        except Exception as error:
            print(f"AVISO: no se pudo revalidar el {item['value']} % del {item['fecha'][:10]}: {error}")
    if os.environ.get("RIGLOS_STRICT_UPDATE") == "1" and len(verified) != len(CONSOLIDATED_HISTORY):
        raise RuntimeError("no se pudieron revalidar todos los porcentajes históricos del perímetro")
    return verified


def verify_perimeter_length_history() -> list[dict]:
    """Revalida las longitudes fechadas antes de incorporarlas a la serie."""
    verified = []
    for item in PERIMETER_LENGTH_HISTORY:
        try:
            raw = fetch_bytes(
                item["url"],
                user_agent="Mozilla/5.0 (compatible; incendio-riglos-panel/1.0)",
            ).decode("utf-8", errors="replace")
            if not re.search(item["patron"], normalize_text(clean_html(raw)), re.I):
                raise RuntimeError("la longitud esperada ya no aparece en la publicación")
            verified.append(item)
        except Exception as error:
            print(f"AVISO: no se pudo revalidar el perímetro de {item['value']} km del {item['fecha'][:10]}: {error}")
    if os.environ.get("RIGLOS_STRICT_UPDATE") == "1" and len(verified) != len(PERIMETER_LENGTH_HISTORY):
        raise RuntimeError("no se pudieron revalidar todas las longitudes históricas del perímetro")
    return verified


def update_perimeter_history(percent_records: list[dict], length_records: list[dict]) -> bool:
    path = DATA / "cronologia.json"
    data = read_json(path)
    series = data.setdefault("series", [])
    official_hosts = ("www.aragonhoy.es", "aragonhoy.es")
    for point in series:
        meta = point.get("perimetro_consolidado_meta") or {}
        source_url = str(meta.get("fuente", {}).get("url") or "")
        if point.get("perimetro_consolidado_pct") is not None and not any(host in source_url for host in official_hosts):
            point["perimetro_consolidado_pct"] = None
            point.pop("perimetro_consolidado_meta", None)
        length_meta = point.get("perimetro_longitud_meta") or {}
        length_url = str(length_meta.get("fuente", {}).get("url") or "")
        if point.get("perimetro_longitud_km") is not None and not any(host in length_url for host in official_hosts):
            point["perimetro_longitud_km"] = None
            point.pop("perimetro_longitud_meta", None)
    events = [
        event for event in data.setdefault("eventos", [])
        if "cadenaser.com" not in str(event.get("fuente", {}).get("url") or "")
    ]
    data["eventos"] = events
    known_urls = {item.get("fuente", {}).get("url") for item in events}
    for record in percent_records:
        point = next((item for item in series if item.get("fecha") == record["fecha"]), None)
        if point is None:
            point = {
                "fecha": record["fecha"],
                "superficie_ha": None,
                "perimetro_consolidado_pct": None,
                "precipitacion_mm": None,
            }
            series.append(point)
        point["perimetro_consolidado_pct"] = record["value"]
        point["perimetro_consolidado_meta"] = {
            "fecha_hora": record["fecha"],
            "fiabilidad": record["fiabilidad"],
            "fuente": {"nombre": record["nombre"], "url": record["url"]},
        }
        event = next((item for item in events if item.get("fuente", {}).get("url") == record["url"]), None)
        if event is not None:
            event["fiabilidad"] = record["fiabilidad"]
        else:
            events.append({
                "fecha_hora": record["fecha"],
                "categoria": "Perímetro",
                "descripcion": f"Se publica un {record['value']} % del perímetro consolidado.",
                "fiabilidad": record["fiabilidad"],
                "fuente": {"nombre": record["nombre"], "url": record["url"]},
            })
            known_urls.add(record["url"])
    for record in length_records:
        point = next((item for item in series if item.get("fecha") == record["fecha"]), None)
        if point is None:
            point = {
                "fecha": record["fecha"],
                "superficie_ha": None,
                "perimetro_consolidado_pct": None,
                "precipitacion_mm": None,
            }
            series.append(point)
        point["perimetro_longitud_km"] = record["value"]
        point["perimetro_longitud_meta"] = {
            "fecha_hora": record["fecha"],
            "fiabilidad": record["fiabilidad"],
            "fuente": {"nombre": record["nombre"], "url": record["url"]},
        }
    series.sort(key=lambda item: item["fecha"])
    events.sort(key=lambda item: item["fecha_hora"], reverse=True)
    data["nota_edicion"] = (
        "Las superficies, los porcentajes y las longitudes son cifras explícitas publicadas por fuentes oficiales. La línea une "
        "los puntos oficiales disponibles sin inventar valores intermedios; una cifra difundida únicamente "
        "por medios de comunicación no se incorpora."
    )
    return write_json_if_changed(path, data)


def update_chronology(
    article: dict,
    area: int | None,
    nuclei: int | None,
    people: int | None,
    roads: list[dict] | None,
    consolidated: int | None,
) -> bool:
    path = DATA / "cronologia.json"
    data = read_json(path)
    data["ultima_revision"] = article["published_at"]
    known_urls = {item.get("fuente", {}).get("url") for item in data.get("eventos", [])}
    if article["url"] not in known_urls:
        details = []
        if area is not None:
            details.append(f"{area:n} hectáreas provisionales".replace(",", "."))
        if nuclei is not None:
            details.append(f"{nuclei} núcleos evacuados")
        if people is not None:
            details.append(f"{people:n} personas evacuadas".replace(",", "."))
        if roads is not None:
            details.append(f"{len(roads)} vías cortadas")
        if consolidated is not None:
            details.append(f"{consolidated} % del perímetro consolidado")
        description = article["title"] + (". El parte comunica " + ", ".join(details) + "." if details else ".")
        data.setdefault("eventos", []).insert(0, {
            "fecha_hora": article["published_at"],
            "categoria": "Situación general",
            "descripcion": description,
            "fiabilidad": "provisional",
            "fuente": {"nombre": "Gobierno de Aragón / Aragón Hoy", "url": article["url"]},
        })
    point = next((item for item in data.get("series", []) if item.get("fecha") == article["published_at"]), None)
    if point is None and (area is not None or consolidated is not None):
        point = {
            "fecha": article["published_at"],
            "superficie_ha": None,
            "perimetro_consolidado_pct": None,
            "precipitacion_mm": None,
        }
        data.setdefault("series", []).append(point)
    if point is not None:
        if area is not None:
            point["superficie_ha"] = area
        if consolidated is not None:
            point["perimetro_consolidado_pct"] = consolidated
            point["perimetro_consolidado_meta"] = official_meta(
                article["published_at"], article["url"], reliability="provisional"
            )
        data["series"].sort(key=lambda item: item["fecha"])
    return write_json_if_changed(path, data)


def update_official_incident_data() -> bool:
    article = find_latest_official_article()
    checked_at = datetime.now(TZ).isoformat(timespec="seconds")
    normalized = article["normalized"]
    area = first_integer(normalized, (
        r"superficie.{0,120}?(?:mantiene|asciende|alcanza|estima|supera|afecta)[^0-9]{0,40}([0-9][0-9.\s]*)\s*hectareas",
        r"([0-9][0-9.\s]*)\s*hectareas.{0,80}?superficie",
    ))
    people = first_integer(normalized, (
        r"(?:evacuad|desalojad)[^.]{0,100}?([0-9][0-9.\s]*)\s+personas",
        r"([0-9][0-9.\s]*)\s+personas[^.]{0,80}?(?:evacuad|desalojad)",
    ))
    nuclei = first_integer(normalized, (
        r"([0-9][0-9.\s]*)\s+nucleos(?:\s+de\s+poblacion)?\s+(?:desalojad|evacuad)",
        r"(?:evacuad|desalojad)[^.]{0,100}?([0-9][0-9.\s]*)\s+nucleos",
    ))
    roads = parse_closed_roads(article)
    try:
        dgt_roads = fetch_dgt_fire_road_closures(roads)
        if dgt_roads is not None:
            roads = dgt_roads
            print(f"DGT: {len(roads)} cortes del incendio vigentes en el cuadro de carreteras")
            mark_sources_checked(
                ("dgt",),
                checked_at,
                {
                    "dgt": {
                        "nombre": "DGT — carreteras cortadas por incendio",
                        "url": DGT_FIRE_ROADS_PDF,
                        "alcance": "Estado, puntos kilométricos y sentido de los cortes vigentes por incendio",
                    }
                },
            )
    except Exception as error:
        print(f"AVISO: no se pudieron contrastar los cortes con DGT: {error}")
    if roads:
        roads = attach_official_road_traces(roads)
    status = explicit_fire_status(normalized)
    consolidated = first_integer(normalized, (
        r"([0-9]{1,3})\s*%\s+del\s+perimetro\s+consolidado",
        r"perimetro.{0,60}?consolidad[oa].{0,30}?([0-9]{1,3})\s*%",
        r"consolidad[oa].{0,50}?([0-9]{1,3})\s*%\s+del\s+perimetro",
    ))
    perimeter_length = first_decimal(normalized, (
        r"perimetro.{0,50}?(?:de|alcanza|asciende a)\s*([0-9][0-9.,]*)\s*kilometros",
    ))
    verified_consolidated = verify_consolidated_history()
    verified_lengths = verify_perimeter_length_history()

    state_path = DATA / "estado.json"
    state = read_json(state_path)
    state["ultima_comprobacion_panel"] = checked_at
    state["ultimo_informe_cecopi"] = article["ultimo_informe_cecopi"]
    if article["published_at"] >= (state.get("ultima_actualizacion_oficial") or ""):
        state["ultima_actualizacion_oficial"] = article["published_at"]
    if status:
        state["estado"] = {"value": status, "meta": official_meta(article["published_at"], article["url"])}
    if area is not None and 100 <= area <= 250_000:
        state["superficie_ha"] = {"value": area, "meta": official_meta(article["published_at"], article["url"], reliability="provisional")}
    if nuclei is not None and 0 <= nuclei <= 500:
        state["nucleos_evacuados"] = {"value": nuclei, "meta": official_meta(article["published_at"], article["url"])}
    if people is not None and 0 <= people <= 100_000:
        state["personas_evacuadas"] = {"value": people, "meta": official_meta(article["published_at"], article["url"])}
    if consolidated is not None and 0 <= consolidated <= 100:
        state["perimetro_consolidado_pct"] = {
            "value": consolidated,
            "meta": official_meta(article["published_at"], article["url"], reliability="provisional"),
        }
    else:
        state["perimetro_consolidado_pct"] = {"value": None, "meta": None}
    if verified_consolidated:
        latest_consolidated = max(verified_consolidated, key=lambda item: item["fecha"])
        state["perimetro_consolidado_ultimo_pct"] = {
            "value": latest_consolidated["value"],
            "meta": {
                "fecha_hora": latest_consolidated["fecha"],
                "fiabilidad": "historico",
                "vigencia": "Último porcentaje explícito localizado en una publicación oficial; no confirmado como vigente en partes posteriores.",
                "fuente": {"nombre": latest_consolidated["nombre"], "url": latest_consolidated["url"]},
            },
        }
    else:
        state["perimetro_consolidado_ultimo_pct"] = {"value": None, "meta": None}
    if perimeter_length is not None and 1 <= perimeter_length <= 2_000:
        state["perimetro_longitud_ultima_km"] = {
            "value": perimeter_length,
            "meta": {
                **official_meta(article["published_at"], article["url"], reliability="historico"),
                "vigencia": "Última longitud explícita publicada; puede no ser el valor vigente.",
            },
        }
    elif verified_lengths:
        latest_length = max(verified_lengths, key=lambda item: item["fecha"])
        state["perimetro_longitud_ultima_km"] = {
            "value": latest_length["value"],
            "meta": {
                "fecha_hora": latest_length["fecha"],
                "fiabilidad": "historico",
                "vigencia": "Última longitud explícita publicada; puede no ser el valor vigente.",
                "fuente": {"nombre": latest_length["nombre"], "url": latest_length["url"]},
            },
        }
    elif "aragonhoy.es" not in str(((state.get("perimetro_longitud_ultima_km", {}).get("meta") or {}).get("fuente") or {}).get("url") or ""):
        state["perimetro_longitud_ultima_km"] = {"value": None, "meta": None}
    state["nota_edicion"] = (
        "Actualización automática conservadora a partir del último parte oficial localizado en Aragón Hoy. "
        "Solo se incorporan cifras explícitas; los datos no publicados se conservan o se muestran sin actualización."
    )
    changed = write_json_if_changed(state_path, state)

    evacuations_path = DATA / "evacuaciones.json"
    evacuations = read_json(evacuations_path)
    evacuations["ultima_revision"] = article["published_at"]
    for record in evacuations.get("registros", []):
        coordinates = EVACUATION_COORDINATES.get(record.get("poblacion"))
        if coordinates:
            record["coordenadas"] = coordinates
            record["coordenadas_fuente"] = "OpenStreetMap/Nominatim"
    evacuations["nota_edicion"] = (
        "El total procede del último parte oficial. La relación nominal conserva la última fuente que enumeró "
        "cada núcleo; no se infieren retornos ni nuevas evacuaciones. Las coordenadas identifican el núcleo o "
        "establecimiento y no posiciones operativas."
    )
    changed = write_json_if_changed(evacuations_path, evacuations) or changed

    if roads is not None:
        roads_path = DATA / "carreteras.json"
        road_data = read_json(roads_path)
        road_data["ultima_revision"] = max((item["fecha_hora"] for item in roads), default=checked_at)
        road_data["registros"] = roads
        if roads and roads[0].get("fuente", {}).get("nombre", "").startswith("DGT"):
            road_data["nota_edicion"] = (
                "Relación contrastada con el cuadro vigente de carreteras cortadas por incendio de DGT. "
                "Los trazados enlazan el eje oficial de ICEARAGON con hitos kilométricos oficiales de "
                "ICEARAGON o CartoCiudad/IGN; son aproximaciones cartográficas entre esos PK. "
                "Cuando no existe correspondencia suficiente se conserva un marcador y se explica el motivo. "
                "Verificar de nuevo en DGT o 011 antes de desplazarse."
            )
        else:
            road_data["nota_edicion"] = (
                "Relación extraída del último parte oficial que enumera expresamente las vías cortadas. "
                "Los marcadores son referencias orientativas del entorno del tramo, no el punto exacto del corte. "
                "Verificar de nuevo en DGT o 112 antes de desplazarse."
            )
        changed = write_json_if_changed(roads_path, road_data) or changed

    changed = update_chronology(article, area, nuclei, people, roads, consolidated) or changed
    changed = update_perimeter_history(verified_consolidated, verified_lengths) or changed
    changed = update_sources(article, checked_at) or changed
    print(f"Aragón Hoy: {article['published_at']} · {article['url']}")
    return changed


def number(value: str | None, *, integer: bool = False):
    if value is None or not value.strip():
        return None
    parsed = float(value.replace(",", "."))
    return int(parsed) if integer or parsed.is_integer() else parsed


def by_period(day, tag: str, *, attribute: str | None = None) -> dict[str, object]:
    result = {}
    for node in day.findall(tag):
        period = node.get("periodo")
        if not period:
            continue
        result[period] = node.get(attribute) if attribute else number(node.text, integer=True)
    return result


def period_label(periods: list[str]) -> str | None:
    hours = sorted({int(period) for period in periods if period.isdigit() and len(period) == 2})
    if not hours:
        return None
    start = hours[0]
    end = start
    longest = (start, end)
    current = (start, end)
    for hour in hours[1:]:
        if hour == current[1] + 1:
            current = (current[0], hour)
        else:
            if current[1] - current[0] > longest[1] - longest[0]:
                longest = current
            current = (hour, hour)
    if current[1] - current[0] > longest[1] - longest[0]:
        longest = current
    return f"{longest[0]:02d} h" if longest[0] == longest[1] else f"{longest[0]:02d}–{longest[1]:02d} h"


def extreme(values: dict[str, object], mode=max) -> tuple[object | None, str | None]:
    valid = {period: value for period, value in values.items() if value is not None}
    if not valid:
        return None, None
    selected = mode(valid.values())
    periods = [period for period, value in valid.items() if value == selected]
    return selected, period_label(periods)


def iso_local(value: str, pattern: str) -> str:
    return datetime.strptime(value, pattern).replace(tzinfo=TZ).isoformat()


def parse_spanish_date(value: str) -> str | None:
    match = re.search(r"(\d{1,2})\s+([a-záéíóú]+)\.?\s+(\d{4})", normalize_text(value))
    if not match:
        return None
    month = SPANISH_MONTHS.get(match.group(2))
    if not month:
        return None
    return datetime(int(match.group(3)), month, int(match.group(1))).date().isoformat()


def aemet_csv_link(station_id: str, view: int, marker: str) -> str:
    page_url = (
        "https://www.aemet.es/es/eltiempo/observacion/ultimosdatos?"
        f"datos=det&k=arn&l={station_id}&w={view}"
    )
    page = fetch_bytes(page_url, user_agent="Mozilla/5.0").decode("iso-8859-15", errors="replace")
    links = [unescape(item) for item in re.findall(r'href=["\']([^"\']+\.csv\?[^"\']+)["\']', page, re.I)]
    link = next((item for item in links if marker in item and f"l={station_id}" in item), None)
    if not link:
        raise RuntimeError(f"AEMET no publicó el CSV {marker} para {station_id}")
    return urljoin(page_url, link)


def precipitation_number(value: str | None):
    if not value or not re.fullmatch(r"\s*\d+(?:[.,]\d+)?\s*", value):
        return None
    return number(value)


def fetch_daily_precipitation(station: dict) -> list[dict]:
    station_id = station["idema"]
    source_url = f"https://www.aemet.es/es/eltiempo/observacion/ultimosdatos?l={station_id}&datos=det&w=2"
    source = {"nombre": f"AEMET — resúmenes diarios de {station['nombre']}", "url": source_url}
    records = []

    current_url = aemet_csv_link(station_id, 1, "_resumen-")
    current_text = fetch_bytes(current_url, user_agent="Mozilla/5.0").decode("iso-8859-15", errors="replace")
    current_lines = current_text.splitlines()
    current_date = next((parse_spanish_date(line) for line in current_lines if line.startswith("Actualizado:")), None)
    header_index = next(index for index, line in enumerate(current_lines) if '"Estación"' in line)
    current_rows = list(csv.DictReader(io.StringIO("\n".join(current_lines[header_index:]))))
    if current_date and current_rows:
        records.append({
            "fecha": current_date,
            "idema": station_id,
            "estacion": station["nombre"],
            "precipitacion_mm": precipitation_number(current_rows[0].get("Precipitación 00-24h (mm)")),
            "estado": "Día en curso",
            "completo": False,
            "fuente": source,
        })

    history_url = aemet_csv_link(station_id, 2, "_resumenes-diarios-anteriores")
    history_text = fetch_bytes(history_url, user_agent="Mozilla/5.0").decode("iso-8859-15", errors="replace")
    history_lines = history_text.splitlines()
    history_header = next(index for index, line in enumerate(history_lines) if '"Fecha y hora oficial"' in line)
    for row in csv.DictReader(io.StringIO("\n".join(history_lines[history_header:]))):
        date = parse_spanish_date(row.get("Fecha y hora oficial", ""))
        if not date or date < INCIDENT_START:
            continue
        records.append({
            "fecha": date,
            "idema": station_id,
            "estacion": station["nombre"],
            "precipitacion_mm": precipitation_number(row.get("Precipitación 00-24h (mm)")),
            "estado": "Día completo",
            "completo": True,
            "fuente": source,
        })
    if not records:
        raise RuntimeError(f"AEMET no devolvió precipitación diaria para {station['nombre']}")
    return records


def merge_daily_precipitation(existing: list[dict], current: list[dict]) -> list[dict]:
    merged = {
        (item.get("fecha"), item.get("idema")): item
        for item in existing
        if item.get("fecha") and item.get("idema")
    }
    for item in current:
        merged[(item["fecha"], item["idema"])] = item
    return sorted(merged.values(), key=lambda item: (item["fecha"], item["estacion"]))


def update_weather() -> bool:
    hourly_url = f"https://www.aemet.es/xml/municipios_h/localidad_h_{MUNICIPALITY_ID}.xml"
    root = ElementTree.fromstring(decode_xml(fetch_bytes(hourly_url)))
    today = datetime.now(TZ).date().isoformat()
    days = root.findall("./prediccion/dia")
    day = next((item for item in days if item.get("fecha") == today), None)
    if day is None:
        day = next((item for item in days if (item.get("fecha") or "") >= today), None)
    if day is None:
        raise RuntimeError("AEMET no ha devuelto una predicción utilizable")

    temperatures = by_period(day, "temperatura")
    humidity = by_period(day, "humedad_relativa")
    precipitation = by_period(day, "precipitacion")
    precipitation_probability = by_period(day, "prob_precipitacion")
    storm_probability = by_period(day, "prob_tormenta")
    skies = by_period(day, "estado_cielo", attribute="descripcion")
    gusts = by_period(day, "racha_max")
    winds = {}
    directions = {}
    for wind in day.findall("viento"):
        period = wind.get("periodo")
        if not period:
            continue
        winds[period] = number(wind.findtext("velocidad"), integer=True)
        directions[period] = wind.findtext("direccion") or None

    temp_max, temp_max_period = extreme(temperatures, max)
    temp_min, temp_min_period = extreme(temperatures, min)
    humidity_max, _ = extreme(humidity, max)
    humidity_min, _ = extreme(humidity, min)
    wind_max, wind_max_period = extreme(winds, max)
    gust_max, gust_max_period = extreme(gusts, max)
    peak_direction = next((directions[p] for p, v in winds.items() if v == wind_max), None)
    daytime_skies = [value for period, value in skies.items() if period.isdigit() and 8 <= int(period) <= 20 and value]
    sky = Counter(daytime_skies).most_common(1)[0][0] if daytime_skies else None
    prob_precip = max((value for value in precipitation_probability.values() if value is not None), default=None)
    prob_storm = max((value for value in storm_probability.values() if value is not None), default=None)
    precip_total = sum(value for value in precipitation.values() if value is not None)

    hourly = []
    preferred_hours = ["08", "11", "14", "17", "20", "23"]
    for period in preferred_hours:
        if period not in temperatures:
            continue
        hourly.append({
            "hora": f"{period}:00",
            "temperatura_c": temperatures.get(period),
            "humedad_pct": humidity.get(period),
            "viento_kmh": winds.get(period),
            "direccion": directions.get(period),
            "racha_kmh": gusts.get(period),
            "precipitacion_mm": precipitation.get(period),
            "cielo": skies.get(period),
        })

    station_url = (
        "https://www.aemet.es/es/eltiempo/observacion/"
        f"ultimosdatos_{STATION['idema']}_datos-horarios.csv?"
        f"k=arn&l={STATION['idema']}&datos=det&w=0&f=temperatura&x="
    )
    csv_text = fetch_bytes(station_url).decode("iso-8859-15")
    lines = csv_text.splitlines()
    header_index = next(index for index, line in enumerate(lines) if "Fecha y hora oficial" in line)
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[header_index:]))))
    if not rows:
        raise RuntimeError("AEMET no ha devuelto observaciones horarias")
    observation_fields = (
        "Temperatura (ºC)",
        "Humedad (%)",
        "Velocidad del viento (km/h)",
        "Racha (km/h)",
        "Precipitación (mm)",
    )
    latest = next(
        (
            row for row in rows
            if any(number(row.get(field)) is not None for field in observation_fields)
        ),
        rows[0],
    )
    observed_at = datetime.strptime(latest["Fecha y hora oficial"], "%d/%m/%Y %H:%M").replace(tzinfo=TZ)
    current_day_rows = [
        row for row in rows
        if datetime.strptime(row["Fecha y hora oficial"], "%d/%m/%Y %H:%M").date() == observed_at.date()
    ]
    daily_gusts = [number(row.get("Racha (km/h)")) for row in current_day_rows]
    daily_precip = [number(row.get("Precipitación (mm)")) for row in current_day_rows]
    daily_gusts = [value for value in daily_gusts if value is not None]
    daily_precip = [value for value in daily_precip if value is not None]

    elaborated = root.findtext("elaborado")
    forecast_time = iso_local(elaborated, "%Y-%m-%dT%H:%M:%S") if elaborated else None
    forecast_source = {
        "nombre": "AEMET — predicción horaria de Las Peñas de Riglos",
        "url": "https://www.aemet.es/es/eltiempo/prediccion/municipios/horas/penas-de-riglos-las-id22173",
    }
    observation_source = {
        "nombre": f"AEMET — estación {STATION['nombre']}",
        "url": f"https://www.aemet.es/es/eltiempo/observacion/ultimosdatos?l={STATION['idema']}",
    }
    previous_weather = read_json(DATA / "meteo.json")
    daily_precipitation = []
    station_errors = []
    for station in STATIONS:
        try:
            daily_precipitation.extend(fetch_daily_precipitation(station))
        except Exception as error:
            station_errors.append(f"{station['nombre']}: {error}")
    if station_errors:
        raise RuntimeError("No se validó la precipitación diaria de ambas estaciones: " + "; ".join(station_errors))
    daily_precipitation = merge_daily_precipitation(
        previous_weather.get("precipitacion_diaria", []), daily_precipitation
    )

    result = {
        "ultima_revision": max(filter(None, [forecast_time, observed_at.isoformat()])),
        "prevision": {
            "temperatura_maxima_c": {"value": temp_max, "periodo": temp_max_period},
            "temperatura_minima_c": {"value": temp_min, "periodo": temp_min_period},
            "humedad_minima_pct": {"value": humidity_min},
            "humedad_maxima_pct": {"value": humidity_max},
            "viento_maximo_kmh": {"value": wind_max, "periodo": wind_max_period},
            "direccion_viento_maximo": {"value": peak_direction, "periodo": wind_max_period},
            "racha_maxima_kmh": {"value": gust_max, "periodo": gust_max_period},
            "prob_precipitacion_pct": {"value": prob_precip},
            "precipitacion_total_mm": {"value": precip_total},
            "prob_tormenta_pct": {"value": prob_storm},
            "cielo": {"value": sky},
            "horaria": hourly,
            "meta": {
                "fecha_hora": forecast_time,
                "periodo": day.get("fecha"),
                "fiabilidad": "oficial",
                "fuente": forecast_source,
            },
        },
        "observacion": {
            "precipitacion_ultima_hora_mm": {"value": number(latest.get("Precipitación (mm)"))},
            "precipitacion_desde_00_mm": {"value": sum(daily_precip) if daily_precip else None},
            "racha_actual_kmh": {"value": number(latest.get("Racha (km/h)"))},
            "racha_maxima_desde_00_kmh": {"value": max(daily_gusts) if daily_gusts else None},
            "humedad_relativa_pct": {"value": number(latest.get("Humedad (%)"))},
            "temperatura_c": {"value": number(latest.get("Temperatura (ºC)"))},
            "viento_kmh": {"value": number(latest.get("Velocidad del viento (km/h)"))},
            "direccion": {"value": latest.get("Dirección del viento") or None},
            "meta": {
                "fecha_hora": observed_at.isoformat(),
                "fiabilidad": "oficial",
                "estacion": STATION,
                "control_calidad": "Controles automáticos de calidad en tiempo real de AEMET",
                "fuente": observation_source,
            },
        },
        "estaciones": list(STATIONS),
        "precipitacion_diaria": daily_precipitation,
        "aviso": (
            "La predicción corresponde al punto de referencia municipal utilizado por AEMET. "
            "La observación procede de la estación de Bailo, Puyalto, y no representa necesariamente "
            "las condiciones en todo el incendio."
        ),
    }
    checked_at = datetime.now(TZ).isoformat(timespec="seconds")
    changed = write_json_if_changed(DATA / "meteo.json", result)
    changed = mark_sources_checked(
        ("aemet",),
        checked_at,
        {
            "aemet": {
                "alcance": (
                    "Predicción horaria municipal, observación de Bailo-Puyalto y "
                    "precipitación diaria registrada en Bailo-Puyalto y Jaca"
                )
            }
        },
    ) or changed
    return changed


def update_perimeter() -> bool:
    year = datetime.now(TZ).year
    params = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": "VISOR2D:Perimetros_activos",
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "CQL_FILTER": f"anio={year} AND nombre ILIKE '%RIGLOS%'",
    }
    urls = [
        "https://icearagon.aragon.es/Visor2D?" + urlencode(params),
        "https://idearagon.aragon.es/Visor2D?" + urlencode(params),
    ]
    payload = None
    source_url = None
    errors = []
    for url in urls:
        try:
            payload = json.loads(fetch_bytes(url).decode("utf-8"))
            source_url = url
            break
        except Exception as error:
            errors.append(str(error))
    if payload is None:
        raise RuntimeError("; ".join(errors))
    checked_at = datetime.now(TZ).isoformat(timespec="seconds")
    source_changed = mark_sources_checked(("icearagon-perimetros",), checked_at)
    features = payload.get("features") or []
    if not features:
        print("ICEARAGON: todavía no existe un perímetro 2026 de Riglos")
        return source_changed

    dates = [feature.get("properties", {}).get("fecha_mod") for feature in features]
    dates = [value for value in dates if value]
    result = {
        "type": "FeatureCollection",
        "metadata": {
            "estado": "oficial",
            "es_ficticio": False,
            "aviso": "Perímetro incorporado desde la capa oficial de ICEARAGON.",
            "fuente": {"nombre": "ICEARAGON — perímetros de incendios forestales", "url": source_url},
            "fecha_hora": max(dates) if dates else datetime.now(TZ).isoformat(timespec="seconds"),
        },
        "features": features,
    }
    return write_json_if_changed(DATA / "perimetro.geojson", result) or source_changed


def xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_text(value: str | None) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", value or "")
        if unicodedata.category(char) != "Mn"
    ).lower()


def gml_coordinates(node) -> list[list[float]]:
    if node is None or not node.text:
        return []
    coordinates = []
    for token in re.split(r"\s+", node.text.strip()):
        parts = token.split(",")
        if len(parts) < 2:
            continue
        coordinates.append([float(parts[0]), float(parts[1])])
    if coordinates and coordinates[0] != coordinates[-1]:
        coordinates.append(coordinates[0])
    return coordinates


def gml_geometry(feature) -> dict | None:
    geometry_node = next(
        (child for child in feature if xml_local_name(child.tag) == "msGeometry"),
        None,
    )
    if geometry_node is None:
        return None
    polygons = []
    for polygon in geometry_node.findall(".//{*}Polygon"):
        outer = gml_coordinates(
            polygon.find("./{*}outerBoundaryIs/{*}LinearRing/{*}coordinates")
        )
        if len(outer) < 4:
            continue
        rings = [outer]
        rings.extend(
            ring for ring in (
                gml_coordinates(node)
                for node in polygon.findall(
                    "./{*}innerBoundaryIs/{*}LinearRing/{*}coordinates"
                )
            )
            if len(ring) >= 4
        )
        polygons.append(rings)
    if not polygons:
        return None
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def geometry_points(geometry: dict) -> list[list[float]]:
    points = []

    def visit(value):
        if (
            isinstance(value, list)
            and len(value) >= 2
            and all(isinstance(item, (int, float)) for item in value[:2])
        ):
            points.append(value[:2])
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(geometry.get("coordinates", []))
    return points


def effis_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    parsed = datetime.strptime(value.split(".", 1)[0], "%Y-%m-%d %H:%M:%S")
    return parsed.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ).isoformat()


def update_effis_approximate_perimeter() -> bool:
    params = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": "modis.ba.poly",
        "srsName": "EPSG:4326",
        "bbox": ",".join(str(value) for value in INCIDENT_BBOX),
    }
    source_url = EFFIS_WFS + "?" + urlencode(params)
    root = ElementTree.fromstring(decode_xml(fetch_bytes(source_url)))
    candidates = []
    for member in root.findall(".//{*}featureMember"):
        feature = next(iter(member), None)
        if feature is None:
            continue
        properties = {
            xml_local_name(child.tag): (child.text or "").strip()
            for child in feature
            if xml_local_name(child.tag) not in {"boundedBy", "msGeometry"}
        }
        fire_date = properties.get("FIREDATE", "")[:10]
        commune = normalize_text(properties.get("COMMUNE"))
        if fire_date < INCIDENT_START or "riglos" not in commune:
            continue
        geometry = gml_geometry(feature)
        area = number(properties.get("AREA_HA"), integer=True)
        if geometry is None or area is None or not 1_000 <= area <= 100_000:
            continue
        points = geometry_points(geometry)
        west, south, east, north = INCIDENT_BBOX
        if not points or any(not (west <= lon <= east and south <= lat <= north) for lon, lat in points):
            continue
        candidates.append((properties, geometry, area))

    checked_at = datetime.now(TZ).isoformat(timespec="seconds")
    source_changed = mark_sources_checked(("effis",), checked_at)
    if not candidates:
        print("EFFIS: todavía no existe un área quemada atribuible a Riglos")
        return source_changed

    properties, geometry, area = max(
        candidates,
        key=lambda item: (item[0].get("FINALDATE", ""), item[2]),
    )
    official_state = json.loads((DATA / "estado.json").read_text(encoding="utf-8"))
    official_area = official_state.get("superficie_ha", {}).get("value")
    difference = None
    if official_area:
        difference = round(abs(area - official_area) / official_area * 100, 1)
        if difference > 40:
            raise RuntimeError(
                f"EFFIS devuelve {area} ha, diferencia incompatible con las {official_area} ha publicadas"
            )

    observed_at = effis_timestamp(properties.get("FINALDATE"))
    result = {
        "type": "FeatureCollection",
        "metadata": {
            "estado": "satelital_aproximado",
            "es_ficticio": False,
            "es_perimetro_operativo": False,
            "tipo": "area_quemada_estimada",
            "aviso": (
                "Área quemada estimada por satélite. No equivale al perímetro operativo, "
                "al porcentaje consolidado ni a una instrucción de seguridad."
            ),
            "fecha_hora": observed_at,
            "superficie_ha": area,
            "control_calidad": {
                "superficie_oficial_referencia_ha": official_area,
                "diferencia_pct": difference,
                "umbral_maximo_diferencia_pct": 40,
                "municipio_coincidente": properties.get("COMMUNE"),
                "inicio_posterior_a": INCIDENT_START,
            },
            "fuente": {
                "nombre": "EFFIS / Copernicus — áreas quemadas satelitales",
                "url": source_url,
            },
            "licencia": "Copernicus EMS / EFFIS; reutilización con atribución",
        },
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "nombre": "Área quemada aproximada EFFIS — Las Peñas de Riglos",
                    "tipo": "area_quemada_satelital",
                    "superficie_ha": area,
                    "fecha_inicio": effis_timestamp(properties.get("FIREDATE")),
                    "fecha_fin": observed_at,
                    "ultima_actualizacion_effis": effis_timestamp(properties.get("LASTUPDATE")),
                    "municipio": properties.get("COMMUNE"),
                    "provincia": properties.get("PROVINCE"),
                    "id_effis": properties.get("id"),
                },
                "geometry": geometry,
            }
        ],
    }
    return write_json_if_changed(DATA / "perimetro-aproximado.geojson", result) or source_changed


def write_json_if_changed(path: Path, data: dict) -> bool:
    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if current == rendered:
        return False
    path.write_text(rendered, encoding="utf-8")
    return True


if __name__ == "__main__":
    changed = []
    failures = []
    try:
        if update_official_incident_data():
            changed.append("parte oficial, estado, evacuaciones, carreteras, cronología y fuentes")
    except Exception as error:
        print(f"AVISO: no se pudo actualizar Aragón Hoy; se conservan los datos anteriores: {error}")
        failures.append(f"Aragón Hoy: {error}")
    try:
        if update_weather():
            changed.append("meteo")
    except Exception as error:
        print(f"AVISO: no se pudo actualizar AEMET; se conservan los datos anteriores: {error}")
        failures.append(f"AEMET: {error}")
    try:
        if update_perimeter():
            changed.append("perímetro")
    except Exception as error:
        print(f"AVISO: no se pudo consultar ICEARAGON; se conserva el perímetro anterior: {error}")
        failures.append(f"ICEARAGON: {error}")
    try:
        if update_effis_approximate_perimeter():
            changed.append("área aproximada EFFIS")
    except Exception as error:
        print(f"AVISO: no se pudo actualizar EFFIS; se conserva la capa anterior: {error}")
        failures.append(f"EFFIS: {error}")
    print("Actualizados: " + (", ".join(changed) if changed else "sin cambios"))
    if failures and os.environ.get("RIGLOS_STRICT_UPDATE") == "1":
        raise SystemExit(
            "Actualización cancelada: no se publicará un resultado parcial.\n- "
            + "\n- ".join(failures)
        )
