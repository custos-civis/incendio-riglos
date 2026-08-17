#!/usr/bin/env python3
"""Segunda comprobación externa de DGT y del informe CECOPI antes de publicar."""

from __future__ import annotations

import io
import json
import re
from html import unescape
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TZ = ZoneInfo("Europe/Madrid")
DGT_PDF = "https://www.dgt.es/estaticos/movilidad/CarreterasCortadasIncendios.pdf?origen=app"
ALIASES = {"HF-0262-BA": "HF0262BA"}
ARAGON_HOY = "https://www.aragonhoy.es"
ARAGON_HOY_CATEGORY = f"{ARAGON_HOY}/hacienda-interior-administracion-publica"


def fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "incendio-riglos-secondary-verifier/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def clean_html(fragment: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def latest_cecopi_article() -> dict:
    """Localiza de forma independiente el último parte oficial que identifica al CECOPI."""
    category = fetch(ARAGON_HOY_CATEGORY).decode("utf-8", errors="replace")
    links = set()
    for href in re.findall(r'href=["\']([^"\']+)["\']', category, re.I):
        url = urljoin(ARAGON_HOY, unescape(href)).rstrip("/")
        normalized = clean_html(url).lower()
        if (
            urlparse(url).netloc == "www.aragonhoy.es"
            and "/hacienda-interior-administracion-publica/" in url
            and ("incendio" in normalized or "extincion" in normalized)
            and "riglos" in normalized
            and re.search(r"-\d{5,}$", url)
        ):
            links.add(url)

    candidates = []
    for url in sorted(links, key=lambda item: int(item.rsplit("-", 1)[-1]), reverse=True)[:20]:
        raw = fetch(url).decode("utf-8", errors="replace")
        published = re.search(r'"datePublished"\s*:\s*"([^"]+)"', raw)
        paragraphs = [clean_html(item) for item in re.findall(
            r'<p\b[^>]*class=["\'][^"\']*\bparagraph\b[^"\']*["\'][^>]*>(.*?)</p>',
            raw,
            re.I | re.S,
        )]
        captions = [clean_html(item) for item in re.findall(
            r'<figcaption\b[^>]*>(.*?)</figcaption>', raw, re.I | re.S,
        )]
        article_text = " ".join((*paragraphs, *captions))
        if published and re.search(r"Pe.as de Riglos", article_text, re.I) and re.search(r"\bCECOPI\b", article_text, re.I):
            candidates.append({
                "url": url,
                "fecha_hora": datetime.fromisoformat(published.group(1)).astimezone(TZ).isoformat(),
            })
    if not candidates:
        raise RuntimeError("no se localizó ningún parte CECOPI verificable en Aragón Hoy")
    return max(candidates, key=lambda item: item["fecha_hora"])


def verify_dgt(roads: list[dict]) -> None:
    text = " ".join(" ".join((page.extract_text() or "").split()) for page in PdfReader(io.BytesIO(fetch(DGT_PDF))).pages)
    generated = re.search(r"Fecha de generaci.n del PDF:\s*(\d{2})-(\d{2})-(\d{4})\s+(\d{2}):(\d{2})", text, re.I)
    if not generated:
        raise RuntimeError("DGT no publica una fecha reconocible")
    day, month, year, hour, minute = map(int, generated.groups())
    published = datetime(year, month, day, hour, minute, tzinfo=TZ)
    if datetime.now(TZ) - published > timedelta(hours=24):
        raise RuntimeError("el cuadro de DGT tiene más de 24 horas")
    for road in roads:
        code = re.escape(ALIASES.get(road["carretera"], road["carretera"]))
        match = re.search(
            rf"Arag.n\s+(?:Zaragoza\s+-\s+Huesca|Huesca)\s+{code}\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+.*?\s+NEGRO",
            text,
            re.I,
        )
        if not match:
            raise RuntimeError(f"DGT ya no incluye {road['carretera']}")
        official = tuple(map(float, match.groups()))
        local = float(road["pk_inicio"]), float(road["pk_fin"])
        if any(abs(a - b) > 0.05 for a, b in zip(official, local)):
            raise RuntimeError(f"los PK de {road['carretera']} no coinciden con DGT: {local} frente a {official}")


