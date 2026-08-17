"use strict";

window.RiglosMap = (() => {
  const center = [42.34946, -0.72596];

  async function init(data) {
    const status = document.getElementById("map-status");
    if (typeof L === "undefined") { status.textContent = "Leaflet no está disponible. Comprueba la conexión o instala la biblioteca localmente."; return; }
    const map = L.map("map", { center, zoom: 10, zoomControl: true, scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' }).addTo(map);

    const effis = L.tileLayer.wms("https://maps.effis.emergency.copernicus.eu/effis", {
      layers: "modis.ba.poly",
      format: "image/png",
      transparent: true,
      time: new Date().toISOString().slice(0, 10),
      attribution: '<a href="https://forest-fire.emergency.copernicus.eu/" target="_blank" rel="noopener noreferrer">EFFIS / Copernicus</a>'
    });

    const layers = {
      "Perímetro del incendio": L.featureGroup(),
      "Espacio protegido": L.featureGroup(),
      "Poblaciones evacuadas": L.featureGroup(),
      "Carreteras cortadas": L.featureGroup(),
      "Estaciones meteorológicas": L.featureGroup(),
      "Área quemada satelital EFFIS (diaria)": effis,
      "Focos térmicos (preparado)": L.featureGroup(),
      "Precipitación (preparado)": L.featureGroup(),
      "Perímetros históricos (preparado)": L.featureGroup()
    };

    const officialBounds = await addGeoJson("data/perimetro.geojson", layers["Perímetro del incendio"], { color: "#a53d34", weight: 3, fillOpacity: .16 });
    await addGeoJson("data/espacios-protegidos.geojson", layers["Espacio protegido"], { color: "#397454", weight: 2, fillColor: "#67a47d", fillOpacity: .12 });
    addMarkers(data.evacuaciones?.registros, layers["Poblaciones evacuadas"], "evacuated", item => `${item.poblacion}: ${item.estado}`);
    addMarkers(data.carreteras?.registros, layers["Carreteras cortadas"], "road", item => `${item.carretera}: ${item.estado}`);
    addMarkers(data.meteo?.estaciones, layers["Estaciones meteorológicas"], "station", item => stationLabel(item, data.meteo));
    ["Perímetro del incendio", "Espacio protegido", "Poblaciones evacuadas", "Carreteras cortadas", "Estaciones meteorológicas"].forEach(name => layers[name].addTo(map));
    effis.addTo(map);
    L.control.layers({}, layers, { collapsed: window.innerWidth < 720 }).addTo(map);
    L.control.scale({ imperial: false }).addTo(map);
    if (officialBounds?.isValid()) map.fitBounds(officialBounds, { padding: [24, 24], maxZoom: 12 });
    status.textContent = "ICEARAGON: perímetro oficial si está publicado · EFFIS: área quemada satelital diaria.";
    const resizeMap = () => map.invalidateSize({ pan: false });
    requestAnimationFrame(resizeMap);
    setTimeout(resizeMap, 250);
    window.addEventListener("resize", resizeMap, { passive: true });
    if ("ResizeObserver" in window) new ResizeObserver(resizeMap).observe(document.getElementById("map"));
  }

  async function addGeoJson(url, group, style) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) return null;
      const geojson = await response.json();
      const layer = L.geoJSON(geojson, { style, onEachFeature: (feature, itemLayer) => itemLayer.bindPopup(featurePopup(feature, geojson.metadata)) }).addTo(group);
      if (url.includes("perimetro")) document.getElementById("perimeter-note").textContent = geojson.metadata?.aviso || (geojson.features?.length ? "Capa oficial incorporada." : "No hay un GeoJSON oficial incorporado.");
      return layer.getBounds();
    } catch (error) { console.warn(`No se pudo cargar ${url}`, error); return null; }
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
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[char]); }
  return { init };
})();
