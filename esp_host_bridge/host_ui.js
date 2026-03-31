const hostMetricsBoot = (window.__HOST_METRICS_BOOT__ && typeof window.__HOST_METRICS_BOOT__ === 'object')
  ? window.__HOST_METRICS_BOOT__
  : {};
let nextLogId = Number(hostMetricsBoot.nextLogId || 1);
if (!Number.isFinite(nextLogId) || nextLogId < 1) nextLogId = 1;
let nextCommLogId = Number(hostMetricsBoot.nextCommLogId || 1);
if (!Number.isFinite(nextCommLogId) || nextCommLogId < 1) nextCommLogId = 1;
let lastStatusPayload = null;
let currentViewMode = 'setup';
let currentEspPreviewPage = 'home';
let lastMonitorDashboardSignature = '';
let lastMonitorDetailSignature = '';
let lastPreviewCardSignature = '';
let lastPreviewUiSignature = '';
let mainLogRows = [];
let hideMetricLogs = false;
const ESP_PREVIEW_LONG_PRESS_MS = 420;
const ESP_PREVIEW_SWIPE_THRESHOLD = 36;
let espPreviewDockerItems = [];
let espPreviewVmItems = [];
let espPreviewDockerOverrides = Object.create(null);
let espPreviewVmOverrides = Object.create(null);
let espPreviewActiveModal = null;
const ESP_PREVIEW_PAGE_KEY = 'esp_host_bridge_esp_preview_page_v1';
const ESP_PREVIEW_PAGE_KEY_LEGACY = 'host_metrics_esp_preview_page_v1';
const VIEW_MODE_KEY = 'esp_host_bridge_view_mode_v1';
const VIEW_MODE_KEY_LEGACY = 'host_metrics_view_mode_v1';
const HIDE_METRIC_LOGS_KEY = 'esp_host_bridge_hide_metric_logs_v1';
const HIDE_METRIC_LOGS_KEY_LEGACY = 'host_metrics_hide_metric_logs_v1';
const UI_SECTIONS_KEY = 'esp_host_bridge_ui_sections_v1';
const UI_SECTIONS_KEY_LEGACY = 'host_metrics_ui_sections_v1';

function previewUiSnapshot(s) {
  const preview = (s && s.preview_ui && typeof s.preview_ui === 'object') ? s.preview_ui : hostMetricsBoot.preview_ui;
  return (preview && typeof preview === 'object') ? preview : {};
}
function previewUiMode(s) {
  return previewUiSnapshot(s).mode === 'homeassistant' ? 'homeassistant' : 'host';
}
function previewPageOrder(s) {
  const rows = previewUiSnapshot(s).page_order;
  return Array.isArray(rows) && rows.length ? rows : ['home'];
}
function previewPageMeta(s, page) {
  const pages = previewUiSnapshot(s).pages;
  const map = (pages && typeof pages === 'object') ? pages : {};
  const meta = map && map[page];
  if (meta && typeof meta === 'object') return meta;
  const home = map && map.home;
  return (home && typeof home === 'object') ? home : { page_id: 'home', dom_id: 'espPageHome', title: 'HOME', footer: 'HOME', nav: {} };
}
function previewTabs(s) {
  const rows = previewUiSnapshot(s).tabs;
  return Array.isArray(rows) ? rows : [];
}
function previewHomeButtons(s) {
  const rows = previewUiSnapshot(s).home_buttons;
  return Array.isArray(rows) ? rows : [];
}
function previewModalMeta(s, target) {
  const modals = previewUiSnapshot(s).modals;
  const map = (modals && typeof modals === 'object') ? modals : {};
  const meta = map && map[target];
  return (meta && typeof meta === 'object') ? meta : {};
}
function setMetricCardHeading(valueId, iconClass, labelText) {
  const valueEl = document.getElementById(valueId);
  const labelEl = valueEl && valueEl.previousElementSibling;
  if (!labelEl) return;
  labelEl.innerHTML = `<span class="metric-icon" aria-hidden="true"><span class="mdi ${iconClass}"></span></span>${escapeHtml(labelText)}`;
}
function setCardHeading(valueId, labelText) {
  const valueEl = document.getElementById(valueId);
  const labelEl = valueEl && valueEl.previousElementSibling;
  if (!labelEl) return;
  labelEl.textContent = labelText;
}
function renderPreviewUi(s) {
  const preview = previewUiSnapshot(s);
  const signature = JSON.stringify(preview);
  if (signature === lastPreviewUiSignature) return;
  lastPreviewUiSignature = signature;

  const tabsBox = document.getElementById('espPreviewTabs');
  if (tabsBox) {
    tabsBox.innerHTML = previewTabs(s).map((tab) => {
      const pageId = escapeHtml(String(tab && tab.page_id || 'home'));
      const label = escapeHtml(String(tab && tab.label || pageId));
      const iconClass = escapeHtml(String(tab && tab.icon_class || 'mdi-application-outline'));
      return `<button class="secondary" type="button" data-esp-page="${pageId}"><span class="mdi ${iconClass}" aria-hidden="true"></span>${label}</button>`;
    }).join('');
  }

  const homeButtonsBox = document.getElementById('espHomeNavButtons');
  if (homeButtonsBox) {
    homeButtonsBox.innerHTML = previewHomeButtons(s).map((button) => {
      const target = escapeHtml(String(button && button.target_page || 'home'));
      const position = escapeHtml(String(button && button.position || ''));
      const title = escapeHtml(String(button && button.title || target));
      const iconClass = escapeHtml(String(button && button.icon_class || 'mdi-circle-outline'));
      return `<div class="esp-home-btn ${position}" data-esp-nav="${target}" title="${title}"><span class="mdi ${iconClass}"></span></div>`;
    }).join('');
  }

  ['docker', 'vms'].forEach((target) => {
    const meta = previewModalMeta(s, target);
    const modal = document.getElementById(target === 'docker' ? 'espDockerModal' : 'espVmsModal');
    if (!modal) return;
    const icon = modal.querySelector('.esp-preview-modal-heading .mdi');
    const title = modal.querySelector('.esp-preview-modal-title');
    const subtitle = modal.querySelector('.esp-preview-modal-subtitle');
    if (icon) icon.className = `mdi ${String(meta && meta.icon_class || 'mdi-puzzle-outline')}`;
    if (title) title.textContent = String(meta && meta.title || target.toUpperCase());
    if (subtitle) subtitle.textContent = String(meta && meta.subtitle || '');
  });

  renderPreviewActionGroups(s);
  setEspPreviewPage(currentEspPreviewPage);
}
function workloadMetricFlag(metrics, key) {
  if (!metrics || !Object.prototype.hasOwnProperty.call(metrics, key)) return null;
  const value = Number(metrics[key]);
  return Number.isFinite(value) ? value : null;
}
async function pollStatus() {
  try {
    const r = await fetch('/api/status');
    const s = await r.json();
    const started = s.started_at ? new Date(s.started_at * 1000).toLocaleString() : '--';
    const agentEl = document.getElementById('statusAgent');
    const pidEl = document.getElementById('statusPid');
    const startedEl = document.getElementById('statusStarted');
    const exitEl = document.getElementById('statusLastExit');
    if (agentEl) agentEl.textContent = s.running ? 'Running' : 'Stopped';
    if (pidEl) pidEl.textContent = s.pid ?? '--';
    if (startedEl) startedEl.textContent = started;
    if (exitEl) exitEl.textContent = s.last_exit ?? '--';
    lastStatusPayload = s;
    renderPreviewUi(s);
    renderPreviewCards(s);
    updateTelemetryHealth(s);
    updateSerialHealth(s);
    updateHostNameStatus(s);
    updateActiveIfaceStatus(s);
    updateDisplaySleepStatus(s);
    updateEspWifiStatus(s);
    updateEspBootHealth(s);
    updateMetricPreview(s.last_metrics || {});
    updateMonitorDashboard(s);
  } catch (_) {}
}
function updateTelemetryHealth(s) {
  const el = document.getElementById('telemetryHealth');
  if (!el) return;
  const ageRaw = s && s.last_metrics_age_s;
  const age = Number(ageRaw);
  el.classList.remove('ok', 'warn', 'danger');
  if (!Number.isFinite(age)) {
    el.textContent = 'Telemetry: Waiting';
    return;
  }
  if (age <= 3) {
    el.classList.add('ok');
    el.textContent = `Telemetry: Live (${Math.round(age)}s)`;
    return;
  }
  if (age <= 10) {
    el.classList.add('warn');
    el.textContent = `Telemetry: Delayed (${Math.round(age)}s)`;
    return;
  }
  el.classList.add('danger');
  el.textContent = `Telemetry: Stale (${Math.round(age)}s)`;
}
function updateSerialHealth(s) {
  const cs = (s && s.comm_status && typeof s.comm_status === 'object') ? s.comm_status : {};
  const serialEl = document.getElementById('serialHealth');
  const recEl = document.getElementById('serialReconnects');
  const ageEl = document.getElementById('serialEventAge');
  if (serialEl) {
    serialEl.classList.remove('ok', 'warn', 'danger');
    const v = cs.serial_connected;
    if (v === true) {
      serialEl.classList.add('ok');
      serialEl.textContent = 'Serial: Connected';
    } else if (v === false) {
      serialEl.classList.add('danger');
      serialEl.textContent = 'Serial: Disconnected';
    } else {
      serialEl.textContent = 'Serial: Unknown';
    }
  }
  if (recEl) {
    recEl.classList.remove('ok', 'warn', 'danger');
    const n = Number(cs.serial_disconnect_count || 0);
    if (n > 0) recEl.classList.add('warn');
    recEl.textContent = `Reconnects: ${n}`;
  }
  if (ageEl) {
    ageEl.classList.remove('ok', 'warn', 'danger');
    const age = Number(cs.last_comm_event_age_s);
    if (!Number.isFinite(age)) {
      ageEl.textContent = 'Comm: --';
    } else {
      if (age <= 5) ageEl.classList.add('ok');
      else if (age <= 30) ageEl.classList.add('warn');
      else ageEl.classList.add('danger');
      ageEl.textContent = `Comm: ${fmtAgeSec(age)}`;
    }
  }
}
function updateActiveIfaceStatus(s) {
  const el = document.getElementById('activeIfaceStatus');
  if (!el) return;
  el.classList.remove('ok', 'warn', 'danger');
  const active = (s && typeof s.active_iface === 'string') ? s.active_iface.trim() : '';
  if (!active) {
    el.classList.add('warn');
    el.textContent = 'Active Interface: Auto';
    return;
  }
  el.classList.add('ok');
  el.textContent = `Active Interface: ${active}`;
}
function updateHostNameStatus(s) {
  const el = document.getElementById('hostNameStatus');
  if (!el) return;
  el.classList.remove('ok', 'warn', 'danger');
  const host = (s && typeof s.host_name === 'string') ? s.host_name.trim() : '';
  if (!host) {
    el.classList.add('warn');
    el.textContent = 'Host: Unknown';
    return;
  }
  el.classList.add('ok');
  el.textContent = `Host: ${host}`;
}
function updateDisplaySleepStatus(s) {
  const el = document.getElementById('displaySleepStatus');
  if (!el) return;
  el.classList.remove('ok', 'warn', 'danger');
  const es = (s && s.esp_status && typeof s.esp_status === 'object') ? s.esp_status : {};
  const sleeping = es.display_sleeping;
  if (sleeping === true) {
    el.classList.add('warn');
    el.textContent = 'Display: Sleeping';
    return;
  }
  if (sleeping === false) {
    el.classList.add('ok');
    el.textContent = 'Display: Awake';
    return;
  }
  el.textContent = 'Display: --';
}
function updateEspWifiStatus(s) {
  const es = (s && s.esp_status && typeof s.esp_status === 'object') ? s.esp_status : {};
  const statusEl = document.getElementById('espWifiStatus');
  const detailEl = document.getElementById('espWifiDetail');
  const state = String(es.wifi_state || '').trim().toUpperCase();
  const ssid = String(es.wifi_ssid || '').trim();
  const ip = String(es.wifi_ip || '').trim();
  const rssi = Number(es.wifi_rssi_dbm);
  const age = Number(es.wifi_age_s);
  if (statusEl) {
    statusEl.classList.remove('ok', 'warn', 'danger');
    if (state === 'CONNECTED') {
      statusEl.classList.add('ok');
      statusEl.textContent = 'ESP Wi-Fi: Connected';
    } else if (state === 'DISCONNECTED') {
      statusEl.classList.add('danger');
      statusEl.textContent = 'ESP Wi-Fi: Disconnected';
    } else {
      statusEl.textContent = 'ESP Wi-Fi: --';
    }
  }
  if (detailEl) {
    detailEl.classList.remove('ok', 'warn', 'danger');
    if (state === 'CONNECTED') {
      const parts = [];
      if (ssid) parts.push(ssid);
      if (ip) parts.push(ip);
      if (Number.isFinite(rssi)) parts.push(`${Math.round(rssi)} dBm`);
      detailEl.classList.add('ok');
      detailEl.textContent = `ESP Wi-Fi Detail: ${parts.length ? parts.join(' • ') : 'Connected'}`;
      return;
    }
    if (state === 'DISCONNECTED') {
      detailEl.classList.add('danger');
      detailEl.textContent = `ESP Wi-Fi Detail: ${Number.isFinite(age) ? `Last update ${fmtAgeSec(age)}` : 'Disconnected'}`;
      return;
    }
    detailEl.textContent = 'ESP Wi-Fi Detail: --';
  }
}
function updateEspBootHealth(s) {
  const es = (s && s.esp_status && typeof s.esp_status === 'object') ? s.esp_status : {};
  const countEl = document.getElementById('espBootCount');
  const ageEl = document.getElementById('espBootAge');
  const reasonEl = document.getElementById('espBootReason');
  const reason = String(es.last_boot_reason || '').trim();
  if (countEl) {
    countEl.classList.remove('ok', 'warn', 'danger');
    const count = Number(es.boot_count || 0);
    if (count > 0) countEl.classList.add('ok');
    countEl.textContent = `ESP Boots: ${count}`;
  }
  if (ageEl) {
    ageEl.classList.remove('ok', 'warn', 'danger');
    const age = Number(es.last_boot_age_s);
    if (!Number.isFinite(age)) {
      ageEl.textContent = 'Last ESP Boot: --';
    } else {
      if (age <= 10) ageEl.classList.add('ok');
      else if (age <= 300) ageEl.classList.add('warn');
      ageEl.textContent = `Last ESP Boot: ${fmtAgeSec(age)}`;
    }
  }
  if (reasonEl) {
    reasonEl.classList.remove('ok', 'warn', 'danger');
    if (!reason) {
      reasonEl.textContent = 'Last ESP Reset: --';
      return;
    }
    const okReasons = new Set(['POWERON', 'SW', 'USB']);
    const warnReasons = new Set(['EXT', 'DEEPSLEEP']);
    if (okReasons.has(reason)) reasonEl.classList.add('ok');
    else if (warnReasons.has(reason)) reasonEl.classList.add('warn');
    else reasonEl.classList.add('danger');
    reasonEl.textContent = `Last ESP Reset: ${reason}`;
  }
}
function metricText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}
function previewCards(s) {
  return Array.isArray(s && s.preview_cards) ? s.preview_cards : [];
}
function previewActionGroups(s) {
  return Array.isArray(s && s.preview_action_groups) ? s.preview_action_groups : [];
}
function previewActionGroup(s, target) {
  const needle = String(target || '').trim().toLowerCase();
  return previewActionGroups(s).find((row) => String(row && row.target || '').trim().toLowerCase() === needle) || null;
}
function summaryBarChips(s) {
  return Array.isArray(s && s.summary_bar) ? s.summary_bar : [];
}
function renderPreviewCards(s) {
  const box = document.getElementById('metricsPreview');
  if (!box) return;
  const cards = previewCards(s);
  const signature = JSON.stringify(cards);
  if (signature === lastPreviewCardSignature) return;
  lastPreviewCardSignature = signature;
  if (!cards.length) {
    box.innerHTML = '<div class="metric-card"><div class="metric-label">Telemetry</div><div class="metric-value">Waiting...</div><div class="metric-sub">No preview metadata</div></div>';
    return;
  }
  box.innerHTML = cards.map((card) => `<div class="metric-card">
    <div class="metric-label"><span class="metric-icon" aria-hidden="true"><span class="mdi ${escapeHtml(String(card && card.icon_class || 'mdi-chart-box-outline'))}"></span></span>${escapeHtml(String(card && card.label || card.card_id || 'Metric'))}</div>
    <div class="metric-value" id="m${escapeHtml(String(card && card.card_id || 'Metric'))}">Waiting...</div>
    <div class="metric-sub">${escapeHtml(String(card && card.subtext || ''))}</div>
  </div>`).join('');
}
function previewCardText(card, metrics, workloadMode) {
  const key = String(card && card.metric_key || '').trim();
  const secondaryKey = String(card && card.secondary_metric_key || '').trim();
  const has = (k) => !!k && Object.prototype.hasOwnProperty.call(metrics, k) && metrics[k] !== '' && metrics[k] !== null && metrics[k] !== undefined;
  switch (String(card && card.render_kind || '')) {
    case 'percent_metric':
      return has(key) ? `${metrics[key]}%` : 'Waiting...';
    case 'temp_metric':
      return has(key) ? `${metrics[key]}°C` : 'Waiting...';
    case 'pair_metric': {
      const left = has(key) ? `${metrics[key]}` : '...';
      const right = has(secondaryKey) ? `${metrics[secondaryKey]}` : '...';
      return `${left} / ${right}`;
    }
    case 'disk_temp_usage': {
      const left = has(key) ? `${metrics[key]}°C` : '...';
      const right = has(secondaryKey) ? `${metrics[secondaryKey]}%` : '...';
      return `${left} / ${right}`;
    }
    case 'docker_preview_counts': {
      const dr = has('DOCKRUN') ? metrics.DOCKRUN : '...';
      const ds = has('DOCKSTOP') ? metrics.DOCKSTOP : '...';
      const du = has('DOCKUNH') ? metrics.DOCKUNH : '...';
      return `${dr} / ${ds} / ${du}`;
    }
    case 'vm_preview_counts': {
      const vr = has('VMSRUN') ? metrics.VMSRUN : '...';
      if (workloadMode === 'homeassistant') return `${vr}`;
      const vp = has('VMSPAUSE') ? metrics.VMSPAUSE : '...';
      const vs = has('VMSSTOP') ? metrics.VMSSTOP : '...';
      return `${vr} / ${vp} / ${vs}`;
    }
    default:
      return has(key) ? String(metrics[key]) : 'Waiting...';
  }
}
function updateSummaryBarFromMetadata(s, workloadMode) {
  const metrics = (s && s.last_metrics && typeof s.last_metrics === 'object') ? s.last_metrics : {};
  const overview = (s && s.integration_overview && typeof s.integration_overview === 'object') ? s.integration_overview : {};
  summaryBarChips(s).forEach((chip) => {
    const id = `sum${String(chip && chip.chip_id || '').trim()}`;
    switch (String(chip && chip.render_kind || '')) {
      case 'agent_running':
        metricText(id, s.running ? 'Running' : 'Stopped');
        break;
      case 'workload_summary':
        if (workloadMode === 'homeassistant') metricText(id, 'A ' + String(metrics.DOCKRUN ?? '--') + '/' + String(metrics.DOCKSTOP ?? '--') + ' • I ' + String(metrics.VMSRUN ?? '--'));
        else metricText(id, 'D ' + String(metrics.DOCKRUN ?? '--') + '/' + String(metrics.DOCKSTOP ?? '--') + ' • VM ' + String(metrics.VMSRUN ?? '--') + '/' + String(metrics.VMSPAUSE ?? '--') + '/' + String(metrics.VMSSTOP ?? '--'));
        break;
      case 'metrics_age':
        metricText(id, fmtAgeSec(s.last_metrics_age_s));
        break;
      case 'integration_ready': {
        metricText(id, String(overview.ready_text || '--'));
        break;
      }
      case 'metric_text': {
        const metricKey = String(chip && chip.metric_key || '').trim();
        metricText(id, metricKey && Object.prototype.hasOwnProperty.call(metrics, metricKey) ? String(metrics[metricKey]) : String(chip && chip.fallback_text || '--'));
        break;
      }
      default:
        metricText(id, String(chip && chip.fallback_text || '--'));
        break;
    }
  });
}
function updateMetricPreview(metrics) {
  const m = (metrics && typeof metrics === 'object') ? metrics : {};
  const cards = previewCards(lastStatusPayload || {});
  if (!cards.length) return;
  cards.forEach((card) => {
    metricText(`m${String(card && card.card_id || '').trim()}`, previewCardText(card, m, previewUiMode(lastStatusPayload)));
  });
}

