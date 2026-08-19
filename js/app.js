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
  renderCecopiReport();
  renderSummary();
  renderMapSummary();
  renderEvacuations();
  renderRoads();
  renderWeather();
  renderTimeline();
  renderSources();
  setupChartTabs();
  renderChart();
}

function renderCecopiReport() {
  const report = state.data.estado.ultimo_informe_cecopi;
  const link = document.getElementById("cecopi-report");
  if (!link || !report?.url || !report?.fecha_hora) return;
  link.href = report.url;
  link.title = report.titulo || "Último informe oficial de CECOPI";
  document.getElementById("cecopi-report-date").textContent = formatDate(report.fecha_hora);
  link.hidden = false;
}

function renderMapSummary() {
  const e = state.data.estado;
  const roads = state.data.carreteras.registros || [];
  const perimeter = normalizeDatum(e.perimetro_consolidado_pct);
  const lastPercentage = normalizeDatum(e.perimetro_consolidado_ultimo_pct);
  const lastLength = normalizeDatum(e.perimetro_longitud_ultima_km);
  const secondaryLength = normalizeDatum(e.perimetro_longitud_secundaria_km);
  const values = [
    ["Estado", e.estado?.value ?? "—"],
    ["Superficie", e.superficie_ha?.value == null ? "—" : `${formatNumber(e.superficie_ha.value)} ha`],
    ["Consolidado vigente", perimeter.value == null ? "No publicado" : `${formatNumber(perimeter.value)} %`],
    ["Último % explícito", lastPercentage.value == null ? "—" : `${formatNumber(lastPercentage.value)} % · ${formatDate(lastPercentage.meta?.fecha_hora)}`],
    ["Perímetro aprox.", lastLength.value == null ? "—" : `≈ ${formatNumber(lastLength.value)} km · ${formatDate(lastLength.meta?.fecha_hora)}`],
    ["Evacuados", e.nucleos_evacuados?.value == null ? "—" : `${formatNumber(e.nucleos_evacuados.value)} núcleos`],
    ["Cortes", `${roads.length} vías`]
  ];
  document.getElementById("map-summary").innerHTML = values.map(([label, value]) => {
    const fullText = `${label}: ${value}`;
    return `<div title="${escapeHtml(fullText)}"><span>${escapeHtml(label)}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`;
  }).join("");
  document.getElementById("perimeter-history").innerHTML = `<strong>Cifras oficiales de perímetro:</strong> ${historicalPerimeterLinks(lastPercentage, lastLength)}. La longitud es aproximada y el porcentaje es una referencia histórica fechada.${secondaryLength.value == null ? "" : ` <strong>Referencia periodística:</strong> ${historicalDatumLink(`≈ ${formatNumber(secondaryLength.value)} km`, secondaryLength.meta)}; no incorporada a la serie oficial.`}`;
  const traced = roads.filter(road => Array.isArray(road.trazado) && road.trazado.length > 1).length;
  const missing = roads.length - traced;
  document.getElementById("road-map-note").textContent = missing
    ? `${traced} de ${roads.length} cortes tienen un tramo cartográfico oficial visible en violeta. ${missing} no puede representarse como línea; consulta su marcador para conocer el motivo.`
    : `Los ${roads.length} cortes disponen de un tramo cartográfico oficial visible en violeta.`;
}

function renderDates() {
  setTime("panel-checked", state.data.estado.ultima_comprobacion_panel);
  setTime("official-updated", state.data.estado.ultima_actualizacion_oficial, "Sin actualización oficial");
}

function renderSummary() {
  const e = state.data.estado;
  const m = state.data.meteo;
  const cards = [
    metricCard("Último estado explícitamente publicado", e.estado, "", e.estado_meta, String(e.estado?.value || "").toLowerCase() === "activo" ? "danger" : ""),
    metricCard("Superficie", e.superficie_ha, "ha", e.superficie_ha?.meta),
    perimeterCard(e),
    evacuationsCard(e),
    resourcesCard(e),
    weatherCard(m)
  ];
  document.getElementById("status-cards").innerHTML = cards.join("");
}

function perimeterCard(e) {
  const current = normalizeDatum(e.perimetro_consolidado_pct);
  const lastPercentage = normalizeDatum(e.perimetro_consolidado_ultimo_pct);
  const lastLength = normalizeDatum(e.perimetro_longitud_ultima_km);
  const secondaryLength = normalizeDatum(e.perimetro_longitud_secundaria_km);
  const currentValue = lastLength.value == null ? "Sin cifra vigente" : `≈ ${formatNumber(lastLength.value)} km`;
  const consolidatedValue = current.value == null ? "No publicado en el último parte" : `${formatNumber(current.value)} % consolidado`;
  return `<article class="metric-card perimeter-card">
    <span class="metric-label">Perímetro aproximado</span>
    <strong class="metric-value ${lastLength.value == null ? "unavailable" : ""}">${escapeHtml(currentValue)}</strong>
    <div class="perimeter-history"><span>Consolidación</span>${escapeHtml(consolidatedValue)}${lastPercentage.value == null ? "" : ` · ${historicalDatumLink(`${formatNumber(lastPercentage.value)} % (último explícito)`, lastPercentage.meta)}`}</div>
    ${secondaryPerimeterReference(secondaryLength)}
    ${sourceBlock(lastLength.meta || current.meta)}
  </article>`;
}

