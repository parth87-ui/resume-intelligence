/**
 * Application state.
 *
 * A tiny observable store. The resume id and target selection survive a page
 * reload via sessionStorage; the analysis payload itself is kept in memory
 * (it is large, and re-fetchable by id).
 */

const KEY = 'resume-intelligence.session';

const state = {
  catalog: null,
  resume: null, // upload response
  target: { company: null, role: null, level: 'entry' },
  analysis: null,
  jobDescription: '',
  status: 'idle', // idle | uploading | analysing | ready
  health: null,
};

const listeners = new Set();

export function getState() {
  return state;
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setState(patch) {
  Object.assign(state, patch);
  persist();
  listeners.forEach((listener) => listener(state));
}

export function setTarget(patch) {
  state.target = { ...state.target, ...patch };
  persist();
  listeners.forEach((listener) => listener(state));
}

function persist() {
  try {
    sessionStorage.setItem(
      KEY,
      JSON.stringify({
        resumeId: state.resume?.resume_id ?? null,
        resumeName: state.resume?.file_name ?? null,
        target: state.target,
        analysisId: state.analysis?.analysis_id ?? null,
      })
    );
  } catch {
    /* private browsing or storage disabled - the app still works in-memory */
  }
}

export function readPersisted() {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function clearSession() {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
  Object.assign(state, {
    resume: null,
    analysis: null,
    jobDescription: '',
    status: 'idle',
    target: { company: null, role: null, level: 'entry' },
  });
  listeners.forEach((listener) => listener(state));
}

export function hasAnalysis() {
  return Boolean(state.analysis);
}

export function targetReady() {
  return Boolean(state.target.company && state.target.role && state.resume);
}