function toNum(v) { const n = Number(v); return Number.isFinite(n) ? n : null; }
function fmtAgeSec(s) { if (s === null || s === undefined || !Number.isFinite(Number(s))) return '--'; const x = Math.max(0, Number(s)); if (x < 2) return 'just now'; if (x < 60) return String(Math.round(x)) + 's ago'; if (x < 3600) return String(Math.round(x/60)) + 'm ago'; return String(Math.round(x/3600)) + 'h ago'; }
function fmtUptimeSec(v) { const n = Math.max(0, Math.round(Number(v||0))); const d = Math.floor(n/86400), h = Math.floor((n%86400)/3600), m = Math.floor((n%3600)/60); if (d) return String(d) + 'd ' + String(h) + 'h'; if (h) return String(h) + 'h ' + String(m) + 'm'; return String(m) + 'm'; }
function fmtEspUptime(v) {
  const n = Math.max(0, Math.round(Number(v || 0)));
  const d = Math.floor(n / 86400);
  const h = Math.floor((n % 86400) / 3600);
  const m = Math.floor((n % 3600) / 60);
  return `${d}d ${h}h ${m}m`;
}
function fmtEspMBps(kbps) {
  const n = Number(kbps);
  if (!Number.isFinite(n)) return '--';
  const MBps = n / 8000;
  if (MBps < 10) return MBps.toFixed(2);
  if (MBps < 100) return MBps.toFixed(1);
  return Math.round(MBps).toString();
}
function pickNetScaleKbps(values) {
  const buckets = [2000, 4000, 8000, 20000, 40000, 80000, 200000, 400000, 800000, 1000000, 2000000, 2500000, 5000000];
  const maxValue = Math.max(1, ...((Array.isArray(values) ? values : []).map((v) => Number(v) || 0)));
  for (const bucket of buckets) {
    if (maxValue <= bucket) return bucket;
  }
  return buckets[buckets.length - 1];
}
function fmtNetScaleLabel(kbps) {
  const n = Math.max(1, Math.round(Number(kbps) || 0));
  const MBps = n / 8000;
  if (MBps >= 1000) {
    const GBps = MBps / 1000;
    return Number.isInteger(GBps) ? `${GBps} GB/s` : `${GBps.toFixed(1)} GB/s`;
  }
  if (MBps >= 100 || Math.abs(MBps - Math.round(MBps)) < 0.05) return `${Math.round(MBps)} MB/s`;
  if (MBps >= 10) return `${MBps.toFixed(1)} MB/s`;
  return `${MBps.toFixed(2)} MB/s`;
}
function setEspSliderValue(fillId, knobId, value, maxValue) {
  const max = Math.max(1, Number(maxValue) || 255);
  const pct = Math.max(0, Math.min(100, ((Number(value) || 0) / max) * 100));
  const fill = document.getElementById(fillId);
  const knob = document.getElementById(knobId);
  if (fill) fill.style.width = `${pct}%`;
  if (knob) knob.style.left = `calc(${pct}% - 13px)`;
}
function setPreviewBadge(id, text, mode) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.classList.remove('is-ok', 'is-stale', 'is-empty');
  if (mode === 'ok') el.classList.add('is-ok');
  else if (mode === 'stale') el.classList.add('is-stale');
  else el.classList.add('is-empty');
}
function scaleHistoryToPct(values, maxOverride) {
  const arr = (Array.isArray(values) ? values : []).map((v) => Number(v)).filter((v) => Number.isFinite(v));
  if (!arr.length) return [];
  const maxValue = Math.max(1, Number.isFinite(Number(maxOverride)) ? Number(maxOverride) : 0, ...arr);
  return arr.map((v) => Math.max(0, Math.min(100, (v / maxValue) * 100)));
}
function espDualGraphSvg(cpuValues, memValues) {
  const w = 342, h = 114;
  const cpu = (Array.isArray(cpuValues) ? cpuValues : []).map(Number).filter((v)=>Number.isFinite(v));
  const mem = (Array.isArray(memValues) ? memValues : []).map(Number).filter((v)=>Number.isFinite(v));
  const n = Math.max(cpu.length, mem.length);
  const mk = (arr, color) => {
    if (!arr.length) return '';
    const pts = arr.map((v, i) => {
      const x = (i * (w - 1)) / Math.max(1, arr.length - 1);
      const y = (h - 1) - (Math.max(0, Math.min(100, v)) / 100) * (h - 1);
      return [x, y];
    });
    const d = pts.map((p, i)=> (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
    return '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>';
  };
  const grid = [25, 50, 75].map((pct)=> {
    const y = ((100 - pct) / 100) * (h - 1);
    return '<line x1="0" y1="' + y.toFixed(1) + '" x2="' + (w-1) + '" y2="' + y.toFixed(1) + '" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>';
  }).join('');
  return '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">'
    + '<rect x="0" y="0" width="' + w + '" height="' + h + '" fill="rgba(11,30,74,0.35)"/>'
    + grid
    + mk(cpu, '#38BDF8')
    + mk(mem, '#A855F7')
    + '</svg>';
}
function espSingleGraphSvg(values, color) {
  const w = 342, h = 114;
  const arr = (Array.isArray(values) ? values : []).map(Number).filter((v)=>Number.isFinite(v));
  const grid = [25, 50, 75].map((pct)=> {
    const y = ((100 - pct) / 100) * (h - 1);
    return '<line x1="0" y1="' + y.toFixed(1) + '" x2="' + (w-1) + '" y2="' + y.toFixed(1) + '" stroke="rgba(255,255,255,0.08)" stroke-width="1"/>';
  }).join('');
  let path = '';
  if (arr.length) {
    const pts = arr.map((v, i) => {
      const clamped = Math.max(0, Math.min(100, v));
      const x = (i * (w - 1)) / Math.max(1, arr.length - 1);
      const y = (h - 1) - (clamped / 100) * (h - 1);
      return [x, y];
    });
    path = '<path d="' + pts.map((p, i)=>(i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ') + '" fill="none" stroke="' + (color || '#38BDF8') + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>';
  }
  return '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">'
    + '<rect x="0" y="0" width="' + w + '" height="' + h + '" fill="rgba(11,30,74,0.35)"/>'
    + grid + path + '</svg>';
}
function escapeHtml(text) {
  return String(text == null ? '' : text)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}
function isDockerRunningState(state) {
  const s = String(state || '').toLowerCase();
  return s.includes('up') || s.includes('running') || s.includes('healthy');
}
function dockerStateKeyFromRaw(state) {
  return isDockerRunningState(state) ? 'running' : 'stopped';
}
function dockerStateLabelFromRaw(state) {
  return isDockerRunningState(state) ? 'Running' : 'Stopped';
}
function countDockerPreviewItems(items) {
  const rows = Array.isArray(items) ? items : [];
  let running = 0;
  for (const item of rows) if (isDockerRunningState(item && item.state)) running += 1;
  return { total: rows.length, running, down: Math.max(0, rows.length - running) };
}
function countVmPreviewItems(items) {
  const rows = Array.isArray(items) ? items : [];
  let running = 0, paused = 0, stopped = 0;
  for (const item of rows) {
    const key = String(item && item.stateKey || 'other');
    if (key === 'running') running += 1;
    else if (key === 'paused') paused += 1;
    else if (key === 'stopped') stopped += 1;
  }
  return { total: rows.length, running, paused, stopped };
}
function buildEspHeadPillHtml(kind, label, value) {
  return `<div class="esp-head-pill ${kind}"><span class="k">${escapeHtml(label)}</span><span class="n">${escapeHtml(value)}</span></div>`;
}
function getEspPreviewMeta(page, s) {
  return previewPageMeta(s || lastStatusPayload, page);
}
function renderEspPageIndicator() {
  const el = document.getElementById('espPageIndicator');
  if (!el) return;
  const meta = getEspPreviewMeta(currentEspPreviewPage, lastStatusPayload);
  const count = Number(meta.indicator_count || 0);
  const index = Number(meta.indicator_index || 0);
  if (!count) {
    el.innerHTML = '';
    return;
  }
  const dots = [];
  for (let i = 1; i <= count; i += 1) dots.push(`<span class="esp-page-dot${i === index ? ' active' : ''}"></span>`);
  el.innerHTML = dots.join('');
}
function renderEspTopPills() {
  const el = document.getElementById('espTopPills');
  if (!el) return;
  el.innerHTML = '';
}
function refreshEspPreviewChrome() {
  const meta = getEspPreviewMeta(currentEspPreviewPage, lastStatusPayload);
  const title = document.getElementById('espTopTitle');
  const footer = document.getElementById('espFooterPage');
  if (title) title.textContent = String(meta.title || 'HOME');
  if (footer) footer.textContent = `Preview • ${String(meta.footer || 'HOME')}`;
  renderEspPageIndicator();
  renderEspTopPills();
}
function closeEspPreviewModal() {
  const dockerModal = document.getElementById('espDockerModal');
  const vmsModal = document.getElementById('espVmsModal');
  const screen = document.getElementById('espPreviewScreen');
  if (dockerModal) dockerModal.hidden = true;
  if (vmsModal) vmsModal.hidden = true;
  if (screen) screen.classList.remove('modal-open');
  espPreviewActiveModal = null;
}
function renderPreviewActionGroups(s) {
  ['docker', 'vms'].forEach((target) => {
    const group = previewActionGroup(s, target);
    const footer = document.getElementById(target === 'docker' ? 'espDockerModalActions' : 'espVmsModalActions');
    const footnote = document.getElementById(target === 'docker' ? 'espDockerModalFootnote' : 'espVmsModalFootnote');
    const actions = Array.isArray(group && group.actions) ? group.actions : [];
    if (footer) {
      footer.hidden = actions.length === 0;
      footer.innerHTML = actions.map((action) => {
        const cls = escapeHtml(String(action && action.button_class || 'secondary'));
        const label = escapeHtml(String(action && action.label || action && action.command_id || '--'));
        const commandId = escapeHtml(String(action && action.command_id || ''));
        return `<button class="esp-modal-action ${cls}" type="button" data-esp-preview-command="${commandId}">${label}</button>`;
      }).join('');
    }
    if (footnote) {
      const text = String(group && group.footnote || '');
      footnote.hidden = !text;
      footnote.textContent = text;
    }
  });
}
function applyPreviewCommandOverride(type, name, action) {
  const patch = (action && typeof action.optimistic_patch === 'object' && action.optimistic_patch) ? action.optimistic_patch : {};
  if (type === 'docker') {
    espPreviewDockerOverrides[name] = { ...(espPreviewDockerOverrides[name] || {}), ...patch };
    return;
  }
  if (type === 'vms') {
    espPreviewVmOverrides[name] = { ...(espPreviewVmOverrides[name] || {}), ...patch };
  }
}
function refreshEspPreviewActiveModal() {
  if (!espPreviewActiveModal) return;
  if (espPreviewActiveModal.type === 'docker') {
    const item = espPreviewDockerItems.find((row) => row && row.name === espPreviewActiveModal.name);
    if (!item) return;
    metricText('espDockerModalName', item.name);
    const status = document.getElementById('espDockerModalStatus');
    const detail = document.getElementById('espDockerModalDetail');
    if (status) {
      const stateKey = dockerStateKeyFromRaw(item.state);
      status.className = `esp-state-pill ${stateKey}`;
      status.textContent = dockerStateLabelFromRaw(item.state);
    }
    if (detail) detail.textContent = `Latest state: ${dockerStateLabelFromRaw(item.state)}`;
    return;
  }
  if (espPreviewActiveModal.type === 'vms') {
    const item = espPreviewVmItems.find((row) => row && row.name === espPreviewActiveModal.name);
    if (!item) return;
    metricText('espVmsModalName', item.name);
    const status = document.getElementById('espVmsModalStatus');
    const detail = document.getElementById('espVmsModalDetail');
    if (status) {
      status.className = `esp-state-pill ${escapeHtml(String(item.stateKey || 'other'))}`;
      status.textContent = String(item.stateLabel || 'Unknown');
    }
    if (detail) {
      const vcpus = Number(item.vcpus || 0);
      const memMiB = Number(item.memMiB || 0);
      detail.textContent = (vcpus || memMiB)
        ? `${item.stateLabel || 'Unknown'} • ${vcpus || 0} vCPU • ${memMiB || 0} MiB`
        : `Latest state: ${item.stateLabel || 'Unknown'}`;
    }
  }
}
function openEspPreviewModal(type, index) {
  const items = type === 'docker' ? espPreviewDockerItems : espPreviewVmItems;
  const item = Array.isArray(items) ? items[index] : null;
  if (!item) return;
  closeEspPreviewModal();
  const screen = document.getElementById('espPreviewScreen');
  const modal = document.getElementById(type === 'docker' ? 'espDockerModal' : 'espVmsModal');
  espPreviewActiveModal = { type, name: item.name };
  if (modal) modal.hidden = false;
  if (screen) screen.classList.add('modal-open');
  refreshEspPreviewActiveModal();
}
function navigateEspPreview(direction) {
  if (espPreviewActiveModal) return;
  const nav = getEspPreviewMeta(currentEspPreviewPage, lastStatusPayload).nav || {};
  const next = nav && nav[direction];
  if (next) setEspPreviewPage(next);
}
function setEspPreviewPage(page) {
  const order = previewPageOrder(lastStatusPayload);
  const next = order.includes(page) ? page : 'home';
  currentEspPreviewPage = next;
  document.querySelectorAll('[data-esp-page]').forEach((btn)=> {
    btn.classList.toggle('active', btn.getAttribute('data-esp-page') === next);
  });
  const screen = document.getElementById('espPreviewScreen');
  if (screen) screen.classList.toggle('home-mode', next === 'home');
  previewPageOrder(lastStatusPayload).forEach((pageId) => {
    const meta = getEspPreviewMeta(pageId, lastStatusPayload);
    const el = document.getElementById(String(meta.dom_id || ''));
    if (el) el.classList.toggle('active', pageId === next);
  });
  closeEspPreviewModal();
  refreshEspPreviewChrome();
  try { localStorage.setItem(ESP_PREVIEW_PAGE_KEY, next); } catch (_) {}
}
function initEspPreview() {
  const tabsBox = document.getElementById('espPreviewTabs');
  if (tabsBox) {
    tabsBox.addEventListener('click', (ev) => {
      const btn = ev.target.closest('[data-esp-page]');
      if (!btn) return;
      setEspPreviewPage(btn.getAttribute('data-esp-page') || 'home');
    });
  }
  const homeButtonsBox = document.getElementById('espHomeNavButtons');
  if (homeButtonsBox) {
    homeButtonsBox.addEventListener('click', (ev) => {
      const el = ev.target.closest('[data-esp-nav]');
      if (!el) return;
      ev.preventDefault();
      ev.stopPropagation();
      setEspPreviewPage(el.getAttribute('data-esp-nav') || 'home');
    });
  }
  const screen = document.getElementById('espPreviewScreen');
  const top = document.getElementById('espPreviewTop');
  if (top) {
    let holdTimer = null;
    const clearHold = () => {
      if (holdTimer !== null) {
        clearTimeout(holdTimer);
        holdTimer = null;
      }
    };
    top.addEventListener('pointerdown', () => {
      clearHold();
      if (currentEspPreviewPage === 'home') return;
      holdTimer = window.setTimeout(() => {
        setEspPreviewPage('home');
        clearHold();
      }, 500);
    });
    ['pointerup', 'pointercancel', 'pointerleave'].forEach((eventName) => top.addEventListener(eventName, clearHold));
  }
  if (screen) {
    let wheelLockUntil = 0;
    let gestureStart = null;
    let rowHoldTimer = null;
    let rowHoldTarget = null;
    let rowHoldOpen = false;
    let rowHoldStartX = 0;
    let rowHoldStartY = 0;
    const clearRowHold = () => {
      if (rowHoldTimer !== null) {
        clearTimeout(rowHoldTimer);
        rowHoldTimer = null;
      }
      if (rowHoldTarget) rowHoldTarget.classList.remove('is-pressing');
      rowHoldTarget = null;
      rowHoldOpen = false;
    };
    screen.addEventListener('wheel', (ev) => {
      const now = Date.now();
      if (now < wheelLockUntil || espPreviewActiveModal) return;
      if (ev.target.closest('.esp-workload-list')) return;
      const dx = Number(ev.deltaX || 0);
      const dy = Number(ev.deltaY || 0);
      if (Math.max(Math.abs(dx), Math.abs(dy)) < 18) return;
      ev.preventDefault();
      wheelLockUntil = now + 180;
      if (Math.abs(dx) > Math.abs(dy)) navigateEspPreview(dx > 0 ? 'left' : 'right');
      else navigateEspPreview(dy > 0 ? 'up' : 'down');
    }, { passive: false });
    screen.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape') {
        closeEspPreviewModal();
        return;
      }
      if (ev.key === 'ArrowRight') { ev.preventDefault(); navigateEspPreview('right'); }
      else if (ev.key === 'ArrowLeft') { ev.preventDefault(); navigateEspPreview('left'); }
      else if (ev.key === 'ArrowUp') { ev.preventDefault(); navigateEspPreview('up'); }
      else if (ev.key === 'ArrowDown') { ev.preventDefault(); navigateEspPreview('down'); }
    });
    screen.addEventListener('pointerdown', (ev) => {
      if (ev.button !== 0) return;
      const row = ev.target.closest('[data-esp-modal-row]');
      const inList = ev.target.closest('.esp-workload-list');
      clearRowHold();
      gestureStart = null;
      if (row && !espPreviewActiveModal) {
        rowHoldTarget = row;
        rowHoldStartX = ev.clientX;
        rowHoldStartY = ev.clientY;
        rowHoldTarget.classList.add('is-pressing');
        rowHoldTimer = window.setTimeout(() => {
          rowHoldOpen = true;
          openEspPreviewModal(row.dataset.espModalRow, Number(row.dataset.espIndex || -1));
        }, ESP_PREVIEW_LONG_PRESS_MS);
      }
      if (!inList && !espPreviewActiveModal && currentEspPreviewPage !== 'home') {
        gestureStart = { x: ev.clientX, y: ev.clientY, pointerId: ev.pointerId };
      }
    });
    screen.addEventListener('pointermove', (ev) => {
      if (rowHoldTarget) {
        const dx = Math.abs(ev.clientX - rowHoldStartX);
        const dy = Math.abs(ev.clientY - rowHoldStartY);
        if (dx > 6 || dy > 6) clearRowHold();
      }
    });
    screen.addEventListener('pointerup', (ev) => {
      const start = gestureStart;
      const modalWasOpened = rowHoldOpen;
      clearRowHold();
      gestureStart = null;
      if (modalWasOpened || espPreviewActiveModal || !start || start.pointerId !== ev.pointerId) return;
      const dx = ev.clientX - start.x;
      const dy = ev.clientY - start.y;
      if (Math.max(Math.abs(dx), Math.abs(dy)) < ESP_PREVIEW_SWIPE_THRESHOLD) return;
      if (Math.abs(dx) > Math.abs(dy)) navigateEspPreview(dx < 0 ? 'left' : 'right');
      else navigateEspPreview(dy < 0 ? 'up' : 'down');
    });
    ['pointercancel', 'pointerleave'].forEach((eventName) => screen.addEventListener(eventName, () => {
      clearRowHold();
      gestureStart = null;
    }));
    screen.addEventListener('contextmenu', (ev) => {
      if (ev.target.closest('[data-esp-modal-row]')) ev.preventDefault();
    });
    screen.addEventListener('click', (ev) => {
      const closeBtn = ev.target.closest('[data-esp-modal-close]');
      if (closeBtn) {
        ev.preventDefault();
        closeEspPreviewModal();
        return;
      }
      const previewAction = ev.target.closest('[data-esp-preview-command]');
      if (previewAction && espPreviewActiveModal) {
        const commandId = String(previewAction.getAttribute('data-esp-preview-command') || '').trim();
        const group = previewActionGroup(lastStatusPayload || {}, espPreviewActiveModal.type);
        const action = Array.isArray(group && group.actions)
          ? group.actions.find((row) => String(row && row.command_id || '').trim() === commandId)
          : null;
        if (!action) return;
        if (action.destructive && action.confirmation_text) {
          if (!window.confirm(String(action.confirmation_text))) return;
        }
        applyPreviewCommandOverride(espPreviewActiveModal.type, espPreviewActiveModal.name, action);
        closeEspPreviewModal();
        if (lastStatusPayload) updateEspPreview(lastStatusPayload);
        return;
      }
    });
  }
  let saved = 'home';
  try {
    const v = localStorage.getItem(ESP_PREVIEW_PAGE_KEY) || localStorage.getItem(ESP_PREVIEW_PAGE_KEY_LEGACY);
    if (v) saved = v;
  } catch (_) {}
  setEspPreviewPage(saved);
}
let layoutSyncQueued = false;
function syncEspPreviewScale() {
  const viewport = document.getElementById('espPreviewViewport');
  if (!viewport) return;
  const width = viewport.clientWidth || viewport.getBoundingClientRect().width || 0;
  if (!Number.isFinite(width) || width <= 0) return;
  const scale = Math.min(1, width / 456);
  viewport.style.setProperty('--esp-scale', scale.toFixed(4));
}
function syncStickyOffsets() {
  const root = document.documentElement;
  const topbar = document.querySelector('.topbar');
  if (!root || !topbar) return;
  const styles = window.getComputedStyle(topbar);
  const stickyTop = parseFloat(styles.top || '16') || 16;
  const offset = Math.ceil(stickyTop + topbar.getBoundingClientRect().height + 14);
  root.style.setProperty('--summary-sticky-top', offset + 'px');
}
function syncResponsiveLayout() {
  syncStickyOffsets();
  syncEspPreviewScale();
}
function requestLayoutSync() {
  if (layoutSyncQueued) return;
  layoutSyncQueued = true;
  window.requestAnimationFrame(() => {
    layoutSyncQueued = false;
    syncResponsiveLayout();
  });
}
function setMetricCard(idBase, valueText, subText, sev) {
  metricText('mv' + idBase, valueText);
  metricText('ms' + idBase, subText || '');
  const el = document.getElementById('mc' + idBase);
  if (el) { el.classList.remove('sev-ok','sev-warn','sev-danger'); if (sev) el.classList.add(sev); }
}
function sparklineSvg(values, color) {
  const arr = (Array.isArray(values) ? values : []).map(Number).filter((v)=>Number.isFinite(v));
  const w = 240, h = 44, p = 2;
  if (!arr.length) return '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none"><path class="spark-bg" d="M0 ' + (h-1) + ' L' + w + ' ' + (h-1) + '"/></svg>';
  const min = Math.min.apply(null, arr); const max = Math.max.apply(null, arr); const span = Math.max(1e-6, max-min);
  const pts = arr.map((v,i)=>{ const x = p + (i*(w-2*p))/Math.max(1,arr.length-1); const y = h-p - ((v-min)/span)*(h-2*p); return [x,y]; });
  const path = pts.map((pt,i)=>(i ? 'L' : 'M') + pt[0].toFixed(1) + ' ' + pt[1].toFixed(1)).join(' ');
  const area = path + ' L ' + pts[pts.length-1][0].toFixed(1) + ' ' + (h-p) + ' L ' + pts[0][0].toFixed(1) + ' ' + (h-p) + ' Z';
  const stroke = color || '#39c1ff';
  return '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' + '<path class="spark-bg" d="M0 ' + (h-1) + ' L' + w + ' ' + (h-1) + '"/>' + '<path class="spark-fill" d="' + area + '"/>' + '<path class="spark-line" style="stroke:' + stroke + '" d="' + path + '"/>' + '</svg>';
}
function setSpark(id, values, color) { const el = document.getElementById(id); if (el) el.innerHTML = sparklineSvg(values, color); }
function historyOf(s, key) { return (s && s.metric_history && Array.isArray(s.metric_history[key])) ? s.metric_history[key] : []; }
function parseDockerCompact(v) {
  const raw = String(v||'').trim(); if (!raw) return [];
  const items = raw.split(';').map((x)=>x.trim()).filter(Boolean).map((item)=>{ const parts = item.split('|'); const name = parts[0] || ''; const state = parts.length > 1 ? parts[1] : '--'; return {name:String(name), state:String(state)}; }).filter((x)=>x.name);
  const rank = (state) => {
    const s = String(state || '').toLowerCase();
    return (s.includes('up') || s.includes('running') || s.includes('healthy')) ? 0 : 1;
  };
  items.sort((a, b) => rank(a.state) - rank(b.state) || a.name.localeCompare(b.name));
  return items;
}
function parseVmCompact(v) {
  const raw = String(v || '').trim();
  if (!raw || raw === '-') return [];
  const items = raw.split(';').map((x)=>x.trim()).filter(Boolean).map((item) => {
    const parts = item.split('|');
    const stateKey = String(parts[1] || 'other').trim().toLowerCase() || 'other';
    return {
      name: String(parts[0] || ''),
      stateKey,
      vcpus: Number(parts[2] || 0) || 0,
      memMiB: Number(parts[3] || 0) || 0,
      stateLabel: String(parts[4] || parts[1] || 'Unknown'),
    };
  }).filter((x) => x.name);
  const rank = { running: 0, paused: 1, stopped: 2, other: 3 };
  items.sort((a, b) => (rank[a.stateKey] ?? 4) - (rank[b.stateKey] ?? 4) || a.name.localeCompare(b.name));
  return items;
}
function applyDockerPreviewOverrides(items) {
  return (Array.isArray(items) ? items : []).map((item) => {
    const override = espPreviewDockerOverrides[item.name];
    if (!override) return { ...item };
    return { ...item, state: override.state };
  });
}
function applyVmPreviewOverrides(items) {
  return (Array.isArray(items) ? items : []).map((item) => {
    const override = espPreviewVmOverrides[item.name];
    if (!override) return { ...item };
    return {
      ...item,
      stateKey: override.stateKey || item.stateKey,
      stateLabel: override.stateLabel || item.stateLabel,
    };
  });
}
function renderEspDockerRows(items, stateMode) {
  const list = document.getElementById('espDockerRows');
  const empty = document.getElementById('espDockerEmpty');
  if (!list || !empty) return;
  const mode = previewUiMode(lastStatusPayload);
  const pageMeta = getEspPreviewMeta('docker', lastStatusPayload);
  const rows = (Array.isArray(items) ? items : []).slice(0, 10);
  if (!rows.length) {
    list.innerHTML = '';
    const title = empty.querySelector('.esp-workload-empty-title');
    const subtitle = empty.querySelector('.esp-workload-empty-subtitle');
    const token = workloadMetricFlag(lastStatusPayload && lastStatusPayload.last_metrics, 'HATOKEN');
    const api = workloadMetricFlag(lastStatusPayload && lastStatusPayload.last_metrics, 'HADOCKAPI');
    if (mode === 'homeassistant' && token === 0) {
      if (title) title.textContent = String(pageMeta.token_missing_title || 'Token Missing');
      if (subtitle) subtitle.textContent = String(pageMeta.token_missing_subtitle || 'Supervisor token is not available to the app');
    } else if (mode === 'homeassistant' && api === 0) {
      if (title) title.textContent = String(pageMeta.api_error_title || 'Add-on API Error');
      if (subtitle) subtitle.textContent = String(pageMeta.api_error_subtitle || 'Check app logs for Supervisor API errors');
    } else {
      if (title) title.textContent = String(pageMeta.empty_title || 'No Docker Data');
      if (subtitle) subtitle.textContent = String(pageMeta.empty_subtitle || 'No containers in the latest payload');
    }
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  const iconClass = String(pageMeta.home_button_icon_class || pageMeta.tab_icon_class || 'mdi-docker');
  list.innerHTML = rows.map((item, index) => {
    return `<button class="esp-workload-row" type="button" data-esp-modal-row="docker" data-esp-index="${index}">
      <span class="mdi ${escapeHtml(iconClass)}" aria-hidden="true"></span>
      <span class="esp-workload-row-name">${escapeHtml(item.name)}</span>
    </button>`;
  }).join('');
}
function renderEspVmRows(items, stateMode) {
  const list = document.getElementById('espVmsRows');
  const empty = document.getElementById('espVmsEmpty');
  if (!list || !empty) return;
  const mode = previewUiMode(lastStatusPayload);
  const pageMeta = getEspPreviewMeta('vms', lastStatusPayload);
  const rows = (Array.isArray(items) ? items : []).slice(0, 10);
  if (!rows.length) {
    list.innerHTML = '';
    const title = empty.querySelector('.esp-workload-empty-title');
    const subtitle = empty.querySelector('.esp-workload-empty-subtitle');
    const token = workloadMetricFlag(lastStatusPayload && lastStatusPayload.last_metrics, 'HATOKEN');
    const api = workloadMetricFlag(lastStatusPayload && lastStatusPayload.last_metrics, 'HAVMSAPI');
    if (mode === 'homeassistant' && token === 0) {
      if (title) title.textContent = String(pageMeta.token_missing_title || 'Token Missing');
      if (subtitle) subtitle.textContent = String(pageMeta.token_missing_subtitle || 'Supervisor token is not available to the app');
    } else if (mode === 'homeassistant' && api === 0) {
      if (title) title.textContent = String(pageMeta.api_error_title || 'Integration API Error');
      if (subtitle) subtitle.textContent = String(pageMeta.api_error_subtitle || 'Check app logs for Core WebSocket errors');
    } else {
      if (title) title.textContent = String(pageMeta.empty_title || 'No VM Data');
      if (subtitle) subtitle.textContent = String(pageMeta.empty_subtitle || 'No virtual machines in the latest payload');
    }
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  const iconClass = String(pageMeta.home_button_icon_class || pageMeta.tab_icon_class || 'mdi-monitor-multiple');
  list.innerHTML = rows.map((item, index) => `<button class="esp-workload-row" type="button" data-esp-modal-row="vms" data-esp-index="${index}">
      <span class="mdi ${escapeHtml(iconClass)}" aria-hidden="true"></span>
      <span class="esp-workload-row-name">${escapeHtml(item.name)}</span>
    </button>`).join('');
}
function monitorDetailPayloads(s) {
  return (s && s.monitor_detail_payloads && typeof s.monitor_detail_payloads === 'object') ? s.monitor_detail_payloads : {};
}
function renderStatusListDetail(payload, detailId) {
  const prev = document.getElementById(`${detailId}PreviewList`);
  const all = document.getElementById(`${detailId}AllList`);
  const hint = document.getElementById(`${detailId}MoreHint`);
  if (!prev || !all || !hint) return;
  const items = Array.isArray(payload && payload.items) ? payload.items : [];
  const rowHtml = (it) => {
    const name = escapeHtml(String(it && it.name || '--'));
    const stateText = escapeHtml(String(it && it.state_text || '--'));
    const stateClass = escapeHtml(String(it && it.state_class || 'other'));
    return `<li><span>${name}</span><span class="docker-pill ${stateClass}">${stateText}</span></li>`;
  };
  prev.innerHTML = items.slice(0, 5).map(rowHtml).join('');
  all.innerHTML = items.map(rowHtml).join('');
  hint.textContent = String(payload && payload.hint || 'Waiting for data...');
}
function updateMonitorDetailsFromMetadata(s) {
  const payloads = monitorDetailPayloads(s);
  monitorDetailSections(s).forEach((detail) => {
    const detailId = String(detail && detail.detail_id || '').trim();
    if (!detailId) return;
    renderStatusListDetail(payloads[detailId] || null, detailId);
  });
}
function setMonitorMode(mode) {
  currentViewMode = (mode === 'monitor') ? 'monitor' : 'setup';
  document.body.classList.toggle('view-monitor', currentViewMode === 'monitor');
  try { localStorage.setItem(VIEW_MODE_KEY, currentViewMode); } catch (_) {}
  const b1 = document.getElementById('viewSetupBtn'); const b2 = document.getElementById('viewMonitorBtn');
  if (b1) b1.classList.toggle('active', currentViewMode === 'setup');
  if (b2) b2.classList.toggle('active', currentViewMode === 'monitor');
  requestLayoutSync();
}
function initViewMode() {
  try {
    const saved = localStorage.getItem(VIEW_MODE_KEY) || localStorage.getItem(VIEW_MODE_KEY_LEGACY);
    if (saved === 'monitor') setMonitorMode('monitor');
    else setMonitorMode('setup');
  } catch (_) { setMonitorMode('setup'); }
}
function integrationLabel(id) {
  const key = String(id || '').trim().toLowerCase();
  const meta = integrationDashboardMeta(lastStatusPayload, key);
  if (meta && meta.label) return String(meta.label);
  if (key === 'host_power') return 'Host Power';
  return key ? key.replace(/[_-]+/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase()) : 'Integration';
}
function integrationDashboardRows(s) {
  return Array.isArray(s && s.integration_dashboard) ? s.integration_dashboard : [];
}
function monitorDashboardGroups(s) {
  return Array.isArray(s && s.monitor_dashboard) ? s.monitor_dashboard : [];
}
function monitorDetailSections(s) {
  return Array.isArray(s && s.monitor_details) ? s.monitor_details : [];
}
function integrationDashboardMeta(s, id) {
  const target = String(id || '').trim().toLowerCase();
  if (!target) return null;
  return integrationDashboardRows(s).find((row) => String(row && row.integration_id || '').trim().toLowerCase() === target) || null;
}
function monitorDashboardCardHtml(card) {
  const cardId = String(card && card.card_id || '').trim();
  if (!cardId) return '';
  const label = escapeHtml(String(card && card.label || cardId));
  const subtext = escapeHtml(String(card && card.subtext || ''));
  const sparkKeys = Array.isArray(card && card.spark_keys) ? card.spark_keys : [];
  const sparkSvg = sparkKeys.length ? `<svg id="spark${escapeHtml(cardId)}"></svg>` : '';
  return `<div class="mcard" id="mc${escapeHtml(cardId)}">
    <div class="metric-label">${label}</div>
    <div class="metric-value" id="mv${escapeHtml(cardId)}">--</div>
    <div class="metric-sub" id="ms${escapeHtml(cardId)}">${subtext}</div>
    ${sparkSvg}
  </div>`;
}
function renderMonitorDashboardSections(s) {
  const box = document.getElementById('monitorDashboardSections');
  if (!box) return;
  const groups = monitorDashboardGroups(s);
  const signature = JSON.stringify(groups);
  if (signature === lastMonitorDashboardSignature) return;
  lastMonitorDashboardSignature = signature;
  if (!groups.length) {
    box.innerHTML = '<div class="monitor-note">Waiting for monitor dashboard metadata...</div>';
    return;
  }
  box.innerHTML = groups.map((group) => {
    const title = escapeHtml(String(group && group.title || 'Metrics'));
    const iconClass = escapeHtml(String(group && group.icon_class || 'mdi-view-dashboard-outline'));
    const spanClass = escapeHtml(String(group && group.span_class || 'span6'));
    const cards = Array.isArray(group && group.cards) ? group.cards : [];
    return `<section class="mgroup ${spanClass}">
      <h3><span class="gicon" aria-hidden="true"><span class="mdi ${iconClass}"></span></span>${title}</h3>
      <div class="mgroup-grid">${cards.map(monitorDashboardCardHtml).join('')}</div>
    </section>`;
  }).join('');
}
function renderMonitorDetailSections(s) {
  const box = document.getElementById('monitorDetailSections');
  if (!box) return;
  const details = monitorDetailSections(s);
  const signature = JSON.stringify(details);
  if (signature === lastMonitorDetailSignature) return;
  lastMonitorDetailSignature = signature;
  if (!details.length) {
    box.innerHTML = '<div class="monitor-note">Waiting for workload detail metadata...</div>';
    return;
  }
  box.innerHTML = details.map((detail) => {
    const detailId = escapeHtml(String(detail && detail.detail_id || 'detail'));
    const title = escapeHtml(String(detail && detail.title || 'Details'));
    const spanClass = escapeHtml(String(detail && detail.span_class || 'span6'));
    const waitingText = escapeHtml(String(detail && detail.waiting_text || 'Waiting for data...'));
    const showAllText = escapeHtml(String(detail && detail.show_all_text || 'Show all'));
    return `<section class="mgroup ${spanClass}">
      <h3><span class="gicon" aria-hidden="true"><span class="mdi mdi-apps"></span></span>${title}</h3>
      <div class="mgroup-grid">
        <div class="mcard">
          <div class="metric-sub" id="${detailId}MoreHint">${waitingText}</div>
          <ul class="docker-list" id="${detailId}PreviewList"></ul>
          <details><summary class="monitor-note">${showAllText}</summary><ul class="docker-list" id="${detailId}AllList"></ul></details>
        </div>
      </div>
    </section>`;
  }).join('');
}
function integrationHealthClass(row) {
  if (!row || row.enabled === false) return '';
  if (row.available === false || row.last_error) return 'danger';
  if (row.available === true) return 'ok';
  return 'warn';
}
function integrationHealthText(row) {
  if (!row) return 'Unknown';
  if (row.enabled === false) return 'Disabled';
  if (row.available === false) return 'Unavailable';
  if (row.available === true) return 'Ready';
  return 'Unknown';
}
function renderIntegrationOverview(s) {
  const overview = (s && s.integration_overview && typeof s.integration_overview === 'object') ? s.integration_overview : {};
  const cardsBox = document.getElementById('integrationDashboardCards');
  const chipsBox = document.getElementById('integrationHealthChips');
  const healthBox = document.getElementById('integrationHealthList');
  const cmdBox = document.getElementById('commandRegistryList');
  const cmdHint = document.getElementById('commandRegistryHint');
  const dashboardCards = Array.isArray(overview.dashboard_cards) ? overview.dashboard_cards : [];
  const healthChips = Array.isArray(overview.health_chips) ? overview.health_chips : [];
  const healthRows = Array.isArray(overview.health_rows) ? overview.health_rows : [];
  const commandGroups = Array.isArray(overview.command_groups) ? overview.command_groups : [];
  if (cardsBox) {
    if (!dashboardCards.length) {
      cardsBox.innerHTML = '<div class="monitor-note">Waiting for integration metadata...</div>';
    } else {
      cardsBox.innerHTML = dashboardCards.map((card) => {
        const icon = escapeHtml(String(card && card.icon_class || 'mdi-puzzle-outline'));
        const label = escapeHtml(String(card && card.label || 'Integration'));
        const sourceText = escapeHtml(String(card && card.source_text || 'Source: --'));
        const commandsText = escapeHtml(String(card && card.commands_text || '--'));
        const statusClass = escapeHtml(String(card && card.status_class || ''));
        const statusText = escapeHtml(String(card && card.status_text || 'Unknown'));
        return `<div class="integration-dashboard-card">
          <div class="integration-dashboard-head">
            <div class="integration-dashboard-title"><span class="mdi ${icon}" aria-hidden="true"></span>${label}</div>
            <span class="status-pill ${statusClass}">${statusText}</span>
          </div>
          <div class="integration-dashboard-meta">${sourceText}</div>
          <div class="integration-dashboard-meta">${commandsText}</div>
        </div>`;
      }).join('');
    }
  }
  if (chipsBox) {
    if (!healthChips.length) {
      chipsBox.innerHTML = '';
    } else {
      chipsBox.innerHTML = healthChips.map((chip) => {
        const statusClass = escapeHtml(String(chip && chip.status_class || ''));
        const text = escapeHtml(String(chip && chip.text || ''));
        return `<div class="status-pill ${statusClass}">${text}</div>`;
      }).join('');
    }
  }
  if (healthBox) {
    if (!healthRows.length) {
      healthBox.innerHTML = '<div class="monitor-note">Waiting for integration health...</div>';
    } else {
      healthBox.innerHTML = healthRows.map((row) => {
        const statusClass = escapeHtml(String(row && row.status_class || ''));
        const commandHtml = Array.isArray(row && row.commands) && row.commands.length
          ? `<div class="integration-health-tags">${row.commands.map((cmd) => `<span>${escapeHtml(String(cmd))}</span>`).join('')}</div>`
          : '';
        const errorHtml = row && row.error_text
          ? `<div class="integration-health-error">Last error: ${escapeHtml(String(row.error_text))}</div>`
          : '';
        return `<div class="integration-health-row">
          <div class="integration-health-head">
            <div class="integration-health-title">${escapeHtml(String(row && row.title || 'Integration'))}</div>
            <span class="status-pill ${statusClass}">${escapeHtml(String(row && row.status_text || 'Unknown'))}</span>
          </div>
          <div class="integration-health-meta">${escapeHtml(String(row && row.source_text || 'Source: --'))}</div>
          <div class="integration-health-meta">${escapeHtml(String(row && row.refresh_text || 'Refreshed --'))} • ${escapeHtml(String(row && row.success_text || 'Last success --'))}</div>
          ${errorHtml}
          ${commandHtml}
        </div>`;
      }).join('');
    }
  }

  if (cmdHint) {
    cmdHint.textContent = String(overview.command_hint || 'Waiting for command registry...');
  }
  if (cmdBox) {
    if (!commandGroups.length) {
      cmdBox.innerHTML = '<div class="monitor-note">Waiting for command registry...</div>';
    } else {
      cmdBox.innerHTML = commandGroups.map((group) => {
        const ownerTitle = String(group && group.title || 'Commands');
        const ownerIcon = group && group.icon_class ? `mdi ${escapeHtml(String(group.icon_class))}` : '';
        const rowsHtml = (Array.isArray(group && group.rows) ? group.rows : []).map((entry) => {
          const patterns = String(entry && entry.patterns_text || '--');
          const destructive = entry && entry.destructive ? '<span class="command-registry-flag">destructive</span>' : '';
          const label = String(entry && (entry.label || entry.command_id) || '--');
          return `<div class="command-registry-row">
            <div class="command-registry-title">${escapeHtml(label)} ${destructive}</div>
            <div class="command-registry-meta">${escapeHtml(patterns)}</div>
          </div>`;
        }).join('');
        return `<div class="command-registry-group">
          <div class="command-registry-owner">${ownerIcon ? `<span class="${ownerIcon}" aria-hidden="true"></span>` : ''}${escapeHtml(ownerTitle)}</div>
          ${rowsHtml}
        </div>`;
      }).join('');
    }
  }
}
function metricNumber(metrics, key) {
  if (!metrics || !Object.prototype.hasOwnProperty.call(metrics, key) || metrics[key] === '') return null;
  const n = Number(metrics[key]);
  return Number.isFinite(n) ? n : null;
}
function monitorCardSeverity(kind, values) {
  const primary = Number(values && values.primary);
  const secondary = Number(values && values.secondary);
  switch (String(kind || '')) {
    case 'cpu_pct':
      if (!Number.isFinite(primary)) return null;
      return primary >= 90 ? 'sev-danger' : primary >= 70 ? 'sev-warn' : 'sev-ok';
    case 'mem_pct':
      if (!Number.isFinite(primary)) return null;
      return primary >= 90 ? 'sev-danger' : primary >= 75 ? 'sev-warn' : 'sev-ok';
    case 'cpu_temp':
      if (!Number.isFinite(primary)) return null;
      return primary >= 85 ? 'sev-danger' : primary >= 75 ? 'sev-warn' : 'sev-ok';
    case 'traffic_pair':
    case 'disk_io_pair':
      return ((primary || 0) + (secondary || 0)) > 50000 ? 'sev-warn' : 'sev-ok';
    case 'disk_temp':
      if (!Number.isFinite(primary)) return null;
      return primary >= 55 ? 'sev-danger' : primary >= 48 ? 'sev-warn' : 'sev-ok';
    case 'disk_usage':
      if (!Number.isFinite(primary)) return null;
      return primary >= 92 ? 'sev-danger' : primary >= 80 ? 'sev-warn' : 'sev-ok';
    case 'gpu_util':
      if (!Number.isFinite(primary)) return null;
      return primary >= 95 ? 'sev-danger' : primary >= 80 ? 'sev-warn' : 'sev-ok';
    case 'gpu_temp':
      if (!Number.isFinite(primary)) return null;
      return primary >= 85 ? 'sev-danger' : primary >= 75 ? 'sev-warn' : 'sev-ok';
    case 'gpu_mem':
      if (!Number.isFinite(primary)) return null;
      return primary >= 90 ? 'sev-danger' : primary >= 75 ? 'sev-warn' : 'sev-ok';
    case 'docker_counts':
      return Number(values && values.tertiary || 0) > 0 ? 'sev-warn' : 'sev-ok';
    case 'always_ok':
      return 'sev-ok';
    default:
      return null;
  }
}
function monitorCardSparkValues(s, card) {
  const keys = Array.isArray(card && card.spark_keys) ? card.spark_keys : [];
  if (!keys.length) return [];
  if (keys.length === 1) return historyOf(s, keys[0]);
  const series = keys.map((key) => historyOf(s, key));
  const size = Math.max(...series.map((items) => items.length), 0);
  return Array.from({ length: size }, (_, index) => series.reduce((sum, items) => sum + Number(items[index] || 0), 0));
}
function monitorCardViewModel(card, metrics, workloadMode) {
  const primary = metricNumber(metrics, card.metric_key);
  const secondary = metricNumber(metrics, card.secondary_metric_key);
  const tertiary = metricNumber(metrics, card.tertiary_metric_key);
  const values = { primary, secondary, tertiary };
  const subtextFallback = String(card && card.subtext || '');
  switch (String(card && card.render_kind || '')) {
    case 'percent_one_decimal':
      return {
        valueText: primary !== null ? `${primary.toFixed(1)}%` : '--',
        subText: primary !== null ? subtextFallback : 'Waiting for telemetry',
        sev: monitorCardSeverity(card && card.severity_kind, values),
      };
    case 'temp_one_decimal':
      return {
        valueText: primary !== null ? `${primary.toFixed(1)}°C` : '--',
        subText: subtextFallback || 'Temperature',
        sev: monitorCardSeverity(card && card.severity_kind, values),
      };
    case 'uptime':
      return {
        valueText: primary !== null ? fmtUptimeSec(primary) : '--',
        subText: primary !== null ? `${Math.round(primary)}s total` : 'Waiting for telemetry',
        sev: monitorCardSeverity(card && card.severity_kind, values),
      };
    case 'pair_round':
      return {
        valueText: (primary !== null || secondary !== null) ? `${primary !== null ? Math.round(primary) : '...'} / ${secondary !== null ? Math.round(secondary) : '...'}` : '--',
        subText: subtextFallback,
        sev: monitorCardSeverity(card && card.severity_kind, values),
      };
    case 'disk_temp_usage':
      return {
        valueText: primary !== null ? `${primary.toFixed(1)}°C` : '--',
        subText: secondary !== null ? `${secondary.toFixed(1)}% used` : (subtextFallback || 'Temperature / Usage'),
        sev: monitorCardSeverity(card && card.severity_kind, values),
      };
    case 'integer':
      return {
        valueText: primary !== null ? `${Math.round(primary)}` : '--',
        subText: subtextFallback,
        sev: monitorCardSeverity(card && card.severity_kind, values),
      };
    case 'integer_percent':
      return {
        valueText: primary !== null ? `${Math.round(primary)}%` : '--',
        subText: subtextFallback,
        sev: monitorCardSeverity(card && card.severity_kind, values),
      };
    case 'docker_counts':
      return {
        valueText: `${metrics.DOCKRUN ?? '--'} / ${metrics.DOCKSTOP ?? '--'} / ${metrics.DOCKUNH ?? '--'}`,
        subText: subtextFallback,
        sev: monitorCardSeverity(card && card.severity_kind, { primary: metrics.DOCKRUN, secondary: metrics.DOCKSTOP, tertiary: metrics.DOCKUNH }),
      };
    case 'vm_counts':
      return {
        valueText: workloadMode === 'homeassistant'
          ? `${metrics.VMSRUN ?? '--'}`
          : `${metrics.VMSRUN ?? '--'} / ${metrics.VMSPAUSE ?? '--'} / ${metrics.VMSSTOP ?? '--'} / ${metrics.VMSOTHER ?? '--'}`,
        subText: subtextFallback,
        sev: monitorCardSeverity(card && card.severity_kind, values),
      };
    default:
      return {
        valueText: primary !== null ? String(primary) : '--',
        subText: subtextFallback,
        sev: monitorCardSeverity(card && card.severity_kind, values),
      };
  }
}
function updateMonitorCardsFromMetadata(s, workloadMode) {
  const metrics = (s && s.last_metrics && typeof s.last_metrics === 'object') ? s.last_metrics : {};
  monitorDashboardGroups(s).forEach((group) => {
    const cards = Array.isArray(group && group.cards) ? group.cards : [];
    cards.forEach((card) => {
      const view = monitorCardViewModel(card, metrics, workloadMode);
      setMetricCard(String(card.card_id || ''), view.valueText, view.subText, view.sev);
      const sparkColor = String(card && card.spark_color || '').trim();
      const sparkValues = monitorCardSparkValues(s, card);
      if (sparkColor && sparkValues.length) setSpark(`spark${String(card.card_id || '')}`, sparkValues, sparkColor);
      else if (sparkColor) setSpark(`spark${String(card.card_id || '')}`, [], sparkColor);
    });
  });
}
function updateMonitorDashboard(s) {
  if (!s || typeof s !== 'object') return;
  const workloadMode = previewUiMode(s);
  renderMonitorDashboardSections(s);
  renderMonitorDetailSections(s);
  const m = (s.last_metrics && typeof s.last_metrics === 'object') ? s.last_metrics : {};
  updateSummaryBarFromMetadata(s, workloadMode);
  updateMonitorCardsFromMetadata(s, workloadMode);
  updateMonitorDetailsFromMetadata(s);
  renderIntegrationOverview(s);
  updateEspPreview(s);
}
function updateEspPreview(s) {
  const m = (s && s.last_metrics && typeof s.last_metrics === 'object') ? s.last_metrics : {};
  const cs = (s && s.comm_status && typeof s.comm_status === 'object') ? s.comm_status : {};
  const num = (k) => {
    if (!Object.prototype.hasOwnProperty.call(m, k)) return null;
    const n = Number(m[k]);
    return Number.isFinite(n) ? n : null;
  };
  const cpu = num('CPU'), mem = num('MEM'), temp = num('TEMP');
  const rx = num('RX'), tx = num('TX'), diskPct = num('DISKPCT'), diskTemp = num('DISK');
  const gpuUtil = num('GPUU'), gpuTemp = num('GPUT');
  const up = num('UP');
  const dockRun = m.DOCKRUN ?? '--', dockStop = m.DOCKSTOP ?? '--';
  const vmRun = m.VMSRUN ?? '--', vmPause = m.VMSPAUSE ?? '--', vmStop = m.VMSSTOP ?? '--';
  const power = String(m.POWER || 'RUNNING');
  const serialPort = (s && s.config && s.config.serial_port) ? String(s.config.serial_port) : '';
  const lastMetricsAge = Number(s && s.last_metrics_age_s);
  const telemetryStale = Number.isFinite(lastMetricsAge) && lastMetricsAge > 15;
  const brightness = 255;

  const rxHistRaw = historyOf(s, 'RX');
  const txHistRaw = historyOf(s, 'TX');
  const netScale = pickNetScaleKbps([...rxHistRaw, ...txHistRaw, rx, tx]);
  const rxHist = scaleHistoryToPct(rxHistRaw, netScale);
  const txHist = scaleHistoryToPct(txHistRaw, netScale);
  const cpuHist = historyOf(s,'CPU');
  const memHist = historyOf(s,'MEM');
  const cpuTempHist = historyOf(s,'TEMP');
  const diskTempHist = historyOf(s,'DISK');
  const diskUsageHist = historyOf(s,'DISKPCT');
  const gpuUtilHist = historyOf(s,'GPUU');
  const gpuTempHist = historyOf(s,'GPUT');
  const host = (s && typeof s.host_name === 'string') ? s.host_name.trim() : '';

  metricText('espNetRxVal', rx !== null ? fmtEspMBps(rx) : '--');
  metricText('espNetTxVal', tx !== null ? fmtEspMBps(tx) : '--');
  const netGraphEl = document.getElementById('espNetGraph');
  const netLoadingEl = document.getElementById('espNetLoading');
  const netScaleEl = document.getElementById('espNetScale');
  if (netGraphEl) netGraphEl.innerHTML = espDualGraphSvg(rxHist, txHist);
  if (netLoadingEl) netLoadingEl.textContent = '';
  if (netScaleEl) netScaleEl.textContent = fmtNetScaleLabel(netScale);

  metricText('espSysCpuVal', cpu !== null ? `${Math.round(cpu)}` : '--');
  metricText('espSysMemVal', mem !== null ? `${Math.round(mem)}` : '--');
  const sysGraphEl = document.getElementById('espSysGraph');
  const sysGraphLoading = document.getElementById('espSysLoading');
  if (sysGraphEl) sysGraphEl.innerHTML = espDualGraphSvg(cpuHist, memHist);
  if (sysGraphLoading) sysGraphLoading.textContent = '';

  metricText('espCpuTempVal', temp !== null ? `${Math.round(temp)}` : '--');
  const cpuTempGraphEl = document.getElementById('espCpuTempGraph');
  const cpuTempLoadingEl = document.getElementById('espCpuTempLoading');
  if (cpuTempGraphEl) cpuTempGraphEl.innerHTML = espSingleGraphSvg(cpuTempHist, '#38BDF8');
  if (cpuTempLoadingEl) cpuTempLoadingEl.textContent = '';

  metricText('espDiskTempVal', diskTemp !== null ? `${Math.round(diskTemp)}` : '--');
  const diskTempGraphEl = document.getElementById('espDiskTempGraph');
  const diskTempLoadingEl = document.getElementById('espDiskTempLoading');
  if (diskTempGraphEl) diskTempGraphEl.innerHTML = espSingleGraphSvg(diskTempHist, '#A855F7');
  if (diskTempLoadingEl) diskTempLoadingEl.textContent = '';

  metricText('espDiskUsageVal', diskPct !== null ? `${Math.round(diskPct)}` : '--');
  const diskUsageGraphEl = document.getElementById('espDiskUsageGraph');
  const diskUsageLoadingEl = document.getElementById('espDiskUsageLoading');
  if (diskUsageGraphEl) diskUsageGraphEl.innerHTML = espSingleGraphSvg(diskUsageHist, '#38BDF8');
  if (diskUsageLoadingEl) diskUsageLoadingEl.textContent = '';

  metricText('espGpuUtilVal', gpuUtil !== null ? `${Math.round(gpuUtil)}` : '--');
  metricText('espGpuTempVal', gpuTemp !== null ? `${Math.round(gpuTemp)}` : '--');
  const gpuGraphEl = document.getElementById('espGpuGraph');
  const gpuLoadingEl = document.getElementById('espGpuLoading');
  if (gpuGraphEl) gpuGraphEl.innerHTML = espDualGraphSvg(gpuUtilHist, gpuTempHist);
  if (gpuLoadingEl) gpuLoadingEl.textContent = '';

  metricText('espUptimeVal', up !== null ? fmtEspUptime(up) : '--');
  const hostNameVal = document.getElementById('espHostNameVal');
  if (hostNameVal) {
    hostNameVal.textContent = host || 'Waiting for host...';
    hostNameVal.classList.toggle('is-empty', !host);
  }

  metricText('espBrightnessVal', String(brightness));
  setEspSliderValue('espBrightnessFill', 'espBrightnessKnob', brightness, 255);

  espPreviewDockerItems = applyDockerPreviewOverrides(parseDockerCompact(m.DOCKER));
  espPreviewVmItems = applyVmPreviewOverrides(parseVmCompact(m.VMS));
  renderEspDockerRows(espPreviewDockerItems, telemetryStale ? 'stale' : 'live');
  renderEspVmRows(espPreviewVmItems, telemetryStale ? 'stale' : 'live');

  metricText('espFooterPort', '');
  refreshEspPreviewChrome();
  refreshEspPreviewActiveModal();
}

async function pollLogs() {
  try {
    const r = await fetch(`/api/logs?since=${nextLogId}`);
    const data = await r.json();
    for (const row of data.lines) { mainLogRows.push(row); nextLogId = row.id + 1; }
    renderMainLogs();
  } catch (_) {}
}
function isMetricLogRowText(text) {
  const t = String(text || '');
  return /\b[A-Z][A-Z0-9_]*=.*\bPOWER=/.test(t);
}
function renderMainLogs() {
  const box = document.getElementById('logs');
  if (!box) return;
  const atBottom = Math.abs((box.scrollHeight - box.clientHeight) - box.scrollTop) < 8;
  let rows = mainLogRows;
  if (hideMetricLogs) rows = rows.filter((r)=> !isMetricLogRowText(r && r.text));
  if (!rows.length) {
    box.textContent = 'No logs yet. Start the agent or click Refresh to load recent output.';
  } else {
    box.textContent = rows.map((r)=> String((r && r.text) || '')).join('');
  }
  if (atBottom) box.scrollTop = box.scrollHeight;
}
async function pollCommLogs() {
  try {
    const r = await fetch(`/api/comm-logs?since=${nextCommLogId}`);
    const data = await r.json();
    const box = document.getElementById('commLogs');
    if (!box) return;
    if (box.textContent === 'No communication events yet. Serial disconnects/reconnects will appear here.') box.textContent = '';
    for (const row of data.lines) { box.textContent += row.text; nextCommLogId = row.id + 1; }
    box.scrollTop = box.scrollHeight;
  } catch (_) {}
}
function setResult(el, text, isError) {
  if (!el) return;
  el.textContent = text;
  el.style.color = isError ? 'var(--danger)' : '';
}
function setSensorChip(chipId, mode, text) {
  const el = document.getElementById(chipId);
  if (!el) return;
  el.classList.remove('auto', 'detected', 'missing');
  el.classList.add(mode || 'auto');
  el.textContent = text || 'Auto';
}
function currentSelectValues(selectEl, includeSynthetic = true) {
  if (!selectEl) return [];
  return Array.from(selectEl.options || [])
    .filter((o)=> includeSynthetic || !(o.dataset && o.dataset.synthetic))
    .map((o)=>String(o.value || '').trim())
    .filter(Boolean);
}
function updateSensorValidationChips() {
  const cpuInput = document.getElementById('cpuTempSensorInput');
  const fanInput = document.getElementById('fanSensorInput');
  const cpuSel = document.getElementById('cpuTempSensorSelect');
  const fanSel = document.getElementById('fanSensorSelect');

  const cpuVal = cpuInput ? String(cpuInput.value || '').trim() : '';
  const fanVal = fanInput ? String(fanInput.value || '').trim() : '';
  const cpuChoices = new Set(currentSelectValues(cpuSel, false));
  const fanChoices = new Set(currentSelectValues(fanSel, false));

  if (!cpuVal) setSensorChip('cpuTempSensorChip', 'auto', 'Auto');
  else if (cpuChoices.has(cpuVal)) setSensorChip('cpuTempSensorChip', 'detected', 'Detected');
  else setSensorChip('cpuTempSensorChip', 'missing', 'Not detected');

  if (!fanVal) setSensorChip('fanSensorChip', 'auto', 'Auto');
  else if (fanChoices.has(fanVal)) setSensorChip('fanSensorChip', 'detected', 'Detected');
  else setSensorChip('fanSensorChip', 'missing', 'Not detected');
}
function updateSerialPortValidationChip() {
  const input = document.getElementById('serialPortInput');
  const sel = document.getElementById('serialPortsSelect');
  const val = input ? String(input.value || '').trim() : '';
  const choices = new Set(currentSelectValues(sel, false));
  if (!val) setSensorChip('serialPortChip', 'auto', 'Auto');
  else if (choices.has(val)) setSensorChip('serialPortChip', 'detected', 'Detected');
  else setSensorChip('serialPortChip', 'missing', 'Not detected');
}
function fillSelect(selectEl, items, emptyLabel) {
  if (!selectEl) return;
  selectEl.innerHTML = '';
  const rows = Array.isArray(items) ? items : [];
  if (!rows.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = emptyLabel;
    selectEl.appendChild(opt);
    return;
  }
  for (const item of rows) {
    const opt = document.createElement('option');
    opt.value = String(item || '');
    opt.textContent = String(item || '');
    selectEl.appendChild(opt);
  }
}
function syncSavedSelectOptions(selectEl, values, selectedValue) {
  if (!selectEl) return;
  Array.from(selectEl.options || []).forEach((opt) => {
    if (opt.dataset && opt.dataset.synthetic === 'saved') opt.remove();
  });
  const normalized = [];
  const seen = new Set();
  const source = Array.isArray(values) ? values : [values];
  for (const raw of source) {
    const value = String(raw || '').trim();
    if (!value || seen.has(value)) continue;
    seen.add(value);
    normalized.push(value);
  }
  const existing = currentSelectValues(selectEl);
  for (let i = normalized.length - 1; i >= 0; i -= 1) {
    const value = normalized[i];
    if (existing.includes(value)) continue;
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = `${value} (saved)`;
    opt.dataset.synthetic = 'saved';
    selectEl.insertBefore(opt, selectEl.firstChild);
  }
  const preferred = String(selectedValue || '').trim();
  if (preferred) {
    selectEl.value = preferred;
    return;
  }
  if (normalized.length === 1) selectEl.value = normalized[0];
}
function getConfiguredInterfaceValue() {
  const input = document.getElementById('ifaceInput');
  return input ? String(input.value || '').trim() : '';
}
function syncInterfaceSelection(preferredValue) {
  const sel = document.getElementById('ifaceSelect');
  if (!sel) return;
  const value = String(preferredValue || '').trim();
  if (!value) {
    syncSavedSelectOptions(sel, [], '');
    sel.value = '';
    return;
  }
  syncSavedSelectOptions(sel, value, value);
}
function getConfiguredSerialPortValue() {
  const input = document.getElementById('serialPortInput');
  return input ? String(input.value || '').trim() : '';
}
function syncSerialPortSelection(preferredValue) {
  const sel = document.getElementById('serialPortsSelect');
  if (!sel) return;
  const value = String(preferredValue || '').trim();
  if (!value) {
    syncSavedSelectOptions(sel, [], '');
    sel.value = '';
    return;
  }
  syncSavedSelectOptions(sel, value, value);
}
function getConfiguredDiskValues() {
  const diskInput = document.getElementById('diskDeviceInput');
  const tempInput = document.getElementById('diskTempDeviceInput');
  const diskValue = diskInput ? String(diskInput.value || '').trim() : '';
  const tempValue = tempInput ? String(tempInput.value || '').trim() : '';
  return {
    diskValue,
    tempValue,
    values: [diskValue, tempValue].filter(Boolean),
    selectedValue: diskValue || tempValue || '',
  };
}
function syncDiskSelection() {
  const sel = document.getElementById('diskDeviceSelect');
  if (!sel) return;
  const cfg = getConfiguredDiskValues();
  syncSavedSelectOptions(sel, cfg.values, cfg.selectedValue);
}
function getConfiguredCpuSensorValue() {
  const input = document.getElementById('cpuTempSensorInput');
  return input ? String(input.value || '').trim() : '';
}
function syncCpuSensorSelection(preferredValue) {
  const sel = document.getElementById('cpuTempSensorSelect');
  if (!sel) return;
  const value = String(preferredValue || '').trim();
  if (!value) {
    syncSavedSelectOptions(sel, [], '');
    sel.value = '';
    return;
  }
  syncSavedSelectOptions(sel, value, value);
}
function getConfiguredFanSensorValue() {
  const input = document.getElementById('fanSensorInput');
  return input ? String(input.value || '').trim() : '';
}
function syncFanSensorSelection(preferredValue) {
  const sel = document.getElementById('fanSensorSelect');
  if (!sel) return;
  const value = String(preferredValue || '').trim();
  if (!value) {
    syncSavedSelectOptions(sel, [], '');
    sel.value = '';
    return;
  }
  syncSavedSelectOptions(sel, value, value);
}
async function fetchHardwareChoices() {
  const r = await fetch('/api/hardware-choices');
  return await r.json();
}
async function refreshInterfaceChoices() {
  const btn = document.getElementById('refreshIfaceBtn');
  const sel = document.getElementById('ifaceSelect');
  const result = document.getElementById('ifaceResult');
  if (!btn || !sel || !result) return;
  btn.disabled = true;
  setResult(result, 'Refreshing...');
  try {
    const data = await fetchHardwareChoices();
    const rows = data && Array.isArray(data.network_ifaces) ? data.network_ifaces : [];
    fillSelect(sel, rows, '(no interfaces found)');
    const configured = getConfiguredInterfaceValue();
    syncInterfaceSelection(configured);
    if (configured) {
      const detected = rows.includes(configured);
      setResult(
        result,
        detected
          ? `Found ${rows.length} interface(s). Saved interface ${configured} selected.`
          : `Found ${rows.length} interface(s). Saved interface ${configured} is not currently detected.`,
        !detected
      );
    } else {
      setResult(result, rows.length ? `Found ${rows.length} interface(s)` : 'No interfaces detected');
    }
  } catch (_) {
    setResult(result, 'Failed to load interfaces', true);
  } finally {
    btn.disabled = false;
    updateSensorValidationChips();
  }
}
async function refreshDiskChoices() {
  const btn = document.getElementById('refreshDiskBtn');
  const sel = document.getElementById('diskDeviceSelect');
  const result = document.getElementById('diskResult');
  if (!btn || !sel || !result) return;
  btn.disabled = true;
  setResult(result, 'Refreshing...');
  try {
    const data = await fetchHardwareChoices();
    const rows = data && Array.isArray(data.disk_devices) ? data.disk_devices : [];
    fillSelect(sel, rows, '(no disk devices found)');
    const cfg = getConfiguredDiskValues();
    syncDiskSelection();
    if (cfg.values.length) {
      const missing = cfg.values.filter((value) => !rows.includes(value));
      const savedSummary = [];
      if (cfg.diskValue) savedSummary.push(`disk=${cfg.diskValue}`);
      if (cfg.tempValue && cfg.tempValue !== cfg.diskValue) savedSummary.push(`temp=${cfg.tempValue}`);
      setResult(
        result,
        missing.length
          ? `Found ${rows.length} disk device(s). Saved ${savedSummary.join(', ')} is not fully detected.`
          : `Found ${rows.length} disk device(s). Saved ${savedSummary.join(', ')} selected.`,
        missing.length > 0
      );
    } else {
      setResult(result, rows.length ? `Found ${rows.length} disk device(s)` : 'No disk devices detected');
    }
  } catch (_) {
    setResult(result, 'Failed to load disk devices', true);
  } finally {
    btn.disabled = false;
    updateSensorValidationChips();
  }
}
async function refreshCpuSensorChoices() {
  const btn = document.getElementById('refreshCpuTempSensorBtn');
  const sel = document.getElementById('cpuTempSensorSelect');
  const result = document.getElementById('cpuTempSensorResult');
  if (!btn || !sel || !result) return;
  btn.disabled = true;
  setResult(result, 'Refreshing...');
  try {
    const data = await fetchHardwareChoices();
    const rows = data && Array.isArray(data.cpu_temp_sensors) ? data.cpu_temp_sensors : [];
    fillSelect(sel, rows, '(no CPU temp sensors found)');
    const configured = getConfiguredCpuSensorValue();
    syncCpuSensorSelection(configured);
    if (configured) {
      const detected = rows.includes(configured);
      setResult(
        result,
        detected
          ? `Found ${rows.length} CPU temp sensor(s). Saved sensor ${configured} selected.`
          : `Found ${rows.length} CPU temp sensor(s). Saved sensor ${configured} is not currently detected.`,
        !detected
      );
    } else {
      setResult(result, rows.length ? `Found ${rows.length} CPU temp sensor(s)` : 'No CPU temp sensors detected');
    }
  } catch (_) {
    setResult(result, 'Failed to load CPU temp sensors', true);
  } finally {
    btn.disabled = false;
    updateSensorValidationChips();
  }
}
async function refreshFanSensorChoices() {
  const btn = document.getElementById('refreshFanSensorBtn');
  const sel = document.getElementById('fanSensorSelect');
  const result = document.getElementById('fanSensorResult');
  if (!btn || !sel || !result) return;
  btn.disabled = true;
  setResult(result, 'Refreshing...');
  try {
    const data = await fetchHardwareChoices();
    const rows = data && Array.isArray(data.fan_sensors) ? data.fan_sensors : [];
    fillSelect(sel, rows, '(no fan sensors found)');
    const configured = getConfiguredFanSensorValue();
    syncFanSensorSelection(configured);
    if (configured) {
      const detected = rows.includes(configured);
      setResult(
        result,
        detected
          ? `Found ${rows.length} fan sensor(s). Saved sensor ${configured} selected.`
          : `Found ${rows.length} fan sensor(s). Saved sensor ${configured} is not currently detected.`,
        !detected
      );
    } else {
      setResult(result, rows.length ? `Found ${rows.length} fan sensor(s)` : 'No fan sensors detected');
    }
  } catch (_) {
    setResult(result, 'Failed to load fan sensors', true);
  } finally {
    btn.disabled = false;
    updateSensorValidationChips();
  }
}
function copySelected(selectId, inputId, resultId, noun) {
  const sel = document.getElementById(selectId);
  const input = document.getElementById(inputId);
  const result = document.getElementById(resultId);
  if (!sel || !input) return;
  if (!sel.value) {
    setResult(result, `Select a ${noun} first`, true);
    return;
  }
  input.value = sel.value;
  setResult(result, `Copied selected ${noun}`);
  updateSensorValidationChips();
}
function copyDiskSelection(mode) {
  const sel = document.getElementById('diskDeviceSelect');
  const disk = document.getElementById('diskDeviceInput');
  const temp = document.getElementById('diskTempDeviceInput');
  const result = document.getElementById('diskResult');
  if (!sel || !disk || !temp) return;
  if (!sel.value) {
    setResult(result, 'Select a disk device first', true);
    return;
  }
  if (mode === 'disk' || mode === 'both') disk.value = sel.value;
  if (mode === 'temp' || mode === 'both') temp.value = sel.value;
  if (mode === 'both') setResult(result, 'Copied selected disk to both fields');
  else if (mode === 'temp') setResult(result, 'Copied selected disk to disk_temp_device');
  else setResult(result, 'Copied selected disk to disk_device');
}

async function refreshSerialPorts() {
  const sel = document.getElementById('serialPortsSelect');
  const result = document.getElementById('portsResult');
  const btn = document.getElementById('refreshPortsBtn');
  if (!sel || !result || !btn) return;
  result.style.color = '';
  result.textContent = 'Refreshing...';
  btn.disabled = true;
  try {
    const r = await fetch('/api/ports');
    const data = await r.json();
    const ports = (data && Array.isArray(data.ports)) ? data.ports : [];
    fillSelect(sel, ports, '(no serial ports found)');
    const configured = getConfiguredSerialPortValue();
    syncSerialPortSelection(configured);
    if (configured) {
      const detected = ports.includes(configured);
      setResult(
        result,
        detected
          ? `Found ${ports.length} port(s). Saved port ${configured} selected.`
          : `Found ${ports.length} port(s). Saved port ${configured} is not currently detected.`,
        !detected
      );
    } else {
      setResult(result, ports.length ? `Found ${ports.length} port(s)` : 'No ports detected');
    }
  } catch (_) {
    setResult(result, 'Failed to load ports', true);
  } finally {
    btn.disabled = false;
    updateSerialPortValidationChip();
  }
}
function useSelectedPort() {
  const sel = document.getElementById('serialPortsSelect');
  const input = document.getElementById('serialPortInput');
  const result = document.getElementById('portsResult');
  if (!sel || !input) return;
  if (!sel.value) {
    if (result) {
      result.textContent = 'Select a port first';
      result.style.color = 'var(--danger)';
    }
    return;
  }
  input.value = sel.value;
  if (result) {
    result.textContent = 'Copied selected port to serial_port';
    result.style.color = 'var(--accent)';
  }
  updateSerialPortValidationChip();
}
async function testSerialPort() {
  const result = document.getElementById('testSerialResult');
  const btn = document.getElementById('testSerialBtn');
  const portEl = document.getElementById('serialPortInput');
  const baudEl = document.getElementById('baudInput');
  if (!result || !btn || !portEl || !baudEl) return;
  result.style.color = '';
  result.textContent = 'Testing...';
  btn.disabled = true;
  try {
    const r = await fetch('/api/test-serial', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ port: portEl.value, baud: Number(baudEl.value || 115200) })
    });
    const data = await r.json();
    result.textContent = (data && data.message) ? data.message : (r.ok ? 'Port opened' : 'Port test failed');
    result.style.color = r.ok ? 'var(--accent)' : 'var(--danger)';
  } catch (_) {
    result.textContent = 'Port test error';
    result.style.color = 'var(--danger)';
  } finally {
    btn.disabled = false;
  }
}
async function previewHostPowerCommands() {
  const btn = document.getElementById('previewHostPowerBtn');
  const box = document.getElementById('hostPowerPreviewBox');
  const shutdownEl = document.getElementById('shutdownCmdInput');
  const restartEl = document.getElementById('restartCmdInput');
  const useSudoEl = document.querySelector('input[name="host_cmd_use_sudo"]');
  if (!btn || !box || !shutdownEl || !restartEl) return;
  btn.disabled = true;
  box.textContent = 'Loading preview...';
  try {
    const r = await fetch('/api/host-power-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        shutdown_cmd: shutdownEl.value,
        restart_cmd: restartEl.value,
        host_cmd_use_sudo: !!(useSudoEl && useSudoEl.checked),
      }),
    });
    const data = await r.json();
    const items = Array.isArray(data && data.items) ? data.items : [];
    if (!items.length) {
      box.textContent = 'No host power commands registered.';
      return;
    }
    box.textContent = items.map((item) => {
      const trigger = String((item && item.trigger) || (item && item.command_id) || 'command');
      const resolved = item && item.ok ? item.command : (item && item.message) || 'not available';
      return `CMD=${trigger} -> ${resolved}`;
    }).join('\n');
  } catch (_) {
    box.textContent = 'Failed to load preview';
  } finally {
    btn.disabled = false;
  }
}