function secondaryPerimeterReference(datum) {
  if (datum.value == null) return "";
  return `<div class="secondary-reference">${badge("fuente_secundaria")}<span>${historicalDatumLink(`≈ ${formatNumber(datum.value)} km difundidos por Cadena SER`, datum.meta)}</span><small>Referencia periodística vinculada a entrevistas con responsables del Gobierno de Aragón; no publicada en un parte oficial ni incorporada a la gráfica.</small></div>`;
}

function historicalPerimeterLinks(lastPercentage, lastLength) {
  const items = [];
  if (lastLength.value != null) items.push(historicalDatumLink(`≈ ${formatNumber(lastLength.value)} km de perímetro`, lastLength.meta));
  if (lastPercentage.value != null) items.push(historicalDatumLink(`${formatNumber(lastPercentage.value)} % consolidado (histórico)`, lastPercentage.meta));
  return items.length ? items.join(" · ") : "sin referencias anteriores incorporadas";
}

function historicalDatumLink(label, meta) {
  const text = `${label} (${formatDate(meta?.fecha_hora)})`;
  return meta?.fuente?.url
    ? `<a class="perimeter-history-link" href="${escapeAttr(meta.fuente.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(text)} <span aria-hidden="true">↗</span></a>`
    : escapeHtml(text);
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
  return `<article class="metric-card evacuation-card"><span class="metric-label">Evacuaciones</span>${main}${sourceBlock(latestMeta(nuclei.meta, people.meta))}</article>`;
}

function resourcesCard(e) {
  const deployment = e.efectivos_desplegados;
  if (!deployment?.meta) {
    return `<article class="metric-card resources-card"><span class="metric-label">Efectivos y medios del operativo</span><strong class="metric-value unavailable">Sin desglose oficial incorporado</strong>${sourceBlock(null)}</article>`;
  }
  const personnel = deployment.personal_jornada_aprox == null ? "—" : `≈ ${formatNumber(deployment.personal_jornada_aprox)}`;
  const aircraft = deployment.medios_aereos_jornada == null ? "—" : formatNumber(deployment.medios_aereos_jornada);
  const personnelMeta = deployment.personal_jornada_meta || deployment.meta;
  const aircraftMeta = deployment.medios_aereos_meta || deployment.meta;
  const personnelDate = deployment.personal_jornada_aprox == null || !personnelMeta?.fecha_hora ? "" : `<small>Dato explícito: ${formatDate(personnelMeta.fecha_hora)}</small>`;
  const aircraftDate = deployment.medios_aereos_jornada == null || !aircraftMeta?.fecha_hora ? "" : `<small>Dato explícito: ${formatDate(aircraftMeta.fecha_hora)}</small>`;
  const groups = Array.isArray(deployment.grupos) ? deployment.grupos : [];
  const details = groups.length
    ? `<details class="resources-details"><summary>Ver desglose del ${escapeHtml(String(deployment.desglose_contexto || "operativo").toLowerCase())}</summary><div class="resources-groups">${groups.map(group => `<section><h3>${escapeHtml(group.organismo)}</h3><ul>${(group.medios || []).map(item => `<li>${item.cantidad == null ? "" : `<strong>${escapeHtml(formatNumber(item.cantidad))}</strong> `}${escapeHtml(item.concepto)}</li>`).join("")}</ul></section>`).join("")}</div></details>`
    : `<p class="resources-empty">El parte no publica un desglose por organismos.</p>`;
  const review = deployment.revision_ultimo_parte;
  const retainedLabels = (review?.campos_mantenidos || []).map(field => field === "personal_jornada_aprox" ? "personal" : "medios aéreos");
  const reviewMessage = !review?.fuente ? "" : review.sin_cambios_notificados
    ? "El último parte no comunica cambios en estas cifras; se mantienen los últimos valores explícitos."
    : retainedLabels.length
      ? `El último parte actualiza parcialmente el despliegue y no publica una nueva cifra de ${retainedLabels.join(" ni ")}; se conserva el último valor explícito.`
      : "Las cifras-resumen proceden del último parte revisado.";
  const reviewBlock = review?.fuente
    ? `<p class="resources-review"><strong>Último parte revisado: ${formatDate(review.fecha_hora)}</strong><span>${escapeHtml(reviewMessage)}</span></p><div class="metric-source resources-source">${sourceLink(review.fuente)}<time datetime="${escapeAttr(review.fecha_hora || "")}">Comprobado frente al último parte oficial</time>${badge(review.fiabilidad || "oficial")}</div>`
    : sourceBlock(deployment.meta);
  return `<article class="metric-card resources-card">
    <span class="metric-label">Efectivos y medios del operativo</span>
    <div class="resources-brief"><div><span>Personal durante la jornada</span><strong>${escapeHtml(personnel)}</strong>${personnelDate}</div><div><span>Medios aéreos durante la jornada</span><strong>${escapeHtml(aircraft)}</strong>${aircraftDate}</div></div>
    <p class="resources-context">${escapeHtml(deployment.resumen_contexto || "Periodo indicado en el parte oficial")}. Las cifras no representan necesariamente medios actuando de forma simultánea.</p>
    ${details}
    ${reviewBlock}
  </article>`;
}

