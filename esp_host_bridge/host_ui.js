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
let currentWorkloadMode = 'host';
let mainLogRows = [];
let hideMetricLogs = false;
const ESP_PREVIEW_PAGE_ORDER = ['home', 'docker', 'settings_1', 'settings_2', 'info_1', 'info_2', 'info_3', 'info_4', 'info_5', 'info_6', 'info_7', 'info_8', 'vms'];
const ESP_PREVIEW_META = {
  home: { title: 'HOME', footer: 'HOME', count: 0, index: 0, topPills: null },
  docker: { title: 'Docker', footer: 'Docker', count: 1, index: 1, topPills: 'docker' },
  settings_1: { title: 'Settings', footer: 'Settings 1', count: 2, index: 1, topPills: null },
  settings_2: { title: 'Settings', footer: 'Settings 2', count: 2, index: 2, topPills: null },
  info_1: { title: 'NETWORK', footer: 'Info 1 • Network', count: 8, index: 1, topPills: null },
  info_2: { title: 'SYSTEM', footer: 'Info 2 • System', count: 8, index: 2, topPills: null },
  info_3: { title: 'CPU TEMP', footer: 'Info 3 • CPU Temp', count: 8, index: 3, topPills: null },
  info_4: { title: 'DISK TEMP', footer: 'Info 4 • Disk Temp', count: 8, index: 4, topPills: null },
  info_5: { title: 'DISK USAGE', footer: 'Info 5 • Disk Usage', count: 8, index: 5, topPills: null },
  info_6: { title: 'GPU', footer: 'Info 6 • GPU', count: 8, index: 6, topPills: null },
  info_7: { title: 'UPTIME', footer: 'Info 7 • Uptime', count: 8, index: 7, topPills: null },
  info_8: { title: 'HOST NAME', footer: 'Info 8 • Host Name', count: 8, index: 8, topPills: null },
  vms: { title: 'VMS', footer: 'VMS', count: 1, index: 1, topPills: 'vms' },
};
const ESP_PREVIEW_NAV = {
  docker: { down: 'home' },
  settings_1: { up: 'home', left: 'settings_2', right: 'settings_2' },
  settings_2: { up: 'home', left: 'settings_1', right: 'settings_1' },
  info_1: { up: 'home', left: 'info_2', right: 'info_8' },
  info_2: { up: 'home', left: 'info_3', right: 'info_1' },
  info_3: { up: 'home', left: 'info_4', right: 'info_2' },
  info_4: { up: 'home', left: 'info_5', right: 'info_3' },
  info_5: { up: 'home', left: 'info_6', right: 'info_4' },
  info_6: { up: 'home', left: 'info_7', right: 'info_5' },
  info_7: { up: 'home', left: 'info_8', right: 'info_6' },
  info_8: { up: 'home', left: 'info_1', right: 'info_7' },
  vms: { down: 'home' },
};
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

