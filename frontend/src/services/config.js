/**
 * Runtime configuration.
 *
 * The frontend is a static bundle, so it cannot be compiled with the API URL
 * baked in. The base URL is resolved at load time, first match wins:
 *
 *   1. `?api=https://...`     - one-off override, remembered afterwards
 *   2. localStorage           - whatever the user last connected to
 *   3. `window.__API_BASE__`  - written into config.js at deploy time
 *   4. same origin            - local development, where FastAPI serves both
 *
 * That ordering means a Netlify build can ship a default (3) while still
 * letting someone point the same deployment at a different backend (1/2)
 * without a rebuild.
 */

const KEY = 'resume-intelligence.api-base';

function normalise(url) {
  if (!url) return '';
  return String(url).trim().replace(/\/+$/, '');
}

function fromQuery() {
  try {
    const value = new URLSearchParams(window.location.search).get('api');
    if (!value) return '';
    const url = normalise(value);
    localStorage.setItem(KEY, url);
    return url;
  } catch {
    return '';
  }
}

function fromStorage() {
  try {
    return normalise(localStorage.getItem(KEY));
  } catch {
    return '';
  }
}

function fromBuild() {
  return normalise(typeof window !== 'undefined' ? window.__API_BASE__ : '');
}

/** The base URL every API call is prefixed with. '' means same-origin. */
export function apiBase() {
  return fromQuery() || fromStorage() || fromBuild() || '';
}

/** Point the app at a different backend (used by the connection panel). */
export function setApiBase(url) {
  const value = normalise(url);
  try {
    if (value) localStorage.setItem(KEY, value);
    else localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable - the value still applies for this page load */
  }
  return value;
}

export function clearApiBase() {
  return setApiBase('');
}

/** True when the API lives on another origin, so CORS is in play. */
export function isCrossOrigin() {
  const base = apiBase();
  if (!base) return false;
  try {
    return new URL(base, window.location.href).origin !== window.location.origin;
  } catch {
    return false;
  }
}

export function describeTarget() {
  return apiBase() || `${window.location.origin} (same origin)`;
}
