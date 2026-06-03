const tradingWorkspaceUrl = "/api/trading-workspace";
const setupReadinessUrl = "/api/setup-readiness";
const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function dollarValue(value) {
  if (value === undefined || value === null || value === "") return "--";
  return `$${Number(value).toFixed(2)}`;
}

function signedValue(value, digits = 2) {
  const number = Number(value || 0);
  return `${number >= 0 ? "+" : ""}${number.toFixed(digits)}`;
}

function tradingChartSvg(candles, signalMarkers = []) {
  if (!candles?.length) {
    return '<div class="terminal-empty">No saved candles are available for this chart.</div>';
  }

  const width = 1100;
  const height = 520;
  const left = 18;
  const right = 70;
  const top = 18;
  const priceBottom = 388;
  const volumeTop = 420;
  const volumeBottom = 488;
  const plotWidth = width - left - right;
  const indicatorKeys = ["vwap", "ema_9", "ema_21", "ema_200"];
  const priceValues = [];
  candles.forEach((candle) => {
    priceValues.push(Number(candle.low), Number(candle.high));
    indicatorKeys.forEach((key) => {
      if (candle[key] !== null) priceValues.push(Number(candle[key]));
    });
  });
  const rawMin = Math.min(...priceValues);
  const rawMax = Math.max(...priceValues);
  const padding = Math.max((rawMax - rawMin) * 0.06, rawMax * 0.0004);
  const low = rawMin - padding;
  const high = rawMax + padding;
  const range = Math.max(high - low, 0.01);
  const maxVolume = Math.max(...candles.map((candle) => Number(candle.volume)), 1);
  const step = plotWidth / candles.length;
  const bodyWidth = Math.max(Math.min(step * 0.68, 10), 2);
  const x = (index) => left + step * index + step / 2;
  const y = (value) => top + ((high - Number(value)) / range) * (priceBottom - top);
  const volumeY = (volume) => volumeBottom - (Number(volume) / maxVolume) * (volumeBottom - volumeTop);

  const grid = Array.from({ length: 5 }, (_, index) => {
    const value = high - (range / 4) * index;
    const lineY = y(value);
    return `
      <line class="price-grid" x1="${left}" y1="${lineY}" x2="${width - right}" y2="${lineY}"></line>
      <text class="price-axis" x="${width - right + 7}" y="${lineY + 4}">${value.toFixed(2)}</text>
    `;
  }).join("");

  const volumeBars = candles
    .map((candle, index) => {
      const className = Number(candle.close) >= Number(candle.open) ? "volume-up" : "volume-down";
      const barTop = volumeY(candle.volume);
      return `<rect class="${className}" x="${x(index) - bodyWidth / 2}" y="${barTop}" width="${bodyWidth}" height="${volumeBottom - barTop}"></rect>`;
    })
    .join("");

  const candleBars = candles
    .map((candle, index) => {
      const className = Number(candle.close) >= Number(candle.open) ? "candle-up" : "candle-down";
      const bodyTop = Math.min(y(candle.open), y(candle.close));
      const bodyHeight = Math.max(Math.abs(y(candle.open) - y(candle.close)), 1.5);
      return `
        <line class="${className}" x1="${x(index)}" y1="${y(candle.high)}" x2="${x(index)}" y2="${y(candle.low)}"></line>
        <rect class="${className}" x="${x(index) - bodyWidth / 2}" y="${bodyTop}" width="${bodyWidth}" height="${bodyHeight}"></rect>
      `;
    })
    .join("");

  const indicator = (key, className) => {
    const points = candles
      .map((candle, index) => (candle[key] === null ? "" : `${x(index)},${y(candle[key])}`))
      .filter(Boolean)
      .join(" ");
    return points ? `<polyline class="indicator-line ${className}" points="${points}"></polyline>` : "";
  };

  const last = candles[candles.length - 1];
  const sessionStartIndex = Math.max(
    candles.findIndex((candle) => candle.session_date === last.session_date),
    0,
  );
  const sessionLineStart = x(sessionStartIndex) - step / 2;
  const rangeLines = ["opening_range_high", "opening_range_low"]
    .filter((key) => last[key] !== null)
    .map(
      (key) =>
        `<line class="opening-range-line" x1="${sessionLineStart}" y1="${y(last[key])}" x2="${width - right}" y2="${y(last[key])}"></line>`,
    )
    .join("");
  const labelIndexes = Array.from(new Set([0, Math.floor((candles.length - 1) / 2), candles.length - 1]));
  const timeLabels = labelIndexes
    .map(
      (index) =>
        `<text class="price-axis" x="${x(index)}" y="${height - 11}" text-anchor="${index === 0 ? "start" : index === candles.length - 1 ? "end" : "middle"}">${escapeHtml(candles[index].time_et)}</text>`,
    )
    .join("");
  const markers = signalMarkers
    .map((marker) => {
      const index = candles.findIndex((candle) => candle.time_et === marker.time_et);
      if (index < 0) return "";
      const markerY = Math.max(y(candles[index].high) - 17, top + 9);
      const className = marker.kind || (marker.scanner_status === "allowed" ? "allowed" : "watch");
      return `
        <line class="signal-marker-guide ${className}" x1="${x(index)}" y1="${markerY + 8}" x2="${x(index)}" y2="${y(candles[index].high) - 2}"></line>
        <circle class="signal-marker ${className}" cx="${x(index)}" cy="${markerY}" r="9"></circle>
        <text class="signal-marker-label" x="${x(index)}" y="${markerY + 4}">${escapeHtml(marker.label)}</text>
      `;
    })
    .join("");

  return `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Expanded saved Webull candle chart with strategy indicators">
      ${grid}
      ${rangeLines}
      ${volumeBars}
      ${candleBars}
      ${indicator("vwap", "line-vwap")}
      ${indicator("ema_9", "line-ema9")}
      ${indicator("ema_21", "line-ema21")}
      ${indicator("ema_200", "line-ema200")}
      ${markers}
      ${timeLabels}
    </svg>
  `;
}

