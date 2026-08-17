"use strict";

window.RiglosCharts = (() => {
  const config = {
    superficie_ha: { label: "Superficie", unit: "ha" },
    perimetro_consolidado_pct: { label: "Perímetro consolidado", unit: "%" },
    precipitacion_mm: { label: "Precipitación", unit: "mm" }
  };

  function render(container, series, key) {
    if (key === "precipitacion_mm") {
      renderPrecipitation(container, series || []);
      return;
    }
    renderSingle(container, series || [], key);
  }

  function renderSingle(container, series, key) {
    const valid = series.map(item => ({ ...item, date: new Date(item.fecha), value: item[key] }))
      .filter(item => !Number.isNaN(item.date.getTime()) && item.value != null && Number.isFinite(Number(item.value)));
    if (!valid.length) {
      empty(container, config[key].label.toLowerCase(), "La gráfica aparecerá cuando una publicación fechada ofrezca un valor explícito.");
      return;
    }
    const chart = chartGeometry(valid);
    const paths = buildSegments(series, key, key === "superficie_ha").map(segment => segment
      .filter(item => item[key] != null)
      .map(item => `${chart.x(new Date(item.fecha))},${chart.y(item[key])}`).join(" "))
      .filter(Boolean)
      .map(points => `<polyline class="chart-line" points="${points}" />`).join("");
    const points = valid.map(item => {
      const meta = item.perimetro_consolidado_meta;
      const source = meta?.fuente?.nombre ? ` · ${meta.fuente.nombre}` : "";
      const label = key === "perimetro_consolidado_pct"
        ? `<text class="chart-value" x="${chart.x(item.date)}" y="${chart.y(item.value) - 13}" text-anchor="middle">${format(item.value)} %</text>`
        : "";
      return `${label}<circle class="chart-point" cx="${chart.x(item.date)}" cy="${chart.y(item.value)}" r="5"><title>${formatDate(item.date)}: ${format(item.value)} ${config[key].unit}${source}</title></circle>`;
    }).join("");
    const description = key === "superficie_ha"
      ? `${valid.length} valores fechados representados. La línea une las cifras publicadas consecutivas y omite los registros sin superficie.`
      : `${valid.length} valores fechados representados. Los datos ausentes no se interpolan.`;
    container.innerHTML = svgFrame(chart, valid, config[key], paths + points, description);
  }

  function renderPrecipitation(container, records) {
    const dated = records.map(item => ({ ...item, date: new Date(`${item.fecha}T12:00:00`) }))
      .filter(item => !Number.isNaN(item.date.getTime()));
    const valid = dated
      .filter(item => !Number.isNaN(item.date.getTime()) && item.precipitacion_mm != null && Number.isFinite(Number(item.precipitacion_mm)));
    if (!valid.length) {
      empty(container, "precipitación", "AEMET no ha devuelto todavía resúmenes diarios utilizables para Jaca y Bailo-Puyalto.");
      return;
    }
    const chart = chartGeometry(valid.map(item => ({ date: item.date, value: item.precipitacion_mm })));
    const stationNames = [...new Set(dated.map(item => item.estacion))];
    const classes = ["bailo", "jaca"];
    const drawings = stationNames.map((station, stationIndex) => {
      const stationRecords = dated.filter(item => item.estacion === station).sort((a, b) => a.date - b.date);
      const items = stationRecords.filter(item => item.precipitacion_mm != null && Number.isFinite(Number(item.precipitacion_mm)));
      const segments = []; let current = [];
      stationRecords.forEach(item => {
        if (item.precipitacion_mm == null || !Number.isFinite(Number(item.precipitacion_mm))) {
          if (current.length) segments.push(current);
          current = [];
        } else {
          current.push(item);
        }
      });
      if (current.length) segments.push(current);
      const lines = segments.map(segment => `<polyline class="chart-line station-${classes[stationIndex]}" points="${segment.map(item => `${chart.x(item.date)},${chart.y(item.precipitacion_mm)}`).join(" ")}" />`).join("");
      const circles = items.map(item => `<circle class="chart-point station-${classes[stationIndex]}" cx="${chart.x(item.date)}" cy="${chart.y(item.precipitacion_mm)}" r="5"><title>${station} · ${formatDate(item.date)}: ${format(item.precipitacion_mm)} mm${item.completo ? "" : " (día en curso)"}</title></circle>`).join("");
      return lines + circles;
    }).join("");
    const legend = `<div class="chart-legend">${stationNames.map((name, index) => `<span><i class="station-${classes[index]}"></i>${escapeHtml(name)}</span>`).join("")}</div>`;
    container.innerHTML = legend + svgFrame(chart, valid.map(item => ({ date: item.date, value: item.precipitacion_mm })), config.precipitacion_mm, drawings, `${valid.length} registros diarios de ${stationNames.length} estaciones AEMET.`);
  }

  function chartGeometry(valid) {
    const width = 1000, height = 330, left = 72, right = 30, top = 30, bottom = 58;
    const plotW = width - left - right, plotH = height - top - bottom;
    const values = valid.map(item => Number(item.value));
    const min = 0, maxRaw = Math.max(...values), max = maxRaw === 0 ? 1 : Math.ceil(maxRaw * 1.15 * 10) / 10;
    const dates = valid.map(item => item.date.getTime());
    const minDate = Math.min(...dates), maxDateRaw = Math.max(...dates), maxDate = maxDateRaw === minDate ? minDate + 86400000 : maxDateRaw;
    return {
      width, height, left, right, top, plotH,
      x: date => left + ((date.getTime() - minDate) / (maxDate - minDate)) * plotW,
      y: value => top + plotH - ((Number(value) - min) / (max - min)) * plotH,
      min, max
    };
  }

  function svgFrame(chart, valid, cfg, drawings, description) {
    let grids = "", labels = "";
    for (let i = 0; i <= 4; i++) {
      const gy = chart.top + (chart.plotH / 4) * i;
      const value = chart.max - ((chart.max - chart.min) / 4) * i;
      grids += `<line class="chart-grid" x1="${chart.left}" y1="${gy}" x2="${chart.width-chart.right}" y2="${gy}" />`;
      labels += `<text class="chart-axis" x="${chart.left-12}" y="${gy+4}" text-anchor="end">${format(value)}</text>`;
    }
    const dates = [...new Map(valid.map(item => [item.date.getTime(), item.date])).values()].sort((a, b) => a - b);
    const selected = [...new Set([0, Math.floor((dates.length - 1) / 2), dates.length - 1])];
    const xLabels = selected.map(index => `<text class="chart-axis" x="${chart.x(dates[index])}" y="${chart.height-20}" text-anchor="middle">${formatDate(dates[index])}</text>`).join("");
    return `<svg viewBox="0 0 ${chart.width} ${chart.height}" role="img" aria-labelledby="chart-title chart-desc"><title id="chart-title">Evolución de ${cfg.label.toLowerCase()}</title><desc id="chart-desc">${description}</desc>${grids}${labels}${drawings}${xLabels}<text class="chart-axis" x="16" y="18">${cfg.unit}</text></svg>`;
  }

  function buildSegments(series, key, connectValidPoints = false) {
    if (connectValidPoints) {
      const valid = series.filter(item => item[key] != null && Number.isFinite(Number(item[key])));
      return valid.length ? [valid] : [];
    }
    const segments = []; let current = [];
    series.forEach(item => {
      if (item[key] == null) { if (current.length) segments.push(current); current = []; }
      else current.push(item);
    });
    if (current.length) segments.push(current);
    return segments;
  }

  function empty(container, label, explanation) {
    container.innerHTML = `<div class="chart-empty"><div><strong>Sin datos oficiales para ${label}</strong><br><span>${explanation}</span></div></div>`;
  }

  const format = value => new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 }).format(value);
  const formatDate = date => new Intl.DateTimeFormat("es-ES", { day: "2-digit", month: "short" }).format(date);
  const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[char]);
  return { render };
})();
