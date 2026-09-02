/**
 * Theme control.
 *
 * Light ("bright") is the default. The choice is written to
 * `document.documentElement[data-theme]`, which is all the CSS reads, and
 * remembered in localStorage. Every colour in the app resolves through design
 * tokens, so switching is a single attribute change - including the SVG charts,
 * which read the same tokens.
 */

const KEY = 'resume-intelligence.theme';
const THEMES = ['light', 'dark'];

export function getTheme() {
  try {
    const stored = localStorage.getItem(KEY);
    if (THEMES.includes(stored)) return stored;
  } catch {
    /* storage unavailable (private mode) - fall through to the default */
  }
  return 'light';
}

export function applyTheme(theme) {
  const next = THEMES.includes(theme) ? theme : 'light';
  // The light palette lives on bare :root, so the attribute is only set for dark.
  if (next === 'dark') {
    document.documentElement.setAttribute('data-theme', 'dark');
  } else {
    document.documentElement.removeAttribute('data-theme');
  }
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* not fatal - the theme still applies for this session */
  }
  return next;
}

export function toggleTheme() {
  return applyTheme(getTheme() === 'dark' ? 'light' : 'dark');
}

/** Call before first paint so the correct palette is in place immediately. */
export function initTheme() {
  return applyTheme(getTheme());
}