function getWorkloadMode(s) {
  return (s && s.platform_mode === 'homeassistant') ? 'homeassistant' : 'host';
}
function getWorkloadLabels(mode) {
  if (mode === 'homeassistant') {
    return {
      dockerTitle: 'Add-ons',
      dockerPage: 'Add-ons',
      dockerFooter: 'Add-ons',
      dockerPreviewSub: 'On / Off / Issue',
      dockerSummary: 'Started / Stopped / Issue',
      dockerListHintEmpty: 'No Home Assistant add-ons in latest payload',
      dockerListHintOne: 'Showing 1 add-on',
      dockerListHintMany: (count) => `Showing ${count} add-ons`,
      dockerListHintMore: (count, extra) => `Showing 5 of ${count} add-ons (+${extra} more)`,
      dockerModalSub: 'Home Assistant app control',
      vmTitle: 'Integrations',
      vmPage: 'Integrations',
      vmFooter: 'Integrations',
      vmPreviewSub: 'Loaded integrations',
      vmSummary: 'Loaded integrations',
      vmListHintEmpty: 'No integrations in latest payload',
      vmListHintOne: 'Showing 1 integration',
      vmListHintMany: (count) => `Showing ${count} integrations`,
      vmListHintMore: (count, extra) => `Showing 5 of ${count} integrations (+${extra} more)`,
      vmModalSub: 'Loaded integration overview',
      summaryLabel: 'Serial / HA',
    };
  }
  return {
    dockerTitle: 'Docker',
    dockerPage: 'Docker',
    dockerFooter: 'Docker',
    dockerPreviewSub: 'Run / Stop / Unh',
    dockerSummary: 'Run / Stop / Unhealthy',
    dockerListHintEmpty: 'No Docker containers in latest payload',
    dockerListHintOne: 'Showing 1 container',
    dockerListHintMany: (count) => `Showing ${count} containers`,
    dockerListHintMore: (count, extra) => `Showing 5 of ${count} containers (+${extra} more)`,
    dockerModalSub: 'Container control',
    vmTitle: 'VMs',
    vmPage: 'VMS',
    vmFooter: 'VMS',
    vmPreviewSub: 'Run / Pause / Stop',
    vmSummary: 'Run / Pause / Stop / Other',
    vmListHintEmpty: 'No virtual machines in latest payload',
    vmListHintOne: 'Showing 1 virtual machine',
    vmListHintMany: (count) => `Showing ${count} virtual machines`,
    vmListHintMore: (count, extra) => `Showing 5 of ${count} virtual machines (+${extra} more)`,
    vmModalSub: 'Virtual machine control',
    summaryLabel: 'Serial / Workloads',
  };
}
function getWorkloadIcons(mode) {
  if (mode === 'homeassistant') {
    return {
      docker: 'mdi-puzzle-outline',
      vm: 'mdi-devices',
    };
  }
  return {
    docker: 'mdi-docker',
    vm: 'mdi-monitor-multiple',
  };
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
function refreshWorkloadLabels(mode) {
  currentWorkloadMode = mode === 'homeassistant' ? 'homeassistant' : 'host';
  const labels = getWorkloadLabels(currentWorkloadMode);
  const icons = getWorkloadIcons(currentWorkloadMode);
  setMetricCardHeading('mDOCKER', icons.docker, labels.dockerTitle);
  setMetricCardHeading('mVMS', icons.vm, labels.vmTitle);
  const dockerSub = document.getElementById('mDOCKER') && document.getElementById('mDOCKER').nextElementSibling;
  const vmSub = document.getElementById('mVMS') && document.getElementById('mVMS').nextElementSibling;
  if (dockerSub) dockerSub.textContent = labels.dockerPreviewSub;
  if (vmSub) vmSub.textContent = labels.vmPreviewSub;
  const summaryLabel = document.getElementById('sumDocker') && document.getElementById('sumDocker').parentElement && document.getElementById('sumDocker').parentElement.querySelector('.k');
  if (summaryLabel) summaryLabel.textContent = labels.summaryLabel;
  setCardHeading('mvDockerCounts', mode === 'homeassistant' ? 'Add-on Summary' : 'Docker Summary');
  setCardHeading('mvVmCounts', mode === 'homeassistant' ? 'Integration Summary' : 'VM Summary');
  const dockerTab = document.querySelector('[data-esp-page="docker"]');
  const vmTab = document.querySelector('[data-esp-page="vms"]');
  if (dockerTab) dockerTab.innerHTML = `<span class="mdi ${icons.docker}" aria-hidden="true"></span>${escapeHtml(labels.dockerPage)}`;
  if (vmTab) vmTab.innerHTML = `<span class="mdi ${icons.vm}" aria-hidden="true"></span>${escapeHtml(labels.vmPage)}`;
  const homeDocker = document.querySelector('[data-esp-nav="docker"]');
  const homeVm = document.querySelector('[data-esp-nav="vms"]');
  if (homeDocker) homeDocker.setAttribute('title', labels.dockerTitle);
  if (homeVm) homeVm.setAttribute('title', labels.vmTitle);
  const homeDockerIcon = homeDocker && homeDocker.querySelector('.mdi');
  const homeVmIcon = homeVm && homeVm.querySelector('.mdi');
  if (homeDockerIcon) homeDockerIcon.className = `mdi ${icons.docker}`;
  if (homeVmIcon) homeVmIcon.className = `mdi ${icons.vm}`;
  const dockerEmptyIcon = document.querySelector('#espDockerEmpty .mdi');
  const vmEmptyIcon = document.querySelector('#espVmsEmpty .mdi');
  if (dockerEmptyIcon) dockerEmptyIcon.className = `mdi ${icons.docker}`;
  if (vmEmptyIcon) vmEmptyIcon.className = `mdi ${icons.vm}`;
  const dockerModal = document.getElementById('espDockerModal');
  const vmModal = document.getElementById('espVmsModal');
  if (dockerModal) {
    const icon = dockerModal.querySelector('.esp-preview-modal-heading .mdi');
    const title = dockerModal.querySelector('.esp-preview-modal-title');
    const subtitle = dockerModal.querySelector('.esp-preview-modal-subtitle');
    if (icon) icon.className = `mdi ${icons.docker}`;
    if (title) title.textContent = labels.dockerTitle;
    if (subtitle) subtitle.textContent = labels.dockerModalSub;
  }
  if (vmModal) {
    const icon = vmModal.querySelector('.esp-preview-modal-heading .mdi');
    const title = vmModal.querySelector('.esp-preview-modal-title');
    const subtitle = vmModal.querySelector('.esp-preview-modal-subtitle');
    const footer = vmModal.querySelector('.esp-preview-modal-footer');
    const footnote = vmModal.querySelector('.esp-preview-modal-footnote');
    if (icon) icon.className = `mdi ${icons.vm}`;
    if (title) title.textContent = labels.vmTitle;
    if (subtitle) subtitle.textContent = labels.vmModalSub;
    if (footer) footer.hidden = currentWorkloadMode === 'homeassistant';
    if (footnote) footnote.hidden = currentWorkloadMode === 'homeassistant';
  }
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
    refreshWorkloadLabels(getWorkloadMode(s));
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
function updateMetricPreview(metrics) {
  const m = (metrics && typeof metrics === 'object') ? metrics : {};
  const keys = Object.keys(m);
  const hasAny = keys.length > 0;
  const has = (k) => Object.prototype.hasOwnProperty.call(m, k) && m[k] !== '' && m[k] !== null && m[k] !== undefined;
  if (!hasAny) {
    metricText('mCPU', 'Waiting...');
    metricText('mMEM', 'Waiting...');
    metricText('mTEMP', 'Waiting...');
    metricText('mNET', 'Waiting...');
    metricText('mDISK', 'Waiting...');
    metricText('mDOCKER', 'Waiting...');
    metricText('mVMS', 'Waiting...');
    return;
  }
  metricText('mCPU', has('CPU') ? `${m.CPU}%` : 'Waiting...');
  metricText('mMEM', has('MEM') ? `${m.MEM}%` : 'Waiting...');
  metricText('mTEMP', has('TEMP') ? `${m.TEMP}°C` : 'Waiting...');
  const rx = has('RX') ? `${m.RX}` : '...';
  const tx = has('TX') ? `${m.TX}` : '...';
  metricText('mNET', `${rx} / ${tx}`);
  const dtemp = has('DISK') ? `${m.DISK}°C` : '...';
  const dpct = has('DISKPCT') ? `${m.DISKPCT}%` : '...';
  metricText('mDISK', `${dtemp} / ${dpct}`);
  const dr = has('DOCKRUN') ? m.DOCKRUN : '...';
  const ds = has('DOCKSTOP') ? m.DOCKSTOP : '...';
  const du = has('DOCKUNH') ? m.DOCKUNH : '...';
  metricText('mDOCKER', `${dr} / ${ds} / ${du}`);
  const vr = has('VMSRUN') ? m.VMSRUN : '...';
  const vp = has('VMSPAUSE') ? m.VMSPAUSE : '...';
  const vs = has('VMSSTOP') ? m.VMSSTOP : '...';
  metricText('mVMS', `${vr} / ${vp} / ${vs}`);
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
function fmtEspMbps(kbps) {
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
function getEspPreviewMeta(page) {
  const labels = getWorkloadLabels(currentWorkloadMode);
  if (page === 'docker') return { title: labels.dockerTitle, footer: labels.dockerFooter, count: 1, index: 1, topPills: 'docker' };
  if (page === 'vms') return { title: labels.vmPage.toUpperCase(), footer: labels.vmFooter, count: 1, index: 1, topPills: 'vms' };
  return ESP_PREVIEW_META[page] || ESP_PREVIEW_META.home;
}
function renderEspPageIndicator() {
  const el = document.getElementById('espPageIndicator');
  if (!el) return;
  const meta = getEspPreviewMeta(currentEspPreviewPage);
  const count = Number(meta.count || 0);
  const index = Number(meta.index || 0);
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
  const meta = getEspPreviewMeta(currentEspPreviewPage);
  const title = document.getElementById('espTopTitle');
  const footer = document.getElementById('espFooterPage');
  if (title) title.textContent = meta.title;
  if (footer) footer.textContent = `Preview • ${meta.footer}`;
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
function refreshEspPreviewActiveModal() {
  if (!espPreviewActiveModal) return;
  if (espPreviewActiveModal.type === 'docker') {
    const item = espPreviewDockerItems.find((row) => row && row.name === espPreviewActiveModal.name);
    if (!item) return;
    metricText('espDockerModalName', item.name);
    return;
  }
  if (espPreviewActiveModal.type === 'vms') {
    const item = espPreviewVmItems.find((row) => row && row.name === espPreviewActiveModal.name);
    if (!item) return;
    metricText('espVmsModalName', item.name);
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
  const next = ESP_PREVIEW_NAV[currentEspPreviewPage] && ESP_PREVIEW_NAV[currentEspPreviewPage][direction];
  if (next) setEspPreviewPage(next);
}
function setEspPreviewPage(page) {
  const next = ESP_PREVIEW_PAGE_ORDER.includes(page) ? page : 'home';
  currentEspPreviewPage = next;
  document.querySelectorAll('[data-esp-page]').forEach((btn)=> {
    btn.classList.toggle('active', btn.getAttribute('data-esp-page') === next);
  });
  const screen = document.getElementById('espPreviewScreen');
  if (screen) screen.classList.toggle('home-mode', next === 'home');
  const pages = {
    home: document.getElementById('espPageHome'),
    docker: document.getElementById('espPageDocker'),
    settings_1: document.getElementById('espPageSettings1'),
    settings_2: document.getElementById('espPageSettings2'),
    info_1: document.getElementById('espPageInfo1'),
    info_2: document.getElementById('espPageInfo2'),
    info_3: document.getElementById('espPageInfo3'),
    info_4: document.getElementById('espPageInfo4'),
    info_5: document.getElementById('espPageInfo5'),
    info_6: document.getElementById('espPageInfo6'),
    info_7: document.getElementById('espPageInfo7'),
    info_8: document.getElementById('espPageInfo8'),
    vms: document.getElementById('espPageVms'),
  };
  Object.entries(pages).forEach(([k, el]) => { if (el) el.classList.toggle('active', k === next); });
  closeEspPreviewModal();
  refreshEspPreviewChrome();
  try { localStorage.setItem(ESP_PREVIEW_PAGE_KEY, next); } catch (_) {}
}
function initEspPreview() {
  document.querySelectorAll('[data-esp-page]').forEach((btn)=> {
    btn.addEventListener('click', () => setEspPreviewPage(btn.getAttribute('data-esp-page') || 'home'));
  });
  document.querySelectorAll('[data-esp-nav]').forEach((el)=> {
    el.addEventListener('click', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      setEspPreviewPage(el.getAttribute('data-esp-nav') || 'home');
    });
  });
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
      const dockerAction = ev.target.closest('[data-esp-docker-action]');
      if (dockerAction && espPreviewActiveModal && espPreviewActiveModal.type === 'docker') {
        const action = dockerAction.getAttribute('data-esp-docker-action');
        espPreviewDockerOverrides[espPreviewActiveModal.name] = { state: action === 'start' ? 'running' : 'stopped' };
        closeEspPreviewModal();
        if (lastStatusPayload) updateEspPreview(lastStatusPayload);
        return;
      }
      const vmAction = ev.target.closest('[data-esp-vms-action]');
      if (vmAction && espPreviewActiveModal && espPreviewActiveModal.type === 'vms') {
        const action = vmAction.getAttribute('data-esp-vms-action');
        if (action === 'start' || action === 'restart') {
          espPreviewVmOverrides[espPreviewActiveModal.name] = { stateKey: 'running', stateLabel: 'Running' };
        } else {
          espPreviewVmOverrides[espPreviewActiveModal.name] = { stateKey: 'stopped', stateLabel: 'Stopped' };
        }
        closeEspPreviewModal();
        if (lastStatusPayload) updateEspPreview(lastStatusPayload);
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
  const rows = (Array.isArray(items) ? items : []).slice(0, 10);
  if (!rows.length) {
    list.innerHTML = '';
    const title = empty.querySelector('.esp-workload-empty-title');
    const subtitle = empty.querySelector('.esp-workload-empty-subtitle');
    const token = workloadMetricFlag(lastStatusPayload && lastStatusPayload.last_metrics, 'HATOKEN');
    const api = workloadMetricFlag(lastStatusPayload && lastStatusPayload.last_metrics, 'HADOCKAPI');
    if (currentWorkloadMode === 'homeassistant' && token === 0) {
      if (title) title.textContent = 'Token Missing';
      if (subtitle) subtitle.textContent = 'Supervisor token is not available to the app';
    } else if (currentWorkloadMode === 'homeassistant' && api === 0) {
      if (title) title.textContent = 'Add-on API Error';
      if (subtitle) subtitle.textContent = 'Check app logs for Supervisor API errors';
    } else {
      if (title) title.textContent = currentWorkloadMode === 'homeassistant' ? 'No Add-ons' : 'No Docker Data';
      if (subtitle) subtitle.textContent = currentWorkloadMode === 'homeassistant' ? 'No add-ons in the latest payload' : 'No containers in the latest payload';
    }
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  list.innerHTML = rows.map((item, index) => {
    const icons = getWorkloadIcons(currentWorkloadMode);
    return `<button class="esp-workload-row" type="button" data-esp-modal-row="docker" data-esp-index="${index}">
      <span class="mdi ${icons.docker}" aria-hidden="true"></span>
      <span class="esp-workload-row-name">${escapeHtml(item.name)}</span>
    </button>`;
  }).join('');
}
function renderEspVmRows(items, stateMode) {
  const list = document.getElementById('espVmsRows');
  const empty = document.getElementById('espVmsEmpty');
  if (!list || !empty) return;
  const rows = (Array.isArray(items) ? items : []).slice(0, 10);
  if (!rows.length) {
    list.innerHTML = '';
    const title = empty.querySelector('.esp-workload-empty-title');
    const subtitle = empty.querySelector('.esp-workload-empty-subtitle');
    const token = workloadMetricFlag(lastStatusPayload && lastStatusPayload.last_metrics, 'HATOKEN');
    const api = workloadMetricFlag(lastStatusPayload && lastStatusPayload.last_metrics, 'HAVMSAPI');
    if (currentWorkloadMode === 'homeassistant' && token === 0) {
      if (title) title.textContent = 'Token Missing';
      if (subtitle) subtitle.textContent = 'Supervisor token is not available to the app';
    } else if (currentWorkloadMode === 'homeassistant' && api === 0) {
      if (title) title.textContent = 'Integration API Error';
      if (subtitle) subtitle.textContent = 'Check app logs for Core WebSocket errors';
    } else {
      if (title) title.textContent = currentWorkloadMode === 'homeassistant' ? 'No Integrations' : 'No VM Data';
      if (subtitle) subtitle.textContent = currentWorkloadMode === 'homeassistant' ? 'No integrations in the latest payload' : 'No virtual machines in the latest payload';
    }
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  const icons = getWorkloadIcons(currentWorkloadMode);
  list.innerHTML = rows.map((item, index) => `<button class="esp-workload-row" type="button" data-esp-modal-row="vms" data-esp-index="${index}">
      <span class="mdi ${icons.vm}" aria-hidden="true"></span>
      <span class="esp-workload-row-name">${escapeHtml(item.name)}</span>
    </button>`).join('');
}
function renderDockerLists(items) {
  const prev = document.getElementById('dockerPreviewList'); const all = document.getElementById('dockerAllList'); const hint = document.getElementById('dockerMoreHint');
  if (!prev || !all || !hint) return;
  const labels = getWorkloadLabels(currentWorkloadMode);
  const rowHtml = (it)=>'<li><span>' + it.name + '</span><span class="docker-pill ' + (it.state === 'up' ? 'up' : 'down') + '">' + it.state + '</span></li>';
  prev.innerHTML = items.slice(0,5).map(rowHtml).join('');
  all.innerHTML = items.map(rowHtml).join('');
  const extra = Math.max(0, items.length - 5);
  const token = workloadMetricFlag(lastStatusPayload && lastStatusPayload.last_metrics, 'HATOKEN');
  const api = workloadMetricFlag(lastStatusPayload && lastStatusPayload.last_metrics, 'HADOCKAPI');
  if (!items.length && currentWorkloadMode === 'homeassistant' && token === 0) hint.textContent = 'Supervisor token missing in app container';
  else if (!items.length && currentWorkloadMode === 'homeassistant' && api === 0) hint.textContent = 'Add-on API unavailable; check logs';
  else if (!items.length) hint.textContent = labels.dockerListHintEmpty;
  else if (extra) hint.textContent = labels.dockerListHintMore(items.length, extra);
  else if (items.length === 1) hint.textContent = labels.dockerListHintOne;
  else hint.textContent = labels.dockerListHintMany(items.length);
}
function renderVmLists(items) {
  const prev = document.getElementById('vmPreviewList'); const all = document.getElementById('vmAllList'); const hint = document.getElementById('vmMoreHint');
  if (!prev || !all || !hint) return;
  const labels = getWorkloadLabels(currentWorkloadMode);
  const rowHtml = (it)=>'<li><span>' + it.name + '</span><span class="docker-pill ' + it.stateKey + '">' + it.stateLabel + '</span></li>';
  prev.innerHTML = items.slice(0,5).map(rowHtml).join('');
  all.innerHTML = items.map(rowHtml).join('');
  const extra = Math.max(0, items.length - 5);
  const token = workloadMetricFlag(lastStatusPayload && lastStatusPayload.last_metrics, 'HATOKEN');
  const api = workloadMetricFlag(lastStatusPayload && lastStatusPayload.last_metrics, 'HAVMSAPI');
  if (!items.length && currentWorkloadMode === 'homeassistant' && token === 0) hint.textContent = 'Supervisor token missing in app container';
  else if (!items.length && currentWorkloadMode === 'homeassistant' && api === 0) hint.textContent = 'Integration registry unavailable; check logs';
  else if (!items.length) hint.textContent = labels.vmListHintEmpty;
  else if (extra) hint.textContent = labels.vmListHintMore(items.length, extra);
  else if (items.length === 1) hint.textContent = labels.vmListHintOne;
  else hint.textContent = labels.vmListHintMany(items.length);
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
function updateMonitorDashboard(s) {
  if (!s || typeof s !== 'object') return;
  const workloadMode = getWorkloadMode(s);
  currentWorkloadMode = workloadMode;
  const labels = getWorkloadLabels(workloadMode);
  const m = (s.last_metrics && typeof s.last_metrics === 'object') ? s.last_metrics : {};
  const n = (k)=> (Object.prototype.hasOwnProperty.call(m,k) && m[k] !== '' ? Number(m[k]) : null);
  metricText('sumAgent', s.running ? 'Running' : 'Stopped');
  if (workloadMode === 'homeassistant') metricText('sumDocker', 'A ' + String(m.DOCKRUN ?? '--') + '/' + String(m.DOCKSTOP ?? '--') + ' • I ' + String(m.VMSRUN ?? '--'));
  else metricText('sumDocker', 'D ' + String(m.DOCKRUN ?? '--') + '/' + String(m.DOCKSTOP ?? '--') + ' • VM ' + String(m.VMSRUN ?? '--') + '/' + String(m.VMSPAUSE ?? '--') + '/' + String(m.VMSSTOP ?? '--'));
  metricText('sumAge', fmtAgeSec(s.last_metrics_age_s));
  metricText('sumPower', String(m.POWER || 'RUNNING'));
  const cpu = n('CPU'), mem = n('MEM'), temp = n('TEMP'), up = n('UP');
  const rx = n('RX'), tx = n('TX'), dtemp = n('DISK'), dpct = n('DISKPCT'), dr = n('DISKR'), dw = n('DISKW');
  const fan = n('FAN'), gu = n('GPUU'), gt = n('GPUT'), gvm = n('GPUVM');
  setMetricCard('CPU', cpu!==null ? cpu.toFixed(1) + '%' : '--', cpu!==null ? 'Current load' : 'Waiting for telemetry', cpu===null?null:(cpu>=90?'sev-danger':cpu>=70?'sev-warn':'sev-ok'));
  setMetricCard('MEM', mem!==null ? mem.toFixed(1) + '%' : '--', mem!==null ? 'Used memory' : 'Waiting for telemetry', mem===null?null:(mem>=90?'sev-danger':mem>=75?'sev-warn':'sev-ok'));
  setMetricCard('TEMP', temp!==null ? temp.toFixed(1) + '°C' : '--', 'CPU sensor', temp===null?null:(temp>=85?'sev-danger':temp>=75?'sev-warn':'sev-ok'));
  setMetricCard('UP', up!==null ? fmtUptimeSec(up) : '--', up!==null ? String(Math.round(up)) + 's total' : 'Waiting for telemetry', 'sev-ok');
  setMetricCard('NET', (rx!==null||tx!==null) ? String(rx!==null?Math.round(rx):'...') + ' / ' + String(tx!==null?Math.round(tx):'...') : '--', 'RX / TX kbps', ((rx||0)+(tx||0))>50000 ? 'sev-warn' : 'sev-ok');
  setMetricCard('DISKIO', (dr!==null||dw!==null) ? String(dr!==null?Math.round(dr):'...') + ' / ' + String(dw!==null?Math.round(dw):'...') : '--', 'Read / Write kB/s', ((dr||0)+(dw||0))>50000 ? 'sev-warn' : 'sev-ok');
  setMetricCard('DISK', dtemp!==null ? dtemp.toFixed(1) + '°C' : '--', dpct!==null ? dpct.toFixed(1) + '% used' : 'Temperature / Usage', dtemp===null?null:(dtemp>=55?'sev-danger':dtemp>=48?'sev-warn':'sev-ok'));
  setMetricCard('DISKPCT', dpct!==null ? dpct.toFixed(1) + '%' : '--', 'Disk usage', dpct===null?null:(dpct>=92?'sev-danger':dpct>=80?'sev-warn':'sev-ok'));
  setMetricCard('FAN', fan!==null ? String(Math.round(fan)) : '--', 'RPM', 'sev-ok');
  setMetricCard('GPUU', gu!==null ? String(Math.round(gu)) + '%' : '--', 'GPU utilization', gu===null?null:(gu>=95?'sev-danger':gu>=80?'sev-warn':'sev-ok'));
  setMetricCard('GPUT', gt!==null ? gt.toFixed(1) + '°C' : '--', 'GPU temp', gt===null?null:(gt>=85?'sev-danger':gt>=75?'sev-warn':'sev-ok'));
  setMetricCard('GPUVM', gvm!==null ? String(Math.round(gvm)) + '%' : '--', 'VRAM usage', gvm===null?null:(gvm>=90?'sev-danger':gvm>=75?'sev-warn':'sev-ok'));
  setMetricCard('DockerCounts', String(m.DOCKRUN ?? '--') + ' / ' + String(m.DOCKSTOP ?? '--') + ' / ' + String(m.DOCKUNH ?? '--'), labels.dockerSummary, (Number(m.DOCKUNH||0)>0) ? 'sev-warn' : 'sev-ok');
  if (workloadMode === 'homeassistant') setMetricCard('VmCounts', String(m.VMSRUN ?? '--'), labels.vmSummary, 'sev-ok');
  else setMetricCard('VmCounts', String(m.VMSRUN ?? '--') + ' / ' + String(m.VMSPAUSE ?? '--') + ' / ' + String(m.VMSSTOP ?? '--') + ' / ' + String(m.VMSOTHER ?? '--'), labels.vmSummary, 'sev-ok');
  renderDockerLists(parseDockerCompact(m.DOCKER));
  renderVmLists(parseVmCompact(m.VMS));
  setSpark('sparkCPU', historyOf(s,'CPU'), '#60a5fa');
  setSpark('sparkMEM', historyOf(s,'MEM'), '#34d399');
  setSpark('sparkTEMP', historyOf(s,'TEMP'), '#fb923c');
  setSpark('sparkUP', historyOf(s,'UP'), '#a78bfa');
  const rxh = historyOf(s,'RX'); const txh = historyOf(s,'TX');
  const netHist = rxh.map((v,i)=> Number(v||0) + Number((txh[i]||0)) );
  setSpark('sparkNET', netHist, '#22d3ee');
  const drh = historyOf(s,'DISKR'); const dwh = historyOf(s,'DISKW');
  const dioHist = drh.map((v,i)=> Number(v||0) + Number((dwh[i]||0)) );
  setSpark('sparkDISKIO', dioHist, '#f472b6');
  setSpark('sparkDISK', historyOf(s,'DISK'), '#f59e0b');
  setSpark('sparkDISKPCT', historyOf(s,'DISKPCT'), '#10b981');
  setSpark('sparkFAN', historyOf(s,'FAN'), '#fbbf24');
  setSpark('sparkGPUU', historyOf(s,'GPUU'), '#38bdf8');
  setSpark('sparkGPUT', historyOf(s,'GPUT'), '#fb7185');
  setSpark('sparkGPUVM', historyOf(s,'GPUVM'), '#c084fc');
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

  metricText('espNetRxVal', rx !== null ? fmtEspMbps(rx) : '--');
  metricText('espNetTxVal', tx !== null ? fmtEspMbps(tx) : '--');
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
    const s = data && data.shutdown ? data.shutdown : {};
    const rr = data && data.restart ? data.restart : {};
    box.textContent =
      `CMD=shutdown -> ${s.ok ? s.command : (s.message || 'not available')}
` +
      `CMD=restart  -> ${rr.ok ? rr.command : (rr.message || 'not available')}`;
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
    if (data && typeof data.shutdown_cmd === 'string') shutdownEl.value = data.shutdown_cmd;
    if (data && typeof data.restart_cmd === 'string') restartEl.value = data.restart_cmd;
    const osName = (data && data.os) ? data.os : 'host';
    if ((shutdownEl.value || restartEl.value)) {
      result.textContent = `Loaded defaults for ${osName}`;
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