async function detectHostPowerDefaults() {
  const btn = document.getElementById('detectHostPowerBtn');
  const shutdownEl = document.getElementById('shutdownCmdInput');
  const restartEl = document.getElementById('restartCmdInput');
  const result = document.getElementById('hostPowerDetectResult');
  if (!btn || !shutdownEl || !restartEl || !result) return;
  result.style.color = '';
  result.textContent = 'Detecting...';
  btn.disabled = true;
  try {
    const r = await fetch('/api/host-power-defaults');
    const data = await r.json();
    const items = Array.isArray(data && data.items) ? data.items : [];
    const byId = Object.create(null);
    for (const item of items) {
      if (!item || typeof item.command_id !== 'string') continue;
      byId[item.command_id] = item;
    }
    if (byId.host_shutdown && typeof byId.host_shutdown.default_command === 'string') shutdownEl.value = byId.host_shutdown.default_command;
    else if (data && typeof data.shutdown_cmd === 'string') shutdownEl.value = data.shutdown_cmd;
    if (byId.host_restart && typeof byId.host_restart.default_command === 'string') restartEl.value = byId.host_restart.default_command;
    else if (data && typeof data.restart_cmd === 'string') restartEl.value = data.restart_cmd;
    const osName = (data && data.os) ? data.os : 'host';
    const loadedCount = items.filter((item) => item && typeof item.default_command === 'string' && item.default_command).length;
    if ((shutdownEl.value || restartEl.value)) {
      result.textContent = `Loaded ${loadedCount || 0} registered host power defaults for ${osName}`;
      result.style.color = 'var(--accent)';
    } else {
      result.textContent = `No defaults available for ${osName}`;
      result.style.color = 'var(--danger)';
    }
  } catch (_) {
    result.textContent = 'Failed to detect host power commands';
    result.style.color = 'var(--danger)';
  } finally {
    btn.disabled = false;
  }
}

