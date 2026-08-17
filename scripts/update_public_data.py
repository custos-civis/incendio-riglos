#!/usr/bin/env python3
"""Actualiza datos públicos que pueden obtenerse sin credenciales.

Fuentes:
- Aragón Hoy: último parte oficial, estado, superficie, evacuaciones,
  carreteras y cronología.
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
STATION = {
    "idema": "9211F",
    "nombre": "Bailo, Puyalto",
    "distancia_capital_municipal_km": 19.79,
    "altitud_m": 722,
    "coordenadas": [42.5141666667, -0.8172222222],
}
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
INCIDENT_BBOX = (-1.15, 42.10, -0.25, 42.72)
INCIDENT_START = "2026-08-09"
EFFIS_WFS = "https://maps.effis.emergency.copernicus.eu/effis"
ARAGON_HOY = "https://www.aragonhoy.es"
CADENA_SER_ARAGON = "https://cadenaser.com/aragon/"
CADENA_SER_PERIMETER_SEED = (
    "https://cadenaser.com/aragon/2026/08/17/"
    "luis-biendicho-el-incendio-de-las-penas-de-riglos-evoluciona-favorablemente-"
    "pero-tenemos-fuego-para-dias-radio-zaragoza/"
)
ARAGON_HOY_PAGES = (
    f"{ARAGON_HOY}/",
    f"{ARAGON_HOY}/hacienda-interior-administracion-publica",
)


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
                and "incendio" in normalized
                and "riglos" in normalized
                and re.search(r"-\d{5,}/?$", url)
            ):
                links.add(url.rstrip("/"))
    if not links:
        raise RuntimeError("No se localizaron partes de Riglos en Aragón Hoy: " + "; ".join(errors))

    articles = []
    for url in sorted(links, key=lambda item: int(item.rsplit("-", 1)[-1]), reverse=True)[:8]:
        try:
            raw = fetch_bytes(url).decode("utf-8")
            published_match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', raw)
            title_match = re.search(r'"headline"\s*:\s*"([^"]+)"', raw)
            paragraphs = [clean_html(item) for item in re.findall(
                r'<p\b[^>]*class=["\'][^"\']*\bparagraph\b[^"\']*["\'][^>]*>(.*?)</p>',
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
            })
        except Exception as error:
            errors.append(f"{url}: {error}")
    if not articles:
        raise RuntimeError("No se pudo leer un parte oficial verificable: " + "; ".join(errors))
    return max(articles, key=lambda item: item["published_at"])


def explicit_fire_status(normalized: str) -> str | None:
    checks = (
        ("Extinguido", r"incendio.{0,80}(?:queda|se da por|esta) extinguido"),
        ("Controlado", r"incendio.{0,80}(?:queda|se da por|esta) controlado"),
        ("Estabilizado", r"incendio.{0,80}(?:queda|se da por|esta) estabilizado"),
        ("Activo", r"incendio.{0,80}(?:permanece|continua|sigue) activo"),
    )
    return next((label for label, pattern in checks if re.search(pattern, normalized)), None)


def nested_dicts(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from nested_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from nested_dicts(item)


def find_latest_reported_perimeter(previous_url: str | None = None) -> dict:
    links = {CADENA_SER_PERIMETER_SEED}
    if previous_url and "cadenaser.com/" in previous_url:
        links.add(previous_url)
    try:
        page = fetch_bytes(CADENA_SER_ARAGON, user_agent="Mozilla/5.0 (compatible; incendio-riglos-panel/1.0)").decode("utf-8")
        for href in re.findall(r'href=["\']([^"\']+)["\']', page, re.I):
            url = urljoin(CADENA_SER_ARAGON, unescape(href))
            normalized = normalize_text(url)
            if "cadenaser.com/aragon/" in url and "incendio" in normalized and "riglos" in normalized:
                links.add(url.split("?", 1)[0])
    except Exception as error:
        print(f"AVISO: no se pudo revisar la portada de Cadena SER; se comprueban las referencias conocidas: {error}")
    reports = []
    for url in list(links)[:12]:
        raw = fetch_bytes(url, user_agent="Mozilla/5.0 (compatible; incendio-riglos-panel/1.0)").decode("utf-8")
        documents = []
        for script in re.findall(
            r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            raw,
            re.I | re.S,
        ):
            try:
                documents.append(json.loads(unescape(script).strip()))
            except (json.JSONDecodeError, TypeError):
                continue
        for item in (entry for document in documents for entry in nested_dicts(document)):
            body = item.get("articleBody")
            published_at = item.get("datePublished")
            if not isinstance(body, str) or not isinstance(published_at, str):
                continue
            normalized_body = normalize_text(body)
            if "penas de riglos" not in normalized_body:
                continue
            match = re.search(
                r"perimetro.{0,100}?(?:alcanza|cercano a|aproximad[oa]|de)?\s*(?:los|unos)?\s*([0-9]{1,3})\s*kilometros",
                normalized_body,
            )
            if not match:
                continue
            length = int(match.group(1))
            if not 10 <= length <= 500:
                continue
            reports.append({
                "value": length,
                "published_at": datetime.fromisoformat(published_at).astimezone(TZ).isoformat(),
                "url": url,
                "title": item.get("headline") or "Información sobre el perímetro",
            })
    if not reports:
        raise RuntimeError("Cadena SER no ha publicado una longitud inequívoca en los artículos localizados")
    return max(reports, key=lambda item: item["published_at"])


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


def update_sources(article: dict, checked_at: str, perimeter_report: dict | None = None) -> bool:
    path = DATA / "fuentes.json"
    data = read_json(path)
    data["ultima_revision"] = checked_at
    for source in data.get("fuentes", []):
        if source.get("id") == "aragon-hoy-ultimo-parte":
            source["url"] = article["url"]
            source["ultima_consulta"] = checked_at
        elif source.get("id") in {"aragon-hoy-busqueda", "aemet", "icearagon-perimetros", "effis"}:
            source["ultima_consulta"] = checked_at
    if perimeter_report:
        source = next((item for item in data.get("fuentes", []) if item.get("id") == "cadena-ser-perimetro"), None)
        values = {
            "id": "cadena-ser-perimetro",
            "nombre": "Cadena SER — declaraciones de responsables del Gobierno de Aragón",
            "url": perimeter_report["url"],
            "tipo": "provisional",
            "ultima_consulta": checked_at,
            "alcance": "Longitud aproximada del perímetro comunicada en entrevista",
        }
        if source is None:
            data.setdefault("fuentes", []).append(values)
        else:
            source.update(values)
    return write_json_if_changed(path, data)


def update_perimeter_report_chronology(report: dict | None) -> bool:
    if not report:
        return False
    path = DATA / "cronologia.json"
    data = read_json(path)
    known_urls = {item.get("fuente", {}).get("url") for item in data.get("eventos", [])}
    if report["url"] in known_urls:
        return False
    data.setdefault("eventos", []).insert(0, {
        "fecha_hora": report["published_at"],
        "categoria": "Perímetro",
        "descripcion": (
            f"El perímetro alcanza aproximadamente {report['value']} kilómetros, "
            "según declaraciones de responsables del Gobierno de Aragón recogidas por Cadena SER."
        ),
        "fiabilidad": "provisional",
        "fuente": {"nombre": "Cadena SER / responsables del Gobierno de Aragón", "url": report["url"]},
    })
    data["eventos"].sort(key=lambda item: item["fecha_hora"], reverse=True)
    data["ultima_revision"] = max(data.get("ultima_revision") or "", report["published_at"])
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
    if area is not None and not any(item.get("fecha") == article["published_at"] for item in data.get("series", [])):
        data.setdefault("series", []).append({
            "fecha": article["published_at"],
            "superficie_ha": area,
            "perimetro_consolidado_pct": consolidated,
            "precipitacion_mm": None,
        })
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
    status = explicit_fire_status(normalized)
    consolidated = first_integer(normalized, (
        r"([0-9]{1,3})\s*%\s+del\s+perimetro\s+consolidado",
        r"perimetro.{0,60}?consolidad[oa].{0,30}?([0-9]{1,3})\s*%",
        r"consolidad[oa].{0,50}?([0-9]{1,3})\s*%\s+del\s+perimetro",
    ))
    perimeter_length = first_integer(normalized, (
        r"perimetro.{0,50}?(?:de|alcanza|asciende a)\s*([0-9][0-9.]*)\s*kilometros",
    ))

    state_path = DATA / "estado.json"
    state = read_json(state_path)
    previous_length_url = state.get("perimetro_longitud_ultima_km", {}).get("meta", {}).get("fuente", {}).get("url")
    perimeter_report = None
    try:
        perimeter_report = find_latest_reported_perimeter(previous_length_url)
    except Exception as error:
        print(f"AVISO: no se pudo actualizar la longitud publicada del perímetro: {error}")
    state["ultima_comprobacion_panel"] = checked_at
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
    if perimeter_length is not None and 1 <= perimeter_length <= 2_000:
        state["perimetro_longitud_ultima_km"] = {
            "value": perimeter_length,
            "meta": {
                **official_meta(article["published_at"], article["url"], reliability="historico"),
                "vigencia": "Última longitud explícita publicada; puede no ser el valor vigente.",
            },
        }
    if perimeter_report and perimeter_report["published_at"] >= state.get("perimetro_longitud_ultima_km", {}).get("meta", {}).get("fecha_hora", ""):
        state["perimetro_longitud_ultima_km"] = {
            "value": perimeter_report["value"],
            "meta": {
                "fecha_hora": perimeter_report["published_at"],
                "fiabilidad": "provisional",
                "vigencia": "Longitud aproximada comunicada por responsables del Gobierno de Aragón en entrevista.",
                "fuente": {
                    "nombre": "Cadena SER / responsables del Gobierno de Aragón",
                    "url": perimeter_report["url"],
                },
            },
        }
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
        road_data["ultima_revision"] = article["published_at"]
        road_data["registros"] = roads
        road_data["nota_edicion"] = (
            "Relación extraída del último parte oficial que enumera expresamente las vías cortadas. "
            "Los marcadores son referencias orientativas del entorno del tramo, no el punto exacto del corte. "
            "Verificar de nuevo en DGT o 112 antes de desplazarse."
        )
        changed = write_json_if_changed(roads_path, road_data) or changed

    changed = update_chronology(article, area, nuclei, people, roads, consolidated) or changed
    changed = update_perimeter_report_chronology(perimeter_report) or changed
    changed = update_sources(article, checked_at, perimeter_report) or changed
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
        if update_official_incident_data():
            changed.append("parte oficial, estado, evacuaciones, carreteras, cronología y fuentes")
    except Exception as error:
        print(f"AVISO: no se pudo actualizar Aragón Hoy; se conservan los datos anteriores: {error}")
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
