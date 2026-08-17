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
    const effisLive = L.tileLayer.wms(effisUrl, {
      layers: "effis.nrt.ba.poly",
      format: "image/png",
      transparent: true,
      time: today,
      attribution: '<a href="https://forest-fire.emergency.copernicus.eu/" target="_blank" rel="noopener noreferrer">EFFIS / Copernicus</a>'
    });
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
      "EFFIS en directo (respaldo)": effisLive,
      "Focos térmicos VIIRS (hoy)": viirsHotspots,
      "Precipitación (preparado)": L.featureGroup(),
      "Perímetros históricos (preparado)": L.featureGroup()
    };

    const official = await addGeoJson("data/perimetro.geojson", layers["Perímetro oficial ICEARAGON"], { color: "#a53d34", weight: 3, fillOpacity: .16 });
    const approximate = await addGeoJson("data/perimetro-aproximado.geojson", layers["Área quemada aproximada EFFIS"], { color: "#d97706", weight: 3, dashArray: "9 7", fillColor: "#f59e0b", fillOpacity: .18 });
    await addGeoJson("data/espacios-protegidos.geojson", layers["Espacio protegido"], { color: "#397454", weight: 2, fillColor: "#67a47d", fillOpacity: .12 });
    addMarkers(data.evacuaciones?.registros, layers["Poblaciones evacuadas"], "evacuated", item => `${item.poblacion}: ${item.estado}`);
    addMarkers(data.carreteras?.registros, layers["Carreteras cortadas"], "road", item => `${item.carretera}: ${item.estado}`);
    addMarkers(data.meteo?.estaciones, layers["Estaciones meteorológicas"], "station", item => stationLabel(item, data.meteo));
    ["Perímetro oficial ICEARAGON", "Área quemada aproximada EFFIS", "Espacio protegido", "Poblaciones evacuadas", "Carreteras cortadas", "Estaciones meteorológicas"].forEach(name => layers[name].addTo(map));
    viirsHotspots.addTo(map);
    L.control.layers({}, layers, { collapsed: window.innerWidth < 720 }).addTo(map);
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
      const layer = L.geoJSON(geojson, { style, onEachFeature: (feature, itemLayer) => itemLayer.bindPopup(featurePopup(feature, geojson.metadata)) }).addTo(group);
      return { bounds: layer.getBounds(), geojson };
    } catch (error) { console.warn(`No se pudo cargar ${url}`, error); return { bounds: null, geojson: null }; }
  }

  function updatePerimeterStatus(official, approximate, status) {
    const note = document.getElementById("perimeter-note");
    if (official?.features?.length) {
      note.textContent = official.metadata?.aviso || "Perímetro oficial incorporado desde ICEARAGON.";
      status.textContent = "Línea roja: perímetro oficial · puntos: focos térmicos VIIRS del día actual.";
      return;
    }
    if (approximate?.features?.length) {
      const metadata = approximate.metadata || {};
      const area = metadata.superficie_ha == null ? "" : ` (${formatNumber(metadata.superficie_ha)} ha)`;
      const date = metadata.fecha_hora ? `, observación ${formatDate(metadata.fecha_hora)}` : "";
      note.textContent = `Área quemada aproximada EFFIS${area}${date}. No equivale al perímetro operativo.`;
      status.textContent = "Línea naranja discontinua: estimación satelital EFFIS · puntos: focos térmicos VIIRS del día actual.";
      return;
    }
    note.textContent = "Todavía no hay geometría oficial ni satelital incorporada.";
    status.textContent = "Sin geometría disponible · los focos térmicos VIIRS se consultan directamente a EFFIS.";
  }

  function featurePopup(feature, metadata) {
    const properties = feature.properties || {};
    const name = properties.nombre || "Perímetro del incendio";
    const area = properties.sup_total ?? properties.superficie_ha;
    const date = properties.fecha_mod || metadata?.fecha_hora;
    return `<strong>${escapeHtml(name)}</strong>${area != null ? `<br>${escapeHtml(new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 }).format(area))} ha` : ""}${date ? `<br>Actualizado: ${escapeHtml(new Date(date).toLocaleString("es-ES"))}` : ""}`;
  }

  function stationLabel(item, meteo) {
    const observation = meteo?.observacion;
    const isObserved = observation?.meta?.estacion?.idema === item.idema;
    const parts = [item.nombre];
    if (item.distancia_capital_municipal_km != null) parts.push(`${new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 }).format(item.distancia_capital_municipal_km)} km de la capital municipal`);
    if (isObserved && observation.temperatura_c?.value != null) parts.push(`${observation.temperatura_c.value} °C`);
    if (isObserved && observation.viento_kmh?.value != null) parts.push(`viento ${observation.viento_kmh.value} km/h`);
    return parts.join(" · ");
  }

  function addMarkers(records = [], group, type, label) {
    records.filter(item => Array.isArray(item.coordenadas) && item.coordenadas.length === 2).forEach(item => {
      const icon = L.divIcon({ className: "", html: `<span class="map-marker ${type}" aria-hidden="true">${type === "road" ? "!" : type === "station" ? "M" : "•"}</span>`, iconSize: [30,30], iconAnchor: [15,15] });
      L.marker(item.coordenadas, { icon, title: label(item) }).bindPopup(escapeHtml(label(item))).addTo(group);
    });
  }
  function formatNumber(value) { return new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 }).format(value); }
  function formatDate(value) { return new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Madrid" }).format(new Date(value)); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[char]); }
  return { init };
})();
