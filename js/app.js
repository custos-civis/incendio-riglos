"use strict";

const DATA_FILES = {
  estado: "data/estado.json",
  evacuaciones: "data/evacuaciones.json",
  carreteras: "data/carreteras.json",
  meteo: "data/meteo.json",
  cronologia: "data/cronologia.json",
  fuentes: "data/fuentes.json"
};

const state = { data: {}, chartKey: "superficie_ha" };

document.addEventListener("DOMContentLoaded", init);

async function init() {
  try {
    const entries = await Promise.all(Object.entries(DATA_FILES).map(async ([key, url]) => {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
      return [key, await response.json()];
    }));
    state.data = Object.fromEntries(entries);
    renderAll();
    await window.RiglosMap?.init(state.data);
  } catch (error) {
    console.error("No se pudieron cargar los datos locales:", error);
    renderLoadError();
  }
}

function renderAll() {
  renderDates();
  renderSummary();
  renderEvacuations();
  renderRoads();
  renderWeather();
  renderTimeline();
  renderSources();
  setupChartTabs();
  renderChart();
}

function renderDates() {
  setTime("panel-checked", state.data.estado.ultima_comprobacion_panel);
  setTime("official-updated", state.data.estado.ultima_actualizacion_oficial, "Sin actualización oficial");
}

function renderSummary() {
  const e = state.data.estado;
  const m = state.data.meteo;
  const cards = [
    metricCard("Estado del incendio", e.estado, "", e.estado_meta, String(e.estado?.value || "").toLowerCase() === "activo" ? "danger" : ""),
    metricCard("Superficie", e.superficie_ha, "ha", e.superficie_ha?.meta),
    metricCard("Perímetro consolidado", e.perimetro_consolidado_pct, "%", e.perimetro_consolidado_pct?.meta),
    evacuationsCard(e),
    weatherCard(m)
  ];
  document.getElementById("status-cards").innerHTML = cards.join("");
}

function metricCard(label, datum, unit, fallbackMeta, className = "") {
  const normalized = normalizeDatum(datum, fallbackMeta);
  const value = displayValue(normalized.value, unit);
  return `<article class="metric-card ${className}">
    <span class="metric-label">${escapeHtml(label)}</span>
    <strong class="metric-value ${normalized.value == null ? "unavailable" : ""} ${className === "danger" ? "active" : ""}">${escapeHtml(value)}</strong>
    ${sourceBlock(normalized.meta)}
  </article>`;
}

function evacuationsCard(e) {
  const nuclei = normalizeDatum(e.nucleos_evacuados);
  const people = normalizeDatum(e.personas_evacuadas);
  const known = nuclei.value != null || people.value != null;
  const main = known
    ? `<div class="weather-brief evacuation-brief"><div><span>Núcleos</span><strong>${escapeHtml(nuclei.value ?? "—")}</strong></div><div><span>Personas aprox.</span><strong>${escapeHtml(people.value ?? "—")}</strong></div></div>`
    : `<strong class="metric-value unavailable">Sin actualización oficial</strong>`;
  return `<article class="metric-card evacuation-card"><span class="metric-label">Evacuaciones</span>${main}${sourceBlock(nuclei.meta || people.meta)}</article>`;
}

function weatherCard(m) {
  const o = m.observacion || {};
  const values = [
    ["Viento", formatNumber(o.viento_kmh?.value, " km/h")],
    ["Dirección", o.direccion?.value],
    ["Racha máx.", formatNumber(o.racha_maxima_kmh?.value, " km/h")],
    ["Humedad", formatNumber(o.humedad_relativa_pct?.value, " %")],
    ["Precipitación", formatNumber(o.precipitacion_mm?.value, " mm")]
  ];
  return `<article class="metric-card weather-card"><span class="metric-label">Observación meteorológica</span><div class="weather-brief">${values.map(([l,v]) => `<div><span>${escapeHtml(l)}</span><strong>${escapeHtml(v ?? "—")}</strong></div>`).join("")}</div>${sourceBlock(o.meta)}</article>`;
}

