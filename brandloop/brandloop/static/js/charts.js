/* Inline-SVG charts. No libraries, no external requests.
 *
 * Colours come from CSS custom properties so light and dark themes are handled
 * by the stylesheet rather than duplicated here. Every chart ships a hover
 * layer: an HTML chart is interactive by default, and the numbers behind each
 * mark should be readable without squinting at an axis. */

const SVG_NS = 'http://www.w3.org/2000/svg';
const SEGMENT_GAP = 2;   // surface gap between stacked segments
const CORNER = 4;        // rounded data-end radius
const AXIS_PAD = { top: 10, right: 6, bottom: 20, left: 30 };

function token(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function el(tag, attrs = {}, parent = null) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (parent) parent.appendChild(node);
  return node;
}

/* A single tooltip element is reused by every chart on the page. */
let tip;
function tooltip() {
  if (!tip) {
    tip = document.createElement('div');
    tip.className = 'charttip';
    document.body.appendChild(tip);
  }
  return tip;
}

function showTip(html, event) {
  const node = tooltip();
  node.innerHTML = html;
  node.style.opacity = '1';
  const box = node.getBoundingClientRect();
  let left = event.clientX + 14;
  if (left + box.width > window.innerWidth - 8) left = event.clientX - box.width - 14;
  node.style.left = `${left + window.scrollX}px`;
  node.style.top = `${event.clientY - box.height - 10 + window.scrollY}px`;
}

function hideTip() {
  if (tip) tip.style.opacity = '0';
}

function niceMax(value) {
  if (value <= 0) return 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
  return Math.ceil(value / magnitude) * magnitude;
}

function svgRoot(container, height) {
  container.innerHTML = '';
  const width = Math.max(container.clientWidth || 520, 260);
  const svg = el('svg', {
    class: 'chart', viewBox: `0 0 ${width} ${height}`, height,
    preserveAspectRatio: 'none', role: 'img',
  }, container);
  return { svg, width, height };
}

/* Rounded on the data-end only, square where it meets the baseline or the
 * segment below it — a bar's footing should not float. */
function barPath(x, y, w, h, r) {
  const radius = Math.min(r, w / 2, h);
  if (h <= 0) return '';
  return `M${x},${y + h} L${x},${y + radius} Q${x},${y} ${x + radius},${y} ` +
         `L${x + w - radius},${y} Q${x + w},${y} ${x + w},${y + radius} L${x + w},${y + h} Z`;
}

/* ------------------------------------------------------- stacked columns */

function stackedColumns(container, data) {
  const { svg, width, height } = svgRoot(container, 190);
  const plotW = width - AXIS_PAD.left - AXIS_PAD.right;
  const plotH = height - AXIS_PAD.top - AXIS_PAD.bottom;

  const series = [
    { key: 'positive', label: 'Positive', color: token('--c-pos', '#0e7c86') },
    { key: 'neutral', label: 'Neutral', color: token('--c-neu', '#c3c9d4') },
    { key: 'negative', label: 'Negative', color: token('--c-neg', '#c9482b') },
  ];

  const totals = data.labels.map((_, i) =>
    series.reduce((sum, s) => sum + (data[s.key][i] || 0), 0));
  const max = niceMax(Math.max(...totals, 1));
  const slot = plotW / data.labels.length;
  const barW = Math.max(4, Math.min(slot - 6, 28));

  // Gridlines and y labels first, so marks always sit on top of them.
  for (let t = 0; t <= 2; t++) {
    const value = (max / 2) * t;
    const y = AXIS_PAD.top + plotH - (value / max) * plotH;
    el('line', { class: 'grid-line', x1: AXIS_PAD.left, x2: width - AXIS_PAD.right, y1: y, y2: y }, svg);
    el('text', { x: AXIS_PAD.left - 6, y: y + 3, 'text-anchor': 'end' }, svg)
      .textContent = String(Math.round(value));
  }

  data.labels.forEach((label, i) => {
    const cx = AXIS_PAD.left + slot * i + slot / 2;
    let cursor = AXIS_PAD.top + plotH;

    series.forEach((s, si) => {
      const value = data[s.key][i] || 0;
      if (!value) return;
      const raw = (value / max) * plotH;
      const h = Math.max(raw - (si === 0 ? 0 : SEGMENT_GAP), 1);
      const y = cursor - h;
      const isTop = series.slice(0, si).every((prev) => !data[prev.key][i]);
      el('path', {
        d: barPath(cx - barW / 2, y, barW, h, isTop ? CORNER : 0),
        fill: s.color,
      }, svg);
      cursor -= raw;
    });

    // Every third tick, so labels never collide on a narrow card.
    if (i % 3 === 0 || i === data.labels.length - 1) {
      el('text', { x: cx, y: height - 6, 'text-anchor': 'middle' }, svg).textContent = label;
    }

    const hit = el('rect', {
      class: 'hit', x: AXIS_PAD.left + slot * i, y: AXIS_PAD.top, width: slot, height: plotH,
    }, svg);
    hit.addEventListener('mousemove', (event) => {
      const rows = series
        .map((s) => `<div><span class="k" style="background:${s.color}"></span>${s.label} <b>${data[s.key][i] || 0}</b></div>`)
        .join('');
      showTip(`<b>${label}</b> · ${totals[i]} mentions${rows}`, event);
    });
    hit.addEventListener('mouseleave', hideTip);
  });

  el('line', {
    class: 'axis-line', x1: AXIS_PAD.left, x2: width - AXIS_PAD.right,
    y1: AXIS_PAD.top + plotH, y2: AXIS_PAD.top + plotH,
  }, svg);
}