async function clearLogs() {
  const btn = document.getElementById('clearLogsBtn');
  const box = document.getElementById('logs');
  if (!btn || !box) return;
  btn.disabled = true;
  try {
    const r = await fetch('/api/logs/clear', { method: 'POST' });
    if (r.ok) {
      mainLogRows = [];
      renderMainLogs();
      nextLogId = 1;
    }
  } catch (_) {
  } finally {
    btn.disabled = false;
  }
}

function downloadLogs() {
  window.location.href = '/api/logs/text';
}
function initMainLogsBuffer() {
  const box = document.getElementById('logs');
  if (!box) return;
  const txt = String(box.textContent || '');
  if (!txt || txt === 'No logs yet. Start the agent or click Refresh to load recent output.') {
    mainLogRows = [];
    return;
  }
  const parts = txt.match(/[^\n]*\n|[^\n]+$/g) || [];
  mainLogRows = parts.map((t, i)=>({ id: -(parts.length - i), text: t }));
  renderMainLogs();
}
function toggleHideMetricLogs() {
  const chk = document.getElementById('hideMetricLogsChk');
  hideMetricLogs = !!(chk && chk.checked);
  try { localStorage.setItem(HIDE_METRIC_LOGS_KEY, hideMetricLogs ? '1' : '0'); } catch (_) {}
  renderMainLogs();
}
function initHideMetricLogs() {
  try {
    const v = localStorage.getItem(HIDE_METRIC_LOGS_KEY) || localStorage.getItem(HIDE_METRIC_LOGS_KEY_LEGACY);
    hideMetricLogs = (v === '1');
  } catch (_) {
    hideMetricLogs = false;
  }
  const chk = document.getElementById('hideMetricLogsChk');
  if (chk) {
    chk.checked = hideMetricLogs;
    chk.addEventListener('change', toggleHideMetricLogs);
  }
  renderMainLogs();
}