function renderEvacuations() {
  const rows = state.data.evacuaciones.registros || [];
  document.getElementById("evacuations-body").innerHTML = rows.length ? rows.map(row => `<tr>
    <th scope="row">${escapeHtml(row.poblacion)}</th>
    <td><span class="status-pill ${slug(row.estado)}">${escapeHtml(row.estado)}</span></td>
    <td>${formatDate(row.fecha_hora)}</td>
    <td>${sourceLink(row.fuente)}</td>
  </tr>`).join("") : `<tr><td colspan="4" class="empty-cell"><strong>Sin registros oficiales incorporados</strong><br>Este apartado no presupone que no existan medidas; indica que el panel aún no dispone de un dato oficial verificable.</td></tr>`;
}

function renderRoads() {
  const roads = state.data.carreteras.registros || [];
  document.getElementById("roads-list").innerHTML = roads.length ? roads.map(road => `<article class="road-card ${slug(road.estado)}">
    <div class="road-name"><strong>${escapeHtml(road.carretera)}</strong><span class="status-pill ${slug(road.estado)}">${escapeHtml(road.estado)}</span></div>
    <dl><dt>Tramo</dt><dd>${escapeHtml(road.tramo || "Sin detalle oficial")}</dd><dt>Actualización</dt><dd>${formatDate(road.fecha_hora)}</dd></dl>
    <div class="source-line">${sourceLink(road.fuente)}</div>
  </article>`).join("") : `<p class="empty-state"><strong>Sin cortes oficiales incorporados</strong><br>Consulta siempre el mapa de tráfico de la DGT antes de desplazarte.</p>`;
}

function renderWeather() {
  renderWeatherGroup("forecast-data", "forecast-source", state.data.meteo.prevision, [
    ["Temperatura", "temperatura_c", " °C"], ["Viento", "viento_kmh", " km/h"], ["Dirección", "direccion", ""],
    ["Prob. precipitación", "prob_precipitacion_pct", " %"], ["Tormentas", "tormentas", ""]
  ]);
  renderWeatherGroup("observation-data", "observation-source", state.data.meteo.observacion, [
    ["Precipitación", "precipitacion_mm", " mm"], ["Racha máxima", "racha_maxima_kmh", " km/h"],
    ["Humedad", "humedad_relativa_pct", " %"], ["Temperatura", "temperatura_c", " °C"], ["Viento", "viento_kmh", " km/h"], ["Dirección", "direccion", ""]
  ]);
  const records = state.data.meteo.precipitacion_efecto_operativo || [];
  document.getElementById("rain-records").innerHTML = records.length ? records.map(r => `<div class="rain-record"><div><span>Fecha</span><strong>${formatDate(r.fecha)}</strong></div><div><span>Estación</span><strong>${escapeHtml(r.estacion)}</strong></div><div><span>Precipitación</span><strong>${formatNumber(r.precipitacion_mm, " mm") ?? "—"}</strong></div><div><span>Observación</span><strong>${escapeHtml(r.observacion)}</strong></div></div>`).join("") : `<p class="empty-state">Sin registros manuales incorporados.</p>`;
}

function renderWeatherGroup(dataId, sourceId, group, fields) {
  document.getElementById(dataId).innerHTML = fields.map(([label,key,unit]) => `<div class="weather-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(formatDatum(group?.[key]?.value, unit))}</strong></div>`).join("");
  document.getElementById(sourceId).innerHTML = sourceBlock(group?.meta, true);
}

function renderTimeline() {
  const events = state.data.cronologia.eventos || [];
  document.getElementById("timeline").innerHTML = events.length ? events.map(event => `<li class="timeline-item">
    <time class="timeline-time" datetime="${escapeAttr(event.fecha_hora)}">${formatDate(event.fecha_hora)}</time>
    <p class="timeline-category">${escapeHtml(event.categoria)}</p>
    <p class="timeline-description">${escapeHtml(event.descripcion)}</p>
    <div class="timeline-meta">${sourceLink(event.fuente)} ${badge(event.fiabilidad)}</div>
  </li>`).join("") : `<li class="empty-state"><strong>No hay eventos oficiales incorporados.</strong><br>La cronología comenzará cuando exista un parte oficial verificable.</li>`;
}

function renderSources() {
  const sources = state.data.fuentes.fuentes || [];
  document.getElementById("sources-list").innerHTML = sources.map(source => `<a class="source-card" href="${escapeAttr(source.url)}" target="_blank" rel="noopener noreferrer"><strong>${escapeHtml(source.nombre)}</strong><span>Última consulta: ${formatDate(source.ultima_consulta)}</span><span class="arrow" aria-hidden="true">↗</span></a>`).join("");
}

