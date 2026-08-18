// Fetch wrappers for the v2 API (`/api/v2`, see backend `v2/api.py`).
// Dev: Vite proxies `/api` to http://127.0.0.1:8000 (see vite.config.js).
// Prod: nginx is expected to proxy `/api` the same way alongside `/v2`.
//
// A location is a what3words point (`w3w`), not a volunteer-initials code
// — see V2_SPEC_ADDENDUM.md Change 3. `GET /locations` / `GET
// /locations/{w3w}` replace the original spec's `/sites`. `recorder`
// (volunteer initials) is separate metadata — "who collected this
// sample" — and is never used as a location identifier.

const BASE = '/api/v2';

export class ApiError extends Error {
  constructor(message, { status, url } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.url = url;
  }
}

function buildQuery(params) {
  if (!params) return '';
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    usp.set(key, value);
  }
  const qs = usp.toString();
  return qs ? `?${qs}` : '';
}

async function request(path, { method = 'GET', params, body, headers, signal } = {}) {
  const url = `${BASE}${path}${buildQuery(params)}`;
  let res;
  try {
    res = await fetch(url, {
      method,
      headers: {
        Accept: 'application/json',
        ...(body ? { 'Content-Type': 'application/json' } : {}),
        ...headers,
      },
      body: body ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch {
    throw new ApiError(
      'Could not reach the river data service. Check your connection and try again.',
      { url }
    );
  }

  if (!res.ok) {
    let detail = '';
    try {
      const data = await res.json();
      detail = data?.detail || data?.message || '';
    } catch {
      // response wasn't JSON — ignore
    }
    const friendly =
      res.status === 404
        ? "That page's data could not be found."
        : res.status === 401 || res.status === 403
          ? 'You are not allowed to do that.'
          : res.status >= 500
            ? 'The river data service had a problem. Please try again shortly.'
            : 'Something went wrong fetching that data.';
    throw new ApiError(detail || friendly, { status: res.status, url });
  }

  if (res.status === 204) return null;
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) return res.json();
  return res.text();
}

// ---- Reference data ----

export function getParameters(opts) {
  return request('/parameters', opts);
}

// ---- River-wide state ----

export function getOverview(opts) {
  return request('/overview', opts);
}

// ---- Locations (what3words points — see module note above) ----

export function getLocations(opts) {
  return request('/locations', opts);
}

export function getLocation(w3w, opts) {
  return request(`/locations/${encodeURIComponent(w3w)}`, opts);
}

export function getSeries({ parameter, w3w, recorder, from, to } = {}, opts) {
  return request('/series', { ...opts, params: { parameter, w3w, recorder, from, to } });
}

export function getDownstream({ parameter, round } = {}, opts) {
  return request('/downstream', { ...opts, params: { parameter, round } });
}

// ---- Review queue (a dozen or so ambiguous readings the cleaning
// pipeline could not confidently resolve — see V2_SPEC_ADDENDUM_2.md Rule
// D. Suggestions are stored but never auto-applied; POST records a human
// decision. Admin-gated the same way as report generation.) ----

export function getReviewQueue(opts) {
  return request('/review-queue', opts);
}

export function postReviewDecision(id, decision, opts) {
  // decision: { status: 'accepted' | 'rejected', resolved_value?, resolved_by? }
  return request(`/review-queue/${encodeURIComponent(id)}`, { ...opts, method: 'POST', body: decision });
}

export function getRounds(opts) {
  return request('/rounds', opts);
}

export function getRound(n, opts) {
  return request(`/rounds/${encodeURIComponent(n)}`, opts);
}

export function getDataQuality(opts) {
  return request('/data-quality', opts);
}

export function exportCsvUrl(params) {
  return `${BASE}/export.csv${buildQuery(params)}`;
}

// ---- Reports (data plumbing only — the Reports UI itself is owned
// elsewhere; these wrappers exist so that UI has one place to fetch from) ----

export function getReports({ type, key, audience } = {}, opts) {
  return request('/reports', { ...opts, params: { type, key, audience } });
}

// The report kinds and audiences, with the wording the interface uses.
// Served by the backend so the questions asked here and the prompts the
// engine runs cannot drift apart.
export function getReportTypes(opts) {
  return request('/reports/types', opts);
}

export function getReport(id, opts) {
  return request(`/reports/${encodeURIComponent(id)}`, opts);
}

export function getReportDownloadUrl(id, format = 'md') {
  return `${BASE}/reports/${encodeURIComponent(id)}/download?format=${format}`;
}

export function getReportVersions({ type, key, audience } = {}, opts) {
  return request('/reports/versions', { ...opts, params: { type, key, audience } });
}

export function generateReport(payload, opts) {
  return request('/reports/generate', { ...opts, method: 'POST', body: payload });
}

export function getReportJob(jobId, opts) {
  return request(`/reports/jobs/${encodeURIComponent(jobId)}`, opts);
}

export function getReportJobs(opts) {
  return request('/reports/jobs', opts);
}