async function loadExpandedChart() {
  const params = new URLSearchParams(window.location.search);
  const symbol = params.get("symbol") || "SPY";
  const timeframe = params.get("timeframe") || "M5";
  $("expanded-chart").innerHTML = '<div class="terminal-empty">Loading expanded chart...</div>';
  const chartResponse = await fetch(
    `${tradingWorkspaceUrl}?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}`,
    { cache: "no-store" },
  );
  const chart = await chartResponse.json();
  if (!chartResponse.ok) throw new Error(chart.error || `Chart request failed: ${chartResponse.status}`);
  const readinessResponse = await fetch(`${setupReadinessUrl}?symbol=${encodeURIComponent(chart.symbol)}`, {
    cache: "no-store",
  });
  const readiness = await readinessResponse.json();
  const markers = readinessResponse.ok ? readiness.signal_markers || [] : [];
  $("expanded-source").textContent = `${chart.source} / ${chart.timeframe}`;
  $("expanded-symbol").textContent = chart.symbol;
  $("expanded-price").textContent = dollarValue(chart.last_price);
  $("expanded-change").textContent = `${signedValue(chart.day_change)} (${signedValue(chart.day_change_pct)}%) vs prior session close`;
  $("expanded-chart").innerHTML = tradingChartSvg(chart.candles, markers);
  $("expanded-time").textContent =
    `${chart.timeframe_role || "Chart timeframe"}. Latest stored bar: ${chart.latest_bar_et} (${chart.data_lag_minutes ?? "--"} min behind now).`;
}

async function refresh() {
  $("expanded-refresh").disabled = true;
  try {
    await loadExpandedChart();
  } catch (error) {
    $("expanded-chart").innerHTML = `<div class="terminal-empty">${escapeHtml(error.message)}</div>`;
    $("expanded-time").textContent = "Run a market-data refresh to populate this expanded chart.";
  } finally {
    $("expanded-refresh").disabled = false;
  }
}

$("expanded-refresh").addEventListener("click", refresh);
refresh();