function weatherCard(m) {
  const o = m.observacion || {};
  const values = [
    ["Viento", formatNumber(o.viento_kmh?.value, " km/h")],
    ["Dirección", o.direccion?.value],
    ["Racha máx. hoy", formatNumber(o.racha_maxima_desde_00_kmh?.value, " km/h")],
    ["Humedad", formatNumber(o.humedad_relativa_pct?.value, " %")],
    ["Lluvia desde 00 h", formatNumber(o.precipitacion_desde_00_mm?.value, " mm")]
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
  document.getElementById("roads-list").innerHTML = roads.length ? roads.map(road => {
    const direction = road.sentido ? `<dt>Sentido</dt><dd>${escapeHtml(road.sentido)}</dd>` : "";
    return `<article class="road-card ${slug(road.estado)}">
      <div class="road-name"><strong>${escapeHtml(road.carretera)}</strong><span class="status-pill ${slug(road.estado)}">${escapeHtml(road.estado)}</span></div>
      <dl><dt>Tramo</dt><dd>${escapeHtml(road.tramo || "Sin detalle oficial")}</dd>${direction}<dt>Actualización</dt><dd>${formatDate(road.fecha_hora)}</dd></dl>
      <div class="source-line">${sourceLink(road.fuente)}</div>
    </article>`;
  }).join("") : `<p class="empty-state"><strong>Sin cortes oficiales incorporados</strong><br>Consulta siempre el mapa de tráfico de la DGT antes de desplazarte.</p>`;
}

function renderWeather() {
  renderWeatherGroup("forecast-data", "forecast-source", state.data.meteo.prevision, [
    ["Temperatura máxima", "temperatura_maxima_c", " °C"], ["Temperatura mínima", "temperatura_minima_c", " °C"],
    ["Humedad mínima", "humedad_minima_pct", " %"], ["Humedad máxima", "humedad_maxima_pct", " %"],
    ["Viento máximo", "viento_maximo_kmh", " km/h"], ["Dirección al máximo", "direccion_viento_maximo", ""],
    ["Racha máxima prevista", "racha_maxima_kmh", " km/h"], ["Prob. precipitación", "prob_precipitacion_pct", " %"],
    ["Precipitación prevista", "precipitacion_total_mm", " mm"], ["Prob. tormenta", "prob_tormenta_pct", " %"],
    ["Estado del cielo", "cielo", ""]
  ]);
  renderWeatherGroup("observation-data", "observation-source", state.data.meteo.observacion, [
    ["Temperatura", "temperatura_c", " °C"], ["Humedad", "humedad_relativa_pct", " %"],
    ["Viento", "viento_kmh", " km/h"], ["Dirección", "direccion", ""],
    ["Racha actual", "racha_actual_kmh", " km/h"], ["Racha máxima hoy", "racha_maxima_desde_00_kmh", " km/h"],
    ["Lluvia última hora", "precipitacion_ultima_hora_mm", " mm"], ["Lluvia desde 00 h", "precipitacion_desde_00_mm", " mm"]
  ]);
  renderHourlyForecast(state.data.meteo.prevision?.horaria || []);
  const station = state.data.meteo.observacion?.meta?.estacion;
  document.getElementById("observation-context").innerHTML = station
    ? `<strong>${escapeHtml(station.nombre)}</strong><span>Estación AEMET ${escapeHtml(station.idema)} · ${escapeHtml(formatNumber(station.altitud_m, " m"))} de altitud</span><small>La estación es una referencia meteorológica cercana; no mide necesariamente las condiciones en todo el incendio.</small>`
    : "";
  const records = [...(state.data.meteo.precipitacion_diaria || [])].sort((a, b) => b.fecha.localeCompare(a.fecha) || a.estacion.localeCompare(b.estacion));
  document.getElementById("rain-records").innerHTML = records.length ? records.map(r => `<div class="rain-record"><div><span>Fecha</span><strong>${formatDate(r.fecha)}</strong></div><div><span>Estación</span><strong>${escapeHtml(r.estacion)}</strong></div><div><span>Precipitación 00–24 h</span><strong>${formatNumber(r.precipitacion_mm, " mm") ?? "Sin dato"}</strong></div><div><span>Estado</span><strong>${escapeHtml(r.estado || (r.completo ? "Día completo" : "Día en curso"))}</strong></div></div>`).join("") : `<p class="empty-state">AEMET no ha devuelto resúmenes diarios utilizables para las estaciones seleccionadas.</p>`;
}

function renderHourlyForecast(records) {
  const target = document.getElementById("forecast-hourly");
  target.innerHTML = records.length ? `<p class="hourly-title">Evolución horaria</p><div class="hourly-list">${records.map(record => `<div class="hourly-item">
    <time>${escapeHtml(record.hora)}</time>
    <strong>${escapeHtml(formatNumber(record.temperatura_c, " °C") ?? "—")}</strong>
    <span>${escapeHtml(record.direccion || "—")} · ${escapeHtml(formatNumber(record.viento_kmh, " km/h") ?? "—")}</span>
    <small>Racha ${escapeHtml(formatNumber(record.racha_kmh, " km/h") ?? "—")} · HR ${escapeHtml(formatNumber(record.humedad_pct, " %") ?? "—")}</small>
  </div>`).join("")}</div>` : "";
}

function renderWeatherGroup(dataId, sourceId, group, fields) {
  document.getElementById(dataId).innerHTML = fields.map(([label,key,unit]) => {
    const datum = group?.[key];
    const period = datum?.periodo ? `<small>${escapeHtml(datum.periodo)}</small>` : "";
    return `<div class="weather-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(formatDatum(datum?.value, unit))}</strong>${period}</div>`;
  }).join("");
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
  const secondaryLength = normalizeDatum(state.data.estado.perimetro_longitud_secundaria_km);
  let series = state.chartKey === "precipitacion_mm"
    ? state.data.meteo.precipitacion_diaria || []
    : state.data.cronologia.series || [];
  if (state.chartKey === "perimetro_longitud_km") {
    if (secondaryLength.value != null && secondaryLength.meta?.fecha_hora) {
      series = [...series, {
        fecha: secondaryLength.meta.fecha_hora,
        perimetro_longitud_km: secondaryLength.value,
        perimetro_longitud_meta: secondaryLength.meta,
        perimetro_longitud_secundaria: true
      }].sort((a, b) => new Date(a.fecha) - new Date(b.fecha));
    }
  }
  window.RiglosCharts?.render(document.getElementById("evolution-chart"), series, state.chartKey);
  const notes = {
    superficie_ha: "Las superficies son estimaciones publicadas en partes fechados; la línea permite ver la evolución de esas cifras.",
    perimetro_consolidado_pct: "Cada punto es un porcentaje explícito, fechado y publicado por una fuente oficial. La línea une todos los puntos oficiales disponibles sin inventar valores intermedios; si solo existe uno, se muestra aislado.",
    perimetro_longitud_km: secondaryLength.value != null
      ? "La línea continua une las longitudes publicadas en partes oficiales. El tramo discontinuo identifica una referencia periodística y no la presenta como dato oficial."
      : "La línea une todas las longitudes explícitas localizadas en partes oficiales: 41,9 km, 58 km y 100 km. La serie se actualizará automáticamente cuando un nuevo parte publique otra longitud.",
    precipitacion_mm: "Precipitación diaria 00–24 h registrada por AEMET en Jaca y Bailo-Puyalto. El último día puede estar incompleto y se actualiza cada 30 minutos."
  };
  document.getElementById("chart-note").textContent = notes[state.chartKey];
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

function latestMeta(...metas) {
  return metas.filter(Boolean).sort((a, b) => String(b.fecha_hora || "").localeCompare(String(a.fecha_hora || "")))[0] || null;
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
  if (!meta?.fuente) return inline ? `<span>No publicado en las fuentes consultadas · ${badge("sin_actualizacion")}</span>` : `<div class="metric-source">${badge("sin_actualizacion")}<time>No publicado en las fuentes consultadas</time></div>`;
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
  const mapping = { oficial: ["official", "Oficial"], provisional: ["provisional", "Provisional"], historico: ["manual", "Dato histórico"], fuente_secundaria: ["secondary", "Fuente periodística"], sin_actualizacion: ["stale", "No publicado"] };
  const [className, label] = mapping[key] || mapping.sin_actualizacion;
  return `<span class="badge ${className}">${label}</span>`;
}

function slug(value) { return String(value || "sin-actualizacion").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[char]); }
function escapeAttr(value) { return escapeHtml(value).replace(/`/g, "&#96;"); }
