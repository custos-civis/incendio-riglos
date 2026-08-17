#!/usr/bin/env python3
"""Validaciones conservadoras de los datos antes de publicar GitHub Pages."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TZ = ZoneInfo("Europe/Madrid")
INCIDENT_BBOX = (-1.15, 42.10, -0.25, 42.72)
OFFICIAL_SOURCE_HOSTS = (
    "aragonhoy.es", "aragon.es", "aemet.es", "dgt.es", "cartociudad.es",
    "idearagon.aragon.es", "opendata.aragon.es", "copernicus.eu", "europa.eu",
)
SECONDARY_PERIMETER_URL = (
    "https://cadenaser.com/aragon/2026/08/17/"
    "miguel-angel-clavero-en-hoy-por-hoy-hemos-podido-estabilizar-diferentes-frentes-"
    "del-incendio-de-las-penas-de-riglos-radio-zaragoza/"
)
errors: list[str] = []


def fail(message: str) -> None:
    errors.append(message)


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        fail(f"{path.name}: JSON no válido ({error})")
        return None


def valid_https_source(source, context: str) -> None:
    if not isinstance(source, dict) or not str(source.get("url", "")).startswith("https://"):
        fail(f"{context}: falta una fuente HTTPS")


def official_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(
        host == allowed or host.endswith(f".{allowed}")
        for allowed in OFFICIAL_SOURCE_HOSTS
    )


def validate_all_urls(value, context: str) -> None:
    """Impide que cualquier archivo público introduzca enlaces ajenos a la lista oficial."""
    if isinstance(value, dict):
        for key, child in value.items():
            validate_all_urls(child, f"{context}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_all_urls(child, f"{context}[{index}]")
    elif isinstance(value, str) and value.startswith(("http://", "https://")):
        secondary_context = "estado.json.perimetro_longitud_secundaria_km.meta.fuente.url"
        if not official_url(value) and not (context == secondary_context and value == SECONDARY_PERIMETER_URL):
            fail(f"{context}: URL no oficial o sin HTTPS ({value})")


def valid_date(value, context: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("sin zona horaria")
        if parsed > datetime.now(TZ) + timedelta(hours=1):
            fail(f"{context}: fecha futura ({value})")
    except Exception as error:
        fail(f"{context}: fecha no válida ({value!r}: {error})")


def valid_latlon(point, context: str) -> bool:
    if not isinstance(point, list) or len(point) != 2:
        fail(f"{context}: coordenada [latitud, longitud] no válida")
        return False
    try:
        lat, lon = map(float, point)
    except (TypeError, ValueError):
        fail(f"{context}: coordenada no numérica")
        return False
    min_lon, min_lat, max_lon, max_lat = INCIDENT_BBOX
    if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
        fail(f"{context}: coordenada fuera del ámbito del incendio ({lat}, {lon})")
        return False
    return True


def validate_roads(data) -> None:
    records = data.get("registros") if isinstance(data, dict) else None
    if not isinstance(records, list) or len(records) > 30:
        fail("carreteras.json: registros ausentes o excesivos")
        return
    names = [record.get("carretera") for record in records]
    if len(names) != len(set(names)):
        fail("carreteras.json: hay carreteras duplicadas")
    for index, record in enumerate(records):
        context = f"carreteras.json registro {index + 1} ({record.get('carretera', '?')})"
        if record.get("estado") != "Cortada":
            fail(f"{context}: estado distinto de Cortada")
        valid_date(record.get("fecha_hora"), context)
        valid_https_source(record.get("fuente"), context)
        for key in ("pk_inicio", "pk_fin"):
            value = record.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 2_000:
                fail(f"{context}: {key} no válido")
        if record.get("coordenadas") is not None:
            valid_latlon(record["coordenadas"], f"{context} marcador")
        trace = record.get("trazado")
        if trace is None:
            if not isinstance(record.get("trazado_no_disponible"), str) or len(record["trazado_no_disponible"].strip()) < 20:
                fail(f"{context}: falta el motivo por el que no puede dibujarse el tramo")
            continue
        if not isinstance(trace, list) or len(trace) < 2 or len(trace) > 10_000:
            fail(f"{context}: trazado vacío o excesivo")
            continue
        for point_index, point in enumerate(trace):
            valid_latlon(point, f"{context} trazado punto {point_index + 1}")
        reference = record.get("trazado_pk_referencia")
        if not isinstance(reference, dict) or not all(isinstance(reference.get(key), (int, float)) for key in ("inicio", "fin")):
            fail(f"{context}: faltan los PK cartográficos de referencia")
        else:
            if abs(float(reference["inicio"]) - float(record["pk_inicio"])) > 1.5:
                fail(f"{context}: el PK inicial cartográfico se aleja demasiado del publicado")
            if abs(float(reference["fin"]) - float(record["pk_fin"])) > 1.5:
                fail(f"{context}: el PK final cartográfico se aleja demasiado del publicado")
        valid_https_source(record.get("trazado_fuente"), f"{context} trazado")
        if record.get("trazado_metodo") not in {"pk_oficiales", "eje_oficial_completo"}:
            fail(f"{context}: método cartográfico no reconocido")


def validate_official_sources(documents: dict) -> None:
    sources = documents.get("fuentes.json", {}).get("fuentes", [])
    for source in sources:
        if source.get("tipo") != "oficial":
            fail(f"fuentes.json: {source.get('id', '?')} no es una fuente oficial")
        url = str(source.get("url") or "")
        if not official_url(url):
            fail(f"fuentes.json: dominio no oficial en {source.get('id', '?')}")
    chronology = documents.get("cronologia.json", {})
    for point in chronology.get("series", []):
        percentage = point.get("perimetro_consolidado_pct")
        if percentage is not None:
            if not isinstance(percentage, (int, float)) or not 0 <= percentage <= 100:
                fail("cronologia.json: porcentaje de perímetro fuera de rango")
            url = str(point.get("perimetro_consolidado_meta", {}).get("fuente", {}).get("url") or "")
            if "aragonhoy.es" not in url:
                fail("cronologia.json: porcentaje de perímetro sin fuente oficial del Gobierno de Aragón")
        length = point.get("perimetro_longitud_km")
        if length is not None:
            if not isinstance(length, (int, float)) or not 0 < length <= 2_000:
                fail("cronologia.json: longitud de perímetro fuera de rango")
            url = str(point.get("perimetro_longitud_meta", {}).get("fuente", {}).get("url") or "")
            if "aragonhoy.es" not in url:
                fail("cronologia.json: longitud de perímetro sin fuente oficial del Gobierno de Aragón")
    state = documents.get("estado.json", {})
    secondary = state.get("perimetro_longitud_secundaria_km") if isinstance(state, dict) else None
    if secondary is not None:
        meta = secondary.get("meta") or {}
        source = meta.get("fuente") or {}
        if secondary.get("value") != 100:
            fail("estado.json: la referencia periodística de perímetro no coincide con los 100 km publicados")
        if meta.get("fiabilidad") != "fuente_secundaria":
            fail("estado.json: la referencia periodística no está etiquetada como fuente secundaria")
        if source.get("url") != SECONDARY_PERIMETER_URL:
            fail("estado.json: la referencia periodística no usa la publicación contrastada")
        valid_date(meta.get("fecha_hora"), "estado.json referencia periodística de perímetro")


def validate_geojson(path: Path, data) -> None:
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        fail(f"{path.name}: no es un FeatureCollection válido")


def main() -> None:
    documents = {}
    for path in sorted(DATA.glob("*.json")) + sorted(DATA.glob("*.geojson")):
        documents[path.name] = load(path)
    validate_roads(documents.get("carreteras.json"))
    validate_official_sources(documents)
    for name, document in documents.items():
        validate_all_urls(document, name)
        if name.endswith(".geojson"):
            validate_geojson(DATA / name, document)
    state = documents.get("estado.json")
    if not isinstance(state, dict):
        fail("estado.json: objeto ausente")
    else:
        valid_date(state.get("ultima_comprobacion_panel"), "estado.json última comprobación")
        report = state.get("ultimo_informe_cecopi")
        if not isinstance(report, dict) or "aragonhoy.es" not in str(report.get("url") or ""):
            fail("estado.json: falta el último informe oficial de CECOPI")
        else:
            valid_date(report.get("fecha_hora"), "estado.json informe CECOPI")
    if errors:
        raise SystemExit("Validación fallida:\n- " + "\n- ".join(errors))
    print(f"Validación completa: {len(documents)} archivos y {len(documents['carreteras.json'].get('registros', []))} cortes comprobados")


if __name__ == "__main__":
    main()
