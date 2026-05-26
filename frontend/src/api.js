const BASE = "/api";
const cache = {};
const TTL = 300000;

async function fetchJSON(url) {
  const now = Date.now();
  const hit = cache[url];
  if (hit && now - hit.time < TTL) return hit.data;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
  const data = await resp.json();
  cache[url] = { data, time: now };
  return data;
}

export function clearCache() {
  Object.keys(cache).forEach((k) => delete cache[k]);
}

export function getStats() {
  return fetchJSON(`${BASE}/stats`);
}

export function getSites() {
  return fetchJSON(`${BASE}/sites`);
}

export function getEntries(params = {}) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") qs.set(k, v);
  });
  return fetchJSON(`${BASE}/entries?${qs}`);
}

export function getChemicals(chemical, filters = {}) {
  const qs = new URLSearchParams({ chemical, ...filters });
  return fetchJSON(`${BASE}/chemicals?${qs}`);
}

export function triggerSync() {
  const url = `${BASE}/sync?_=${Date.now()}`;
  return fetch(url).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${r.statusText}`);
    return r.json();
  });
}

export function getSyncLog(limit = 10) {
  return fetchJSON(`${BASE}/sync/log?limit=${limit}`);
}

export function getRounds(chemical, site) {
  const params = new URLSearchParams();
  if (chemical) params.set("chemical", chemical);
  if (site) params.set("site", site);
  return fetchJSON(`${BASE}/rounds?${params}`);
}

export function getLocationSeries(chemical) {
  return fetchJSON(`${BASE}/location-series?chemical=${chemical}`);
}

export function getSiteAverages(chemical) {
  return fetchJSON(`${BASE}/site-averages?chemical=${chemical}`);
}

export function getSiteSummary(site) {
  return fetchJSON(`${BASE}/site-summary?site=${site}`);
}

export function getPhotos() {
  return fetchJSON(`${BASE}/photos`);
}

// ── Reports ──────────────────────────────────────────────

export function getSiteReport(site, version) {
  const qs = new URLSearchParams({ site });
  if (version) qs.set("version", version);
  return fetchJSON(`${BASE}/reports/site?${qs}`);
}

export function getSiteReportVersions(site) {
  return fetchJSON(`${BASE}/reports/site/versions?site=${site}`);
}

export function getAllSiteReports() {
  return fetchJSON(`${BASE}/reports/site/all`);
}

export function triggerSiteReport(site) {
  return fetch(`${BASE}/reports/site/generate?site=${site}`, { method: "POST" }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${r.statusText}`);
    return r.json();
  });
}

export function getRoundReport(roundLabel, version) {
  const qs = new URLSearchParams({ round_label: roundLabel });
  if (version) qs.set("version", version);
  return fetchJSON(`${BASE}/reports/round?${qs}`);
}

export function getRoundReportVersions(roundLabel) {
  return fetchJSON(`${BASE}/reports/round/versions?round_label=${roundLabel}`);
}

export function getAllRoundReports() {
  return fetchJSON(`${BASE}/reports/round/all`);
}

export function triggerRoundReport(roundLabel, roundStart, roundEnd) {
  const qs = new URLSearchParams({ round_label: roundLabel, round_start: roundStart, round_end: roundEnd });
  return fetch(`${BASE}/reports/round/generate?${qs}`, { method: "POST" }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${r.statusText}`);
    return r.json();
  });
}
