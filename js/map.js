"use strict";

window.RiglosMap = (() => {
  const center = [42.34946, -0.72596];

  async function init(data) {
    const status = document.getElementById("map-status");
    if (typeof L === "undefined") { status.textContent = "Leaflet no está disponible. Comprueba la conexión o instala la biblioteca localmente."; return; }
    const map = L.map("map", { center, zoom: 10, zoomControl: true, scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' }).addTo(map);

    const layers = {
      "Perímetro del incendio": L.featureGroup(),
      "Espacio protegido": L.featureGroup(),
      "Poblaciones evacuadas": L.featureGroup(),
      "Carreteras cortadas": L.featureGroup(),
      "Estaciones meteorológicas": L.featureGroup(),
      "Focos térmicos (preparado)": L.featureGroup(),
      "Precipitación (preparado)": L.featureGroup(),
      "Perímetros históricos (preparado)": L.featureGroup()
    };

    await addGeoJson("data/perimetro.geojson", layers["Perímetro del incendio"], { color: "#a53d34", weight: 3, fillOpacity: .16 });
    await addGeoJson("data/espacios-protegidos.geojson", layers["Espacio protegido"], { color: "#397454", weight: 2, fillColor: "#67a47d", fillOpacity: .12 });
    addMarkers(data.evacuaciones?.registros, layers["Poblaciones evacuadas"], "evacuated", item => `${item.poblacion}: ${item.estado}`);
    addMarkers(data.carreteras?.registros, layers["Carreteras cortadas"], "road", item => `${item.carretera}: ${item.estado}`);
    addMarkers(data.meteo?.estaciones, layers["Estaciones meteorológicas"], "station", item => item.nombre);
    ["Perímetro del incendio", "Espacio protegido", "Poblaciones evacuadas", "Carreteras cortadas", "Estaciones meteorológicas"].forEach(name => layers[name].addTo(map));
    L.control.layers({}, layers, { collapsed: window.innerWidth < 720 }).addTo(map);
    L.control.scale({ imperial: false }).addTo(map);
    status.textContent = "Mapa orientativo. Consulta siempre la cartografía y los avisos oficiales.";
    setTimeout(() => map.invalidateSize(), 0);
  }

  async function addGeoJson(url, group, style) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) return;
      const geojson = await response.json();
      L.geoJSON(geojson, { style, onEachFeature: (feature, layer) => feature.properties?.nombre && layer.bindPopup(escapeHtml(feature.properties.nombre)) }).addTo(group);
      if (url.includes("perimetro") && geojson.features?.length) document.getElementById("perimeter-note").textContent = geojson.metadata?.aviso || "Capa incorporada; consulta su procedencia en los metadatos.";
    } catch (error) { console.warn(`No se pudo cargar ${url}`, error); }
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
