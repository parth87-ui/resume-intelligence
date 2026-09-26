/**
 * Shared UI primitives: escaping, DOM helpers, toasts, formatting.
 * Everything the pages render goes through `esc()` so parsed resume content
 * can never inject markup into the dashboard.
 */

export function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Escape, then highlight `[bracketed placeholders]` and `<angle blanks>`. */
export function escWithPlaceholders(value) {
  return esc(value)
    .replace(/\[([^\]]+)\]/g, '<span class="ph">[$1]</span>')
    .replace(/&lt;([^&]+?)&gt;/g, '<span class="ph">&lt;$1&gt;</span>');
}

export function el(tag, className, html) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (html !== undefined) node.innerHTML = html;
  return node;
}

export function qs(selector, root = document) {
  return root.querySelector(selector);
}

export function qsa(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

/** Delegated click binding: `on(root, '[data-act="x"]', handler)`. */
export function on(root, selector, handler, event = 'click') {
  root.addEventListener(event, (ev) => {
    const target = ev.target.closest(selector);
    if (target && root.contains(target)) handler(ev, target);
  });
}

let toastHost = null;

export function toast(message, kind = 'info', ms = 4600) {
  if (!toastHost) {
    toastHost = el('div', 'toast-host');
    document.body.appendChild(toastHost);
  }
  const icons = { error: '⚠', success: '✓', info: 'ℹ' };
  const node = el(
    'div',
    `toast ${kind}`,
    `<span aria-hidden="true">${icons[kind] || icons.info}</span><span>${esc(message)}</span>`
  );
  node.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  toastHost.appendChild(node);
  setTimeout(() => {
    node.style.transition = 'opacity 240ms, transform 240ms';
    node.style.opacity = '0';
    node.style.transform = 'translateX(14px)';
    setTimeout(() => node.remove(), 260);
  }, ms);
}

export function copyText(text, label = 'Copied to clipboard') {
  const done = () => toast(label, 'success', 2200);
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
  } else {
    fallbackCopy(text, done);
  }
}

function fallbackCopy(text, done) {
  const area = document.createElement('textarea');
  area.value = text;
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  try {
    document.execCommand('copy');
    done();
  } catch {
    toast('Could not copy — select the text manually.', 'error');
  }
  area.remove();
}

/** Animate a number from 0 to `to`, respecting reduced-motion preferences. */
export function countUp(node, to, { duration = 1100, decimals = 0, suffix = '' } = {}) {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduced) {
    node.textContent = to.toFixed(decimals) + suffix;
    return;
  }
  const start = performance.now();
  const tick = (now) => {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    node.textContent = (to * eased).toFixed(decimals) + suffix;
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/** Hand a generated file to the browser as a download. */
export function downloadBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName || 'download';
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoking immediately can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

/** Read a design token, so JS-drawn colours follow the active theme. */
export function token(name, fallback = '') {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name);
  return value.trim() || fallback;
}

export function scoreColor(score) {
  if (score >= 85) return token('--score-excellent', '#16a34a');
  if (score >= 70) return token('--score-strong', '#22c55e');
  if (score >= 55) return token('--score-moderate', '#d97706');
  if (score >= 40) return token('--score-developing', '#ea580c');
  return token('--score-early', '#e11d48');
}

export function priorityClass(priority) {
  return { high: 'bad', medium: 'warn', low: 'mute' }[priority] || 'mute';
}

export function companyMark(name) {
  const palette = ['#ff9900', '#4285f4', '#00a4ef', '#0866ff', '#a2aaad', '#e50914', '#0f62fe', '#fa0f00', '#76b900'];
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) % 997;
  return { letter: name.charAt(0).toUpperCase(), color: palette[hash % palette.length] };
}

export function plural(count, singular, pluralForm) {
  return `${count} ${count === 1 ? singular : pluralForm || `${singular}s`}`;
}

export function skeletonBlock(height = 120) {
  return `<div class="skeleton" style="height:${height}px"></div>`;
}

export function loadingPage(message = 'Working…') {
  return `
    <div class="page fade-up">
      <div class="card pad-lg">
        <div class="row" style="gap:12px"><div class="spinner"></div><strong>${esc(message)}</strong></div>
        <p class="small muted" style="margin-top:8px">
          Parsing the document, running NLP extraction, scoring against the target and building recommendations.
        </p>
      </div>
      <div class="grid cols-3">${skeletonBlock(150)}${skeletonBlock(150)}${skeletonBlock(150)}</div>
      <div class="grid split">${skeletonBlock(300)}${skeletonBlock(300)}</div>
    </div>`;
}

export function emptyState(title, body, actionLabel, actionRoute) {
  return `
    <div class="empty fade-up">
      <h3 style="margin-bottom:8px">${esc(title)}</h3>
      <p class="small">${esc(body)}</p>
      ${actionLabel ? `<button class="btn primary" style="margin-top:16px" data-route="${esc(actionRoute)}">${esc(actionLabel)}</button>` : ''}
    </div>`;
}
