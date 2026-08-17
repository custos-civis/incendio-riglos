"use strict";

window.RiglosMap = (() => {
  const center = [42.34946, -0.72596];

  async function init(data) {
    const status = document.getElementById("map-status");
    if (typeof L === "undefined") { status.textContent = "Leaflet no está disponible. Comprueba la conexión o instala la biblioteca localmente."; return; }
    const map = L.map("map", { center, zoom: 10, zoomControl: true, scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' }).addTo(map);

    const effisUrl = "https://maps.effis.emergency.copernicus.eu/effis";
    const today = new Date().toISOString().slice(0, 10);
    const viirsHotspots = L.tileLayer.wms(effisUrl, {
      layers: "viirs.hs",
      format: "image/png",
      transparent: true,
      time: today,
      opacity: .9,
      attribution: '<a href="https://forest-fire.emergency.copernicus.eu/" target="_blank" rel="noopener noreferrer">VIIRS vía EFFIS / Copernicus</a>'
    });

    const layers = {
      "Perímetro oficial ICEARAGON": L.featureGroup(),
      "Área quemada aproximada EFFIS": L.featureGroup(),
      "Espacio protegido": L.featureGroup(),
      "Poblaciones evacuadas": L.featureGroup(),
      "Carreteras cortadas": L.featureGroup(),
      "Estaciones meteorológicas": L.featureGroup(),
      "Focos térmicos VIIRS (opcional)": viirsHotspots
    };

    const official = await addGeoJson("data/perimetro.geojson", layers["Perímetro oficial ICEARAGON"], { color: "#a53d34", weight: 3, fillOpacity: .16 });
    const approximate = await addGeoJson("data/perimetro-aproximado.geojson", layers["Área quemada aproximada EFFIS"], { color: "#d97706", weight: 3, dashArray: "9 7", fillColor: "#f59e0b", fillOpacity: .18 });
    await addGeoJson("data/espacios-protegidos.geojson", layers["Espacio protegido"], { color: "#397454", weight: 2, fillColor: "#67a47d", fillOpacity: .12 });
    addEvacuationMarkers(data.evacuaciones?.registros, layers["Poblaciones evacuadas"]);
    addMarkers(data.carreteras?.registros, layers["Carreteras cortadas"], "road", "!", roadPopup, item => `${item.carretera}: ${item.tramo}`);
    addMarkers(data.meteo?.estaciones, layers["Estaciones meteorológicas"], "station", "°", item => stationPopup(item, data.meteo), item => `Estación meteorológica AEMET: ${item.nombre}`);

    const defaultLayers = ["Perímetro oficial ICEARAGON", "Área quemada aproximada EFFIS", "Espacio protegido", "Poblaciones evacuadas", "Carreteras cortadas", "Estaciones meteorológicas"];
    defaultLayers.filter(name => hasContent(layers[name])).forEach(name => layers[name].addTo(map));
    const availableLayers = Object.fromEntries(Object.entries(layers).filter(([, layer]) => hasContent(layer)));
    L.control.layers({}, availableLayers, { collapsed: window.innerWidth < 720 }).addTo(map);
    L.control.scale({ imperial: false }).addTo(map);
    const visibleBounds = official.bounds?.isValid() ? official.bounds : approximate.bounds;
    if (visibleBounds?.isValid()) map.fitBounds(visibleBounds, { padding: [28, 28], maxZoom: 12 });
    updatePerimeterStatus(official.geojson, approximate.geojson, status);
    const resizeMap = () => map.invalidateSize({ pan: false });
    requestAnimationFrame(resizeMap);
    setTimeout(resizeMap, 250);
    window.addEventListener("resize", resizeMap, { passive: true });
    if ("ResizeObserver" in window) new ResizeObserver(resizeMap).observe(document.getElementById("map"));
  }

  async function addGeoJson(url, group, style) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) return { bounds: null, geojson: null };
      const geojson = await response.json();
      if (!Array.isArray(geojson.features) || geojson.features.length === 0) return { bounds: null, geojson };
      const layer = L.geoJSON(geojson, { style, onEachFeature: (feature, itemLayer) => itemLayer.bindPopup(featurePopup(feature, geojson.metadata)) }).addTo(group);
      return { bounds: layer.getBounds(), geojson };
    } catch (error) { console.warn(`No se pudo cargar ${url}`, error); return { bounds: null, geojson: null }; }
  }

  function updatePerimeterStatus(official, approximate, status) {
    const note = document.getElementById("perimeter-note");
    if (official?.features?.length) {
      note.textContent = official.metadata?.aviso || "Perímetro oficial incorporado desde ICEARAGON.";
      status.textContent = "Línea roja: perímetro oficial · los focos térmicos VIIRS se pueden activar en el control de capas.";
      return;
    }
    if (approximate?.features?.length) {
      const metadata = approximate.metadata || {};
      const area = metadata.superficie_ha == null ? "" : ` (${formatNumber(metadata.superficie_ha)} ha)`;
      const date = metadata.fecha_hora ? `, observación ${formatDate(metadata.fecha_hora)}` : "";
      note.textContent = `Área quemada aproximada EFFIS${area}${date}. No equivale al perímetro operativo.`;
      status.textContent = "Línea naranja discontinua: estimación satelital EFFIS · los focos térmicos VIIRS se pueden activar en el control de capas.";
      return;
    }
    note.textContent = "Todavía no hay geometría oficial ni satelital incorporada.";
    status.textContent = "Sin geometría disponible · los focos térmicos VIIRS se pueden activar en el control de capas.";
  }

  function featurePopup(feature, metadata) {
    const properties = feature.properties || {};
    const name = properties.nombre || "Perímetro del incendio";
    const area = properties.sup_total ?? properties.superficie_ha;
    const date = properties.fecha_mod || metadata?.fecha_hora;
    return `<strong>${escapeHtml(name)}</strong>${area != null ? `<br>${escapeHtml(new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 }).format(area))} ha` : ""}${date ? `<br>Actualizado: ${escapeHtml(new Date(date).toLocaleString("es-ES"))}` : ""}`;
  }

  function stationPopup(item, meteo) {
    const observation = meteo?.observacion;
    const isObserved = observation?.meta?.estacion?.idema === item.idema;
    const readings = [];
    if (isObserved && observation.temperatura_c?.value != null) readings.push(`Temperatura: ${escapeHtml(observation.temperatura_c.value)} °C`);
    if (isObserved && observation.viento_kmh?.value != null) readings.push(`Viento: ${escapeHtml(observation.viento_kmh.value)} km/h`);
    const distance = item.distancia_capital_municipal_km == null ? "" : `<br><small>A unos ${escapeHtml(formatNumber(item.distancia_capital_municipal_km))} km de Riglos, capital del municipio.</small>`;
    return `<strong>Estación meteorológica AEMET</strong><br>${escapeHtml(item.nombre)}${distance}${readings.length ? `<br>${readings.join("<br>")}` : "<br>Sin observación reciente incorporada"}`;
  }

  function roadPopup(item) {
    const source = safeSourceLink(item.fuente);
    const direction = item.sentido ? `<br>Sentido: ${escapeHtml(item.sentido)}` : "";
    return `<strong>Carretera cortada: ${escapeHtml(item.carretera)}</strong><br>${escapeHtml(item.tramo)}${direction}<br><small>Marcador orientativo del tramo; no señala el punto exacto del corte. Confirma el estado en DGT o llamando al 011.</small>${source}`;
  }

  function evacuationPopup(items) {
    const rows = items.map(item => `<strong>${escapeHtml(item.poblacion)}</strong> · ${escapeHtml(item.estado)}`).join("<br>");
    const source = safeSourceLink(items[0]?.fuente);
    return `<strong>Evacuación oficial comunicada</strong><br>${rows}<br><small>El marcador identifica el núcleo o establecimiento, no un punto operativo.</small>${source}`;
  }

  function addEvacuationMarkers(records = [], group) {
    const grouped = new Map();
    records.filter(hasCoordinates).forEach(item => {
      const key = item.coordenadas.join(",");
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(item);
    });
    grouped.forEach(items => addMarker(items[0].coordenadas, group, "evacuated", "E", evacuationPopup(items), `Evacuación: ${items.map(item => item.poblacion).join(", ")}`));
  }

  function addMarkers(records = [], group, type, symbol, popup, title) {
    records.filter(item => Array.isArray(item.coordenadas) && item.coordenadas.length === 2).forEach(item => {
      addMarker(item.coordenadas, group, type, symbol, popup(item), title(item));
    });
  }

  function addMarker(coordinates, group, type, symbol, popup, title) {
    const icon = L.divIcon({ className: "", html: `<span class="map-marker ${type}" aria-hidden="true">${symbol}</span>`, iconSize: [30,30], iconAnchor: [15,15] });
    L.marker(coordinates, { icon, title }).bindPopup(popup).addTo(group);
  }

  function hasCoordinates(item) { return Array.isArray(item.coordenadas) && item.coordenadas.length === 2; }
  function hasContent(layer) { return !(layer instanceof L.FeatureGroup) || layer.getLayers().length > 0; }
  function safeSourceLink(source) {
    if (!source?.url || !/^https:\/\//.test(source.url)) return "";
    return `<br><a href="${escapeHtml(source.url)}" target="_blank" rel="noopener noreferrer">Fuente: ${escapeHtml(source.nombre || "publicación oficial")} ↗</a>`;
  }
  function formatNumber(value) { return new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 }).format(value); }
  function formatDate(value) { return new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Madrid" }).format(new Date(value)); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[char]); }
  return { init };
})();
