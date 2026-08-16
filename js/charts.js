"use strict";

window.RiglosCharts = (() => {
  const config = {
    superficie_ha: { label: "Superficie", unit: "ha" },
    perimetro_consolidado_pct: { label: "Perímetro consolidado", unit: "%" },
    precipitacion_mm: { label: "Precipitación", unit: "mm" }
  };

  function render(container, series, key) {
    const valid = (series || []).map(item => ({ date: new Date(item.fecha), value: item[key] })).filter(item => !Number.isNaN(item.date.getTime()) && item.value != null && Number.isFinite(Number(item.value)));
    if (!valid.length) {
      container.innerHTML = `<div class="chart-empty"><div><strong>Sin datos oficiales para ${config[key].label.toLowerCase()}</strong><br><span>La gráfica aparecerá al añadir valores al archivo de cronología.</span></div></div>`;
      return;
    }
    const width = 1000, height = 330, left = 72, right = 30, top = 24, bottom = 58;
    const plotW = width - left - right, plotH = height - top - bottom;
    const values = valid.map(d => Number(d.value));
    const min = Math.min(0, ...values), maxRaw = Math.max(...values), max = maxRaw === min ? min + 1 : maxRaw;
    const dates = valid.map(d => d.date.getTime()), minDate = Math.min(...dates), maxDateRaw = Math.max(...dates), maxDate = maxDateRaw === minDate ? minDate + 86400000 : maxDateRaw;
    const x = date => left + ((date.getTime() - minDate) / (maxDate - minDate)) * plotW;
    const y = value => top + plotH - ((Number(value) - min) / (max - min)) * plotH;
    let grids = "", labels = "";
    for (let i = 0; i <= 4; i++) {
      const gy = top + (plotH / 4) * i;
      const val = max - ((max - min) / 4) * i;
      grids += `<line class="chart-grid" x1="${left}" y1="${gy}" x2="${width-right}" y2="${gy}" />`;
      labels += `<text class="chart-axis" x="${left-12}" y="${gy+4}" text-anchor="end">${format(val)}</text>`;
    }
    const segments = buildSegments(series, key).map(segment => segment.filter(item => item[key] != null).map(item => `${x(new Date(item.fecha))},${y(item[key])}`).join(" ")).filter(Boolean);
    const paths = segments.map(points => `<polyline class="chart-line" points="${points}" />`).join("");
    const points = valid.map(item => `<circle class="chart-point" cx="${x(item.date)}" cy="${y(item.value)}" r="5"><title>${formatDate(item.date)}: ${format(item.value)} ${config[key].unit}</title></circle>`).join("");
    const xLabels = valid.map((item, index) => (index === 0 || index === valid.length - 1 || index === Math.floor(valid.length/2)) ? `<text class="chart-axis" x="${x(item.date)}" y="${height-20}" text-anchor="middle">${formatDate(item.date)}</text>` : "").join("");
    container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="chart-title chart-desc"><title id="chart-title">Evolución de ${config[key].label.toLowerCase()}</title><desc id="chart-desc">${valid.length} valores oficiales representados. Los datos ausentes no se interpolan.</desc>${grids}${labels}${paths}${points}${xLabels}<text class="chart-axis" x="16" y="18">${config[key].unit}</text></svg>`;
  }

  function buildSegments(series, key) {
    const segments = []; let current = [];
    (series || []).forEach(item => {
      if (item[key] == null) { if (current.length) segments.push(current); current = []; }
      else current.push(item);
    });
    if (current.length) segments.push(current);
    return segments;
  }
  const format = value => new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 }).format(value);
  const formatDate = date => new Intl.DateTimeFormat("es-ES", { day: "2-digit", month: "short" }).format(date);
  return { render };
})();