async function clearCommLogs() {
  const btn = document.getElementById('clearCommLogsBtn');
  const box = document.getElementById('commLogs');
  if (!btn || !box) return;
  btn.disabled = true;
  try {
    const r = await fetch('/api/comm-logs/clear', { method: 'POST' });
    if (r.ok) {
      box.textContent = 'No communication events yet. Serial disconnects/reconnects will appear here.';
      nextCommLogId = 1;
    }
  } catch (_) {
  } finally {
    btn.disabled = false;
  }
}

function downloadCommLogs() {
  window.location.href = '/api/comm-logs/text';
}

function initSectionState() {
  try {
    const savedRaw = localStorage.getItem(UI_SECTIONS_KEY) || localStorage.getItem(UI_SECTIONS_KEY_LEGACY);
    const saved = savedRaw ? JSON.parse(savedRaw) : null;
    const sections = document.querySelectorAll('details.section[data-section-key]');
    sections.forEach((el) => {
      const sectionKey = el.getAttribute('data-section-key');
      if (saved && sectionKey && Object.prototype.hasOwnProperty.call(saved, sectionKey)) {
        el.open = !!saved[sectionKey];
      } else if (saved && sectionKey === 'telemetry' && Object.prototype.hasOwnProperty.call(saved, 'host_metrics')) {
        el.open = !!saved.host_metrics;
      }
      el.addEventListener('toggle', () => {
        try {
          const currentRaw = localStorage.getItem(UI_SECTIONS_KEY) || localStorage.getItem(UI_SECTIONS_KEY_LEGACY);
          const current = currentRaw ? JSON.parse(currentRaw) : {};
          const k = el.getAttribute('data-section-key');
          if (!k) return;
          current[k] = !!el.open;
          localStorage.setItem(UI_SECTIONS_KEY, JSON.stringify(current));
        } catch (_) {}
      });
    });
  } catch (_) {}
}

