/**
 * Thin API client for the FastAPI backend.
 *
 * Every call funnels through `request()` so error handling, timeouts and the
 * shape of thrown errors are identical everywhere in the UI.
 */

import { apiBase } from './config.js';

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

async function request(path, { method = 'GET', body, timeout = 120000, isForm = false } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(apiBase() + path, {
      method,
      headers: isForm || body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: isForm ? body : body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });

    const text = await response.text();
    const contentType = response.headers.get('content-type') || '';
    let payload = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      // A non-JSON body means we reached something that is not this API - most
      // often a static host answering /api/* with its own index.html or 404
      // page. Dumping that markup at the user explains nothing, so name the
      // actual problem instead.
      const looksLikeHtml = /^\s*<(!doctype|html)/i.test(text) || contentType.includes('text/html');
      payload = {
        detail: looksLikeHtml
          ? `${apiBase() || window.location.origin} returned a web page instead of API data. `
            + 'It is serving the frontend, not the backend - point the app at your API URL.'
          : text.slice(0, 200).trim() || `Request failed (${response.status}).`,
      };
    }

    if (!response.ok) {
      let message = payload?.detail || `Request failed (${response.status})`;
      if (Array.isArray(payload?.problems) && payload.problems.length) {
        message = payload.problems.map((p) => `${p.field}: ${p.message}`).join('; ');
      }
      throw new ApiError(message, response.status, payload);
    }
    return payload;
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new ApiError('The request timed out. The server may still be starting up.', 0, null);
    }
    if (error instanceof ApiError) throw error;
    const target = apiBase() || 'this origin';
    throw new ApiError(
      `Could not reach the API at ${target}. If the backend is hosted separately, ` +
      'set its URL from the connection panel.',
      0,
      null
    );
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  health: () => request('/api/health', { timeout: 15000 }),
  catalog: () => request('/api/catalog'),
  scoringMethodology: () => request('/api/catalog/scoring'),
  requirements: (company, role, level) =>
    request(`/api/catalog/requirements/${encodeURIComponent(company)}/${encodeURIComponent(role)}?level=${encodeURIComponent(level)}`),

  uploadResume: (file) => {
    const form = new FormData();
    form.append('file', file);
    return request('/api/resume/upload', { method: 'POST', body: form, isForm: true });
  },
  parseText: (text) => {
    const form = new FormData();
    form.append('resume_text', text);
    return request('/api/resume/parse-text', { method: 'POST', body: form, isForm: true });
  },

  getResume: (id) => request(`/api/resume/${id}`),
  analyze: (payload) => request('/api/analyze', { method: 'POST', body: payload }),
  analyzeJobDescription: (payload) =>
    request('/api/analyze/job-description', { method: 'POST', body: payload }),
  getAnalysis: (id) => request(`/api/analysis/${id}`),
  listAnalyses: (resumeId) =>
    request(`/api/analyses${resumeId ? `?resume_id=${resumeId}` : ''}`),
  recommendProjects: (payload) => request('/api/projects/recommend', { method: 'POST', body: payload }),
  chat: (payload) => request('/api/chat', { method: 'POST', body: payload, timeout: 60000 }),
  chatStarters: () => request('/api/chat/starters'),
};
