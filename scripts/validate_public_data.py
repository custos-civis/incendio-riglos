#!/usr/bin/env python3
"""Validaciones conservadoras de los datos antes de publicar GitHub Pages."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TZ = ZoneInfo("Europe/Madrid")
INCIDENT_BBOX = (-1.15, 42.10, -0.25, 42.72)
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


def validate_geojson(path: Path, data) -> None:
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        fail(f"{path.name}: no es un FeatureCollection válido")


def main() -> None:
    documents = {}
    for path in sorted(DATA.glob("*.json")) + sorted(DATA.glob("*.geojson")):
        documents[path.name] = load(path)
    validate_roads(documents.get("carreteras.json"))
    for name, document in documents.items():
        if name.endswith(".geojson"):
            validate_geojson(DATA / name, document)
    state = documents.get("estado.json")
    if not isinstance(state, dict):
        fail("estado.json: objeto ausente")
    else:
        valid_date(state.get("ultima_comprobacion_panel"), "estado.json última comprobación")
    if errors:
        raise SystemExit("Validación fallida:\n- " + "\n- ".join(errors))
    print(f"Validación completa: {len(documents)} archivos y {len(documents['carreteras.json'].get('registros', []))} cortes comprobados")


if __name__ == "__main__":
    main()