def verify_cecopi(state: dict) -> None:
    report = state["ultimo_informe_cecopi"]
    raw = fetch(report["url"]).decode("utf-8", errors="replace")
    published = re.search(r'"datePublished"\s*:\s*"([^"]+)"', raw)
    visible = re.sub(r"<[^>]+>", " ", raw)
    if not published or datetime.fromisoformat(published.group(1)).astimezone(TZ).isoformat() != report["fecha_hora"]:
        raise RuntimeError("la fecha del informe CECOPI no coincide con Aragón Hoy")
    if not re.search(r"Pe.as de Riglos", visible, re.I) or not re.search(r"\bCECOPI\b", visible, re.I):
        raise RuntimeError("el enlace guardado no es un informe CECOPI de Las Peñas de Riglos")
    latest = latest_cecopi_article()
    if latest["url"] != report["url"] or latest["fecha_hora"] != report["fecha_hora"]:
        raise RuntimeError(
            "el enlace guardado no es el último parte CECOPI oficial: "
            f"{report['fecha_hora']} frente a {latest['fecha_hora']}"
        )


def verify_perimeter_history(chronology: dict) -> tuple[int, int]:
    """Contrasta cada porcentaje y longitud de la serie con su publicación oficial."""
    cache: dict[str, str] = {}
    percentages = lengths = 0
    for point in chronology.get("series", []):
        percentage = point.get("perimetro_consolidado_pct")
        if percentage is not None:
            meta = point.get("perimetro_consolidado_meta") or {}
            url = str((meta.get("fuente") or {}).get("url") or "")
            if urlparse(url).netloc not in {"aragonhoy.es", "www.aragonhoy.es"}:
                raise RuntimeError("un porcentaje histórico no tiene fuente oficial de Aragón Hoy")
            visible = cache.setdefault(url, clean_html(fetch(url).decode("utf-8", errors="replace")))
            explicit = re.search(rf"{re.escape(str(percentage))}\s*%", visible, re.I)
            half = percentage == 50 and re.search(r"mitad\s+del\s+per.metro", visible, re.I)
            if not explicit and not half:
                raise RuntimeError(f"el {percentage} % histórico no aparece en su publicación oficial")
            percentages += 1

        length = point.get("perimetro_longitud_km")
        if length is not None:
            meta = point.get("perimetro_longitud_meta") or {}
            url = str((meta.get("fuente") or {}).get("url") or "")
            if urlparse(url).netloc not in {"aragonhoy.es", "www.aragonhoy.es"}:
                raise RuntimeError("una longitud histórica no tiene fuente oficial de Aragón Hoy")
            visible = cache.setdefault(url, clean_html(fetch(url).decode("utf-8", errors="replace")))
            displayed = str(length).replace(".", "[,.]")
            if not re.search(rf"per.metro.{{0,80}}{displayed}\s+kil.metros", visible, re.I):
                raise RuntimeError(f"el perímetro de {length} km no aparece en su publicación oficial")
            lengths += 1
    if percentages < 1 or lengths < 2:
        raise RuntimeError("la serie histórica del perímetro está incompleta")
    return percentages, lengths


def verify_secondary_perimeter_reference(state: dict) -> bool:
    """Comprueba la referencia periodística sin confundirla con la serie oficial."""
    datum = state.get("perimetro_longitud_secundaria_km")
    if not datum:
        return False
    meta = datum.get("meta") or {}
    source = meta.get("fuente") or {}
    url = str(source.get("url") or "")
    if datum.get("value") != 100 or meta.get("fiabilidad") != "fuente_secundaria":
        raise RuntimeError("la referencia periodística de perímetro no está correctamente etiquetada")
    if urlparse(url).netloc not in {"cadenaser.com", "www.cadenaser.com"}:
        raise RuntimeError("la referencia periodística no procede de la publicación contrastada")
    visible = clean_html(fetch(url).decode("utf-8", errors="replace"))
    if not re.search(r"per.metro\s+cercano\s+a\s+los\s+100\s+kil.metros", visible, re.I):
        raise RuntimeError("la publicación periodística ya no contiene la referencia de 100 km")
    if not re.search(r"Miguel\s+.ngel\s+Clavero", visible, re.I):
        raise RuntimeError("la publicación no identifica al responsable entrevistado")
    return True


def main() -> None:
    roads = json.loads((DATA / "carreteras.json").read_text(encoding="utf-8"))["registros"]
    state = json.loads((DATA / "estado.json").read_text(encoding="utf-8"))
    chronology = json.loads((DATA / "cronologia.json").read_text(encoding="utf-8"))
    verify_dgt(roads)
    verify_cecopi(state)
    percentages, lengths = verify_perimeter_history(chronology)
    has_secondary = verify_secondary_perimeter_reference(state)
    print(
        "Verificación externa completa: "
        f"DGT ({len(roads)} cortes), último informe CECOPI y serie de perímetro "
        f"({percentages} porcentaje, {lengths} longitudes) coinciden"
        + ("; referencia periodística contrastada" if has_secondary else "")
    )


if __name__ == "__main__":
    main()