const testSerialBtn = document.getElementById('testSerialBtn');
if (testSerialBtn) { testSerialBtn.addEventListener('click', testSerialPort); }
const refreshPortsBtn = document.getElementById('refreshPortsBtn');
if (refreshPortsBtn) { refreshPortsBtn.addEventListener('click', refreshSerialPorts); }
const useSelectedPortBtn = document.getElementById('useSelectedPortBtn');
if (useSelectedPortBtn) { useSelectedPortBtn.addEventListener('click', useSelectedPort); }
const serialPortInput = document.getElementById('serialPortInput');
if (serialPortInput) { serialPortInput.addEventListener('input', function() { updateSerialPortValidationChip(); syncSerialPortSelection(serialPortInput.value); }); }
refreshSerialPorts();
const refreshIfaceBtn = document.getElementById('refreshIfaceBtn');
if (refreshIfaceBtn) { refreshIfaceBtn.addEventListener('click', refreshInterfaceChoices); }
const useIfaceBtn = document.getElementById('useIfaceBtn');
if (useIfaceBtn) { useIfaceBtn.addEventListener('click', function() { copySelected('ifaceSelect', 'ifaceInput', 'ifaceResult', 'interface'); }); }
const ifaceInput = document.getElementById('ifaceInput');
if (ifaceInput) { ifaceInput.addEventListener('input', function() { syncInterfaceSelection(ifaceInput.value); }); }
const refreshDiskBtn = document.getElementById('refreshDiskBtn');
if (refreshDiskBtn) { refreshDiskBtn.addEventListener('click', refreshDiskChoices); }
const useDiskBtn = document.getElementById('useDiskBtn');
if (useDiskBtn) { useDiskBtn.addEventListener('click', function() { copyDiskSelection('disk'); }); }
const useDiskTempBtn = document.getElementById('useDiskTempBtn');
if (useDiskTempBtn) { useDiskTempBtn.addEventListener('click', function() { copyDiskSelection('temp'); }); }
const useDiskBothBtn = document.getElementById('useDiskBothBtn');
if (useDiskBothBtn) { useDiskBothBtn.addEventListener('click', function() { copyDiskSelection('both'); }); }
const refreshCpuTempSensorBtn = document.getElementById('refreshCpuTempSensorBtn');
if (refreshCpuTempSensorBtn) { refreshCpuTempSensorBtn.addEventListener('click', refreshCpuSensorChoices); }
const useCpuTempSensorBtn = document.getElementById('useCpuTempSensorBtn');
if (useCpuTempSensorBtn) { useCpuTempSensorBtn.addEventListener('click', function() { copySelected('cpuTempSensorSelect', 'cpuTempSensorInput', 'cpuTempSensorResult', 'CPU sensor'); }); }
const refreshFanSensorBtn = document.getElementById('refreshFanSensorBtn');
if (refreshFanSensorBtn) { refreshFanSensorBtn.addEventListener('click', refreshFanSensorChoices); }
const useFanSensorBtn = document.getElementById('useFanSensorBtn');
if (useFanSensorBtn) { useFanSensorBtn.addEventListener('click', function() { copySelected('fanSensorSelect', 'fanSensorInput', 'fanSensorResult', 'fan sensor'); }); }
const cpuTempSensorInput = document.getElementById('cpuTempSensorInput');
if (cpuTempSensorInput) { cpuTempSensorInput.addEventListener('input', function() { updateSensorValidationChips(); syncCpuSensorSelection(cpuTempSensorInput.value); }); }
const fanSensorInput = document.getElementById('fanSensorInput');
if (fanSensorInput) { fanSensorInput.addEventListener('input', function() { updateSensorValidationChips(); syncFanSensorSelection(fanSensorInput.value); }); }
const diskDeviceInput = document.getElementById('diskDeviceInput');
if (diskDeviceInput) { diskDeviceInput.addEventListener('input', syncDiskSelection); }
const diskTempDeviceInput = document.getElementById('diskTempDeviceInput');
if (diskTempDeviceInput) { diskTempDeviceInput.addEventListener('input', syncDiskSelection); }
refreshInterfaceChoices();
refreshDiskChoices();
refreshCpuSensorChoices();
refreshFanSensorChoices();
updateSensorValidationChips();
const clearLogsBtn = document.getElementById('clearLogsBtn');
if (clearLogsBtn) { clearLogsBtn.addEventListener('click', clearLogs); }
const downloadLogsBtn = document.getElementById('downloadLogsBtn');
if (downloadLogsBtn) { downloadLogsBtn.addEventListener('click', downloadLogs); }
const clearCommLogsBtn = document.getElementById('clearCommLogsBtn');
if (clearCommLogsBtn) { clearCommLogsBtn.addEventListener('click', clearCommLogs); }
const downloadCommLogsBtn = document.getElementById('downloadCommLogsBtn');
if (downloadCommLogsBtn) { downloadCommLogsBtn.addEventListener('click', downloadCommLogs); }
const detectHostPowerBtn = document.getElementById('detectHostPowerBtn');
if (detectHostPowerBtn) { detectHostPowerBtn.addEventListener('click', detectHostPowerDefaults); }
const previewHostPowerBtn = document.getElementById('previewHostPowerBtn');
if (previewHostPowerBtn) { previewHostPowerBtn.addEventListener('click', previewHostPowerCommands); }
initSectionState();
initMainLogsBuffer();
initHideMetricLogs();
updateSerialPortValidationChip();
initEspPreview();
window.addEventListener('resize', requestLayoutSync);
const viewSetupBtn = document.getElementById('viewSetupBtn');
if (viewSetupBtn) { viewSetupBtn.addEventListener('click', function() { setMonitorMode('setup'); }); }
const viewMonitorBtn = document.getElementById('viewMonitorBtn');
if (viewMonitorBtn) { viewMonitorBtn.addEventListener('click', function() { setMonitorMode('monitor'); }); }
initViewMode();
requestLayoutSync();
setInterval(pollStatus, 2000);
setInterval(pollLogs, 900);
setInterval(pollCommLogs, 900);
updateMetricPreview({});
updateMonitorDashboard({ last_metrics: {}, metric_history: {} });
pollStatus();
pollLogs();
pollCommLogs();