/* ------------------------------------------------------------ trend line */

function trendLine(container, data) {
  const { svg, width, height } = svgRoot(container, 190);
  const plotW = width - AXIS_PAD.left - AXIS_PAD.right;
  const plotH = height - AXIS_PAD.top - AXIS_PAD.bottom;

  // Sentiment is signed, so the scale is symmetric around a zero baseline —
  // otherwise a mildly negative week looks like a catastrophe.
  const bound = Math.max(0.25, ...data.values.map((v) => Math.abs(v))) * 1.15;
  const x = (i) => AXIS_PAD.left + (data.values.length === 1 ? plotW / 2 : (plotW * i) / (data.values.length - 1));
  const y = (v) => AXIS_PAD.top + plotH / 2 - (v / bound) * (plotH / 2);

  [bound, 0, -bound].forEach((value) => {
    const yy = y(value);
    el('line', {
      class: value === 0 ? 'axis-line' : 'grid-line',
      x1: AXIS_PAD.left, x2: width - AXIS_PAD.right, y1: yy, y2: yy,
    }, svg);
    el('text', { x: AXIS_PAD.left - 6, y: yy + 3, 'text-anchor': 'end' }, svg)
      .textContent = value.toFixed(1);
  });

  const points = data.values.map((v, i) => `${x(i)},${y(v)}`).join(' ');
  const accent = token('--c-brand', '#3b5bfd');
  el('polyline', {
    points, fill: 'none', stroke: accent, 'stroke-width': 2,
    'stroke-linejoin': 'round', 'stroke-linecap': 'round',
  }, svg);

  data.labels.forEach((label, i) => {
    if (i % 5 === 0 || i === data.labels.length - 1) {
      el('text', { x: x(i), y: height - 6, 'text-anchor': 'middle' }, svg).textContent = label;
    }
  });

  const crosshair = el('line', {
    class: 'crosshair', y1: AXIS_PAD.top, y2: AXIS_PAD.top + plotH,
  }, svg);
  const marker = el('circle', {
    class: 'marker', r: 5, fill: accent, stroke: token('--panel', '#fff'), 'stroke-width': 2,
  }, svg);

  const hit = el('rect', {
    class: 'hit', x: AXIS_PAD.left, y: AXIS_PAD.top, width: plotW, height: plotH,
  }, svg);
  hit.addEventListener('mousemove', (event) => {
    const box = svg.getBoundingClientRect();
    const ratio = (event.clientX - box.left) / box.width;
    const i = Math.max(0, Math.min(data.values.length - 1,
      Math.round(ratio * width - AXIS_PAD.left) / (plotW / Math.max(data.values.length - 1, 1))));
    const idx = Math.max(0, Math.min(data.values.length - 1, Math.round(i)));
    crosshair.setAttribute('x1', x(idx));
    crosshair.setAttribute('x2', x(idx));
    crosshair.style.opacity = '1';
    marker.setAttribute('cx', x(idx));
    marker.setAttribute('cy', y(data.values[idx]));
    marker.style.opacity = '1';
    const value = data.values[idx];
    const mood = value > 0.15 ? 'positive' : value < -0.1 ? 'negative' : 'neutral';
    showTip(`<b>${data.labels[idx]}</b><div>Avg sentiment <b>${value.toFixed(2)}</b> · ${mood}</div>`, event);
  });
  hit.addEventListener('mouseleave', () => {
    crosshair.style.opacity = '0';
    marker.style.opacity = '0';
    hideTip();
  });
}

/* -------------------------------------------------------- horizontal bars */

function shareBars(container, rows, brandName) {
  container.innerHTML = '';
  const max = Math.max(...rows.map((r) => r.share), 0.01);

  rows.forEach((row) => {
    const isBrand = row.subject === brandName;
    const wrap = document.createElement('div');
    wrap.className = 'barrow';
    wrap.innerHTML = `
      <span title="${row.subject}">${row.subject}</span>
      <span class="track"><span class="fill${isBrand ? '' : ' alt'}"
        style="width:${Math.max((row.share / max) * 100, 2)}%"></span></span>
      <span class="num tiny">${(row.share * 100).toFixed(1)}%</span>`;
    wrap.addEventListener('mousemove', (event) => showTip(
      `<b>${row.subject}</b><div>${row.mentions} mentions · ${(row.share * 100).toFixed(1)}% of voice</div>` +
      `<div>Avg sentiment <b>${row.sentiment.toFixed(2)}</b></div>`, event));
    wrap.addEventListener('mouseleave', hideTip);
    container.appendChild(wrap);
  });
}

window.BLCharts = { stackedColumns, trendLine, shareBars };
