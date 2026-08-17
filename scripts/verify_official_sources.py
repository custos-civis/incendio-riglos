#!/usr/bin/env python3
"""Segunda comprobación externa de DGT y del informe CECOPI antes de publicar."""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TZ = ZoneInfo("Europe/Madrid")
DGT_PDF = "https://www.dgt.es/estaticos/movilidad/CarreterasCortadasIncendios.pdf?origen=app"
ALIASES = {"HF-0262-BA": "HF0262BA"}


def fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "incendio-riglos-secondary-verifier/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read()


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


def main() -> None:
    roads = json.loads((DATA / "carreteras.json").read_text(encoding="utf-8"))["registros"]
    state = json.loads((DATA / "estado.json").read_text(encoding="utf-8"))
    verify_dgt(roads)
    verify_cecopi(state)
    print(f"Verificación externa completa: DGT ({len(roads)} cortes) y último informe CECOPI coinciden")


if __name__ == "__main__":
    main()