function setupChartTabs() {
  const tabs = [...document.querySelectorAll("[data-chart]")];
  tabs.forEach((button, index) => {
    button.tabIndex = button.getAttribute("aria-selected") === "true" ? 0 : -1;
    button.addEventListener("click", () => selectChartTab(button, tabs));
    button.addEventListener("keydown", event => {
      const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
      if (!keys.includes(event.key)) return;
      event.preventDefault();
      const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      selectChartTab(tabs[nextIndex], tabs);
      tabs[nextIndex].focus();
    });
  });
}

function selectChartTab(selected, tabs) {
  tabs.forEach(tab => { const active = tab === selected; tab.setAttribute("aria-selected", String(active)); tab.tabIndex = active ? 0 : -1; });
  state.chartKey = selected.dataset.chart;
  renderChart();
}

function renderChart() {
  window.RiglosCharts?.render(document.getElementById("evolution-chart"), state.data.cronologia.series || [], state.chartKey);
}

function renderLoadError() {
  const message = location.protocol === "file:"
    ? "Para cargar los JSON locales, abre el proyecto mediante un servidor local. Consulta el README para ver el comando más sencillo."
    : "No se pudieron cargar los archivos de datos. Comprueba que todos los JSON sean válidos.";
  document.getElementById("status-cards").innerHTML = `<article class="metric-card danger"><span class="metric-label">Error de carga</span><strong class="metric-value unavailable">${escapeHtml(message)}</strong></article>`;
  document.getElementById("map-status").textContent = message;
}

function normalizeDatum(datum, fallbackMeta = null) {
  if (datum && typeof datum === "object" && Object.prototype.hasOwnProperty.call(datum, "value")) return { value: datum.value, meta: datum.meta || fallbackMeta };
  return { value: datum ?? null, meta: fallbackMeta };
}

function displayValue(value, unit = "") { return value == null || value === "" ? "Sin actualización oficial" : `${typeof value === "number" ? new Intl.NumberFormat("es-ES").format(value) : value}${unit ? ` ${unit}` : ""}`; }
function formatNumber(value, suffix = "") { return value == null || value === "" ? null : `${new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 }).format(value)}${suffix}`; }
function formatDatum(value, suffix = "") { return value == null || value === "" ? "Sin dato" : typeof value === "number" ? formatNumber(value, suffix) : String(value); }

function setTime(id, iso, empty = "Pendiente de cargar") {
  const el = document.getElementById(id);
  if (!iso) { el.textContent = empty; el.removeAttribute("datetime"); return; }
  el.dateTime = iso; el.textContent = formatDate(iso);
}

function formatDate(iso) {
  if (!iso) return "Sin actualización";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return escapeHtml(String(iso));
  const hasTime = String(iso).includes("T");
  return new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", ...(hasTime ? { timeStyle: "short" } : {}), timeZone: "Europe/Madrid" }).format(date);
}

function sourceBlock(meta, inline = false) {
  if (!meta?.fuente) return inline ? `<span>Sin fuente oficial incorporada · ${badge("sin_actualizacion")}</span>` : `<div class="metric-source">${badge("sin_actualizacion")}<time>Sin fuente oficial incorporada</time></div>`;
  const inner = `${sourceLink(meta.fuente)}<time datetime="${escapeAttr(meta.fecha_hora || "")}">Actualizado: ${formatDate(meta.fecha_hora)}</time>${badge(meta.fiabilidad || "oficial")}`;
  return inline ? inner : `<div class="metric-source">${inner}</div>`;
}

function sourceLink(source) {
  if (!source) return "Fuente sin especificar";
  const name = escapeHtml(source.nombre || "Fuente oficial");
  return source.url ? `<a href="${escapeAttr(source.url)}" target="_blank" rel="noopener noreferrer">${name} <span aria-hidden="true">↗</span></a>` : name;
}

function badge(value) {
  const key = String(value || "sin_actualizacion").toLowerCase();
  const mapping = { oficial: ["official", "Oficial"], provisional: ["provisional", "Provisional"], sin_actualizacion: ["stale", "Sin actualización"] };
  const [className, label] = mapping[key] || mapping.sin_actualizacion;
  return `<span class="badge ${className}">${label}</span>`;
}

function slug(value) { return String(value || "sin-actualizacion").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[char]); }
function escapeAttr(value) { return escapeHtml(value).replace(/`/g, "&#96;"); }
