#!/usr/bin/env python3
"""Actualiza datos públicos que pueden obtenerse sin credenciales.

Fuentes:
- AEMET: predicción horaria municipal y observación de Bailo, Puyalto.
- ICEARAGON: perímetro oficial, únicamente cuando exista un registro de 2026
  cuyo nombre contenga "Riglos".
- EFFIS/Copernicus: área quemada satelital, separada del perímetro operativo.

El script no fabrica valores ni geometrías: conserva separadas las capas oficiales
y las estimaciones satelitales publicadas por sus proveedores.
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TZ = ZoneInfo("Europe/Madrid")
MUNICIPALITY_ID = "22173"
STATION = {
    "idema": "9211F",
    "nombre": "Bailo, Puyalto",
    "distancia_capital_municipal_km": 19.79,
    "altitud_m": 722,
    "coordenadas": [42.5141666667, -0.8172222222],
}
INCIDENT_BBOX = (-1.15, 42.10, -0.25, 42.72)
INCIDENT_START = "2026-08-09"
EFFIS_WFS = "https://maps.effis.emergency.copernicus.eu/effis"


def fetch_bytes(url: str, attempts: int = 2) -> bytes:
    last_error = None
    for attempt in range(attempts):
        request = Request(url, headers={"User-Agent": "incendio-riglos-panel/1.0"})
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
        "estaciones": [
            STATION,
            {
                "idema": "9201X",
                "nombre": "Jaca",
                "distancia_capital_municipal_km": 29.6,
                "altitud_m": 832,
                "coordenadas": [42.5797222222, -0.545],
            },
        ],
        "precipitacion_efecto_operativo": [],
        "observaciones_permitidas": [
            "Sin lluvia significativa",
            "Lluvia local",
            "Lluvia potencialmente útil",
            "Tormenta con rachas erráticas",
            "Pendiente de confirmar",
        ],
        "aviso": (
            "La predicción corresponde a la capital municipal. La observación procede de Bailo, Puyalto, "
            "a 19,79 km de la capital municipal, y no representa necesariamente las condiciones en todo el incendio."
        ),
    }
    return write_json_if_changed(DATA / "meteo.json", result)


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
    features = payload.get("features") or []
    if not features:
        print("ICEARAGON: todavía no existe un perímetro 2026 de Riglos")
        return False

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
    return write_json_if_changed(DATA / "perimetro.geojson", result)


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

    if not candidates:
        print("EFFIS: todavía no existe un área quemada atribuible a Riglos")
        return False

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
    return write_json_if_changed(DATA / "perimetro-aproximado.geojson", result)


def write_json_if_changed(path: Path, data: dict) -> bool:
    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if current == rendered:
        return False
    path.write_text(rendered, encoding="utf-8")
    return True


if __name__ == "__main__":
    changed = []
    try:
        if update_weather():
            changed.append("meteo")
    except Exception as error:
        print(f"AVISO: no se pudo actualizar AEMET; se conservan los datos anteriores: {error}")
    try:
        if update_perimeter():
            changed.append("perímetro")
    except Exception as error:
        print(f"AVISO: no se pudo consultar ICEARAGON; se conserva el perímetro anterior: {error}")
    try:
        if update_effis_approximate_perimeter():
            changed.append("área aproximada EFFIS")
    except Exception as error:
        print(f"AVISO: no se pudo actualizar EFFIS; se conserva la capa anterior: {error}")
    print("Actualizados: " + (", ".join(changed) if changed else "sin cambios"))
