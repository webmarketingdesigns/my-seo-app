/* Page glue: API calls, toasts, and the studio approval queue. */

const brandQuery = () => (window.BRAND_ID ? `?brand=${window.BRAND_ID}` : '');

function toast(message, bad = false) {
  const node = document.getElementById('toast');
  if (!node) return;
  node.textContent = message;
  node.classList.toggle('bad', bad);
  node.hidden = false;
  clearTimeout(node._timer);
  node._timer = setTimeout(() => { node.hidden = true; }, 4200);
}

async function api(path, method = 'GET', body = null) {
  const sep = path.includes('?') ? '&' : '?';
  const url = window.BRAND_ID ? `${path}${sep}brand=${window.BRAND_ID}` : path;
  try {
    const response = await fetch(url, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : null,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      toast(data.error || `Request failed (${response.status})`, true);
      return null;
    }
    return data;
  } catch (error) {
    toast(`Network error: ${error.message}`, true);
    return null;
  }
}

function busy(button, label) {
  if (!button) return () => {};
  const original = button.textContent;
  button.disabled = true;
  button.textContent = label;
  return () => { button.disabled = false; button.textContent = original; };
}

/* ------------------------------------------------------------ ingestion */

document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const action = button.dataset.action;

  if (action === 'ingest') {
    const done = busy(button, 'Fetching…');
    const result = await api('/api/ingest', 'POST');
    done();
    if (result) {
      const errors = result.errors && result.errors.length
        ? ` · ${result.errors.length} source(s) failed` : '';
      toast(`Stored ${result.stored} new mentions from ${result.sources_run} sources${errors}`);
      if (result.stored) setTimeout(() => location.reload(), 900);
    }
  }

  if (action === 'seed') {
    const done = busy(button, 'Seeding…');
    const result = await api('/api/seed', 'POST', { days: 30, per_day: 6 });
    done();
    if (result) {
      toast(`Seeded ${result.stored} demo mentions`);
      setTimeout(() => location.reload(), 700);
    }
  }

  if (action === 'run-scheduler') {
    const done = busy(button, 'Running…');
    const result = await api('/api/scheduler/run', 'POST');
    done();
    if (result) {
      toast(`Published ${result.published} due post(s), refreshed ${result.metrics_refreshed} metric(s)`);
      if (result.published || result.metrics_refreshed) setTimeout(() => location.reload(), 900);
    }
  }
});

/* --------------------------------------------------------------- charts */

function drawCharts() {
  const volume = document.getElementById('chart-volume');
  if (volume && volume.dataset.series) {
    window.BLCharts.stackedColumns(volume, JSON.parse(volume.dataset.series));
  }
  const trend = document.getElementById('chart-sentiment');
  if (trend && trend.dataset.series) {
    window.BLCharts.trendLine(trend, JSON.parse(trend.dataset.series));
  }
  const share = document.getElementById('chart-share');
  if (share && share.dataset.series) {
    window.BLCharts.shareBars(share, JSON.parse(share.dataset.series), share.dataset.brand);
  }
}

let redrawTimer;
window.addEventListener('resize', () => {
  clearTimeout(redrawTimer);
  redrawTimer = setTimeout(drawCharts, 180);
});
document.addEventListener('DOMContentLoaded', drawCharts);
