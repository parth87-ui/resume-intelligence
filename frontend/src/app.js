/**
 * Application shell: hash router, sidebar, topbar and the analysis workflow.
 */

import { initChat } from './components/chat.js';
import { esc, loadingPage, on, toast } from './components/ui.js';
import { dashboardPage } from './pages/dashboard.js';
import { gapsPage } from './pages/gaps.js';
import { landing } from './pages/landing.js';
import { projectsPage } from './pages/projects.js';
import { roadmapPage } from './pages/roadmap.js';
import { targetPage } from './pages/target.js';
import { uploadPage } from './pages/upload.js';
import { api } from './services/api.js';
import { clearSession, getState, readPersisted, setState, setTarget } from './services/state.js';
import { getTheme, initTheme, toggleTheme } from './services/theme.js';
import { apiBase, describeTarget, setApiBase } from './services/config.js';

const ROUTES = {
  home: { page: landing, icon: '◈', label: 'Overview', group: 'start' },
  upload: { page: uploadPage, icon: '⬆', label: 'Upload resume', group: 'start' },
  target: { page: targetPage, icon: '◎', label: 'Target selection', group: 'start' },
  dashboard: { page: dashboardPage, icon: '▦', label: 'Analysis dashboard', group: 'results', needsAnalysis: true },
  gaps: { page: gapsPage, icon: '△', label: 'Skill gaps', group: 'results', needsAnalysis: true },
  projects: { page: projectsPage, icon: '◱', label: 'Projects', group: 'results', needsAnalysis: true },
  roadmap: { page: roadmapPage, icon: '⇗', label: 'Learning roadmap', group: 'results', needsAnalysis: true },
};

const root = document.getElementById('app');
let currentRoute = 'home';

const ctx = {
  api,
  navigate,
  refreshShell,
  runAnalysis,
  runJobDescriptionAnalysis,
};

boot();

async function boot() {
  initTheme();

  // Read the stored session *first*: any setState below re-persists the
  // (still empty) state and would otherwise wipe the ids we need.
  const persisted = readPersisted();

  renderShell();
  window.addEventListener('hashchange', () => {
    currentRoute = routeFromHash();
    renderPage();
  });

  currentRoute = routeFromHash();
  renderPage();

  try {
    const [health, catalog] = await Promise.all([api.health(), api.catalog()]);
    setState({ health, catalog });
    restoreSession(catalog, persisted);
    refreshShell();
    if (currentRoute === 'home' || currentRoute === 'target') renderPage();
  } catch (error) {
    toast(error.message, 'error', 9000);
    const banner = document.getElementById('health-chip');
    if (banner) {
      banner.className = 'chip bad';
      banner.textContent = 'API unreachable';
    }
    showConnectionPanel(error.message);
  }

  initChat();
}

function restoreSession(catalog, saved) {
  if (!saved || (!saved.resumeId && !saved.analysisId)) {
    setTarget(saved?.target || { company: catalog.companies[0]?.id ?? null, role: null, level: 'entry' });
    return;
  }
  if (saved.target) setTarget(saved.target);
  if (saved.resumeId) {
    // Re-attach the stored resume without forcing a re-upload.
    api
      .getResume(saved.resumeId)
      .then((stored) => {
        if (!stored) return;
        setState({
          resume: {
            resume_id: stored.resume_id,
            file_name: stored.file_name,
            contact: stored.contact,
            sections_detected: stored.parsed?.metadata?.sections_detected ?? [],
            skills_detected: [],
            skill_profile: { total: 0, applied: 0, by_category: {} },
            metadata: stored.parsed?.metadata ?? {},
            warnings: [],
            parsed: stored.parsed,
          },
        });
        refreshShell();
      })
      .catch(() => {});
  }
  if (saved.analysisId) {
    api
      .getAnalysis(saved.analysisId)
      .then((analysis) => {
        setState({ analysis, status: 'ready' });
        refreshShell();
        if (ROUTES[currentRoute]?.needsAnalysis) renderPage();
      })
      .catch(() => {});
  }
}

/**
 * Shown when the API is unreachable. On a split deploy (static frontend on one
 * host, FastAPI on another) this is how the two halves get introduced.
 */
function showConnectionPanel(reason) {
  const view = document.getElementById('view');
  if (!view) return;
  view.innerHTML = `
    <div class="page fade-up">
      <div class="card pad-lg" style="max-width:720px;margin:40px auto">
        <div class="card-head">
          <div class="title">
            <h3>Connect to your API</h3>
            <span class="sub">The dashboard is static; the analysis engine runs separately.</span>
          </div>
        </div>
        <p class="small muted">${esc(reason)}</p>
        <div class="field" style="margin-top:18px">
          <label for="api-base-input">Backend base URL</label>
          <input class="input" id="api-base-input" placeholder="https://your-api.onrender.com"
                 value="${esc(apiBase())}" autocomplete="url" spellcheck="false" />
          <span class="tiny faint">
            Currently targeting ${esc(describeTarget())}. Include the scheme, no trailing path.
          </span>
        </div>
        <div class="row wrap" style="margin-top:16px;gap:10px">
          <button class="btn primary" id="api-connect">Connect</button>
          <button class="btn ghost" id="api-same-origin">Use this origin</button>
        </div>
        <hr class="divider"/>
        <p class="tiny faint">
          Running locally? Start the backend with <span class="mono">python run.py</span> and use
          <span class="mono">http://127.0.0.1:8000</span>. The backend must allow this origin via
          <span class="mono">CORS_ORIGINS</span>.
        </p>
      </div>
    </div>`;

  const input = document.getElementById('api-base-input');
  const reconnect = (value) => {
    setApiBase(value);
    window.location.reload();
  };
  document.getElementById('api-connect').addEventListener('click', () => {
    const value = input.value.trim();
    if (!value) {
      toast('Enter the backend URL, or choose "Use this origin".', 'error');
      return;
    }
    reconnect(value);
  });
  document.getElementById('api-same-origin').addEventListener('click', () => reconnect(''));
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') document.getElementById('api-connect').click();
  });
}

function routeFromHash() {
  const key = (window.location.hash || '#/home').replace(/^#\/?/, '') || 'home';
  return ROUTES[key] ? key : 'home';
}

function navigate(route) {
  if (!ROUTES[route]) return;
  window.location.hash = `#/${route}`;
}

function renderShell() {
  root.innerHTML = `
    <div class="app">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-mark">RI</div>
          <div class="brand-text">
            <strong>Resume Intelligence</strong>
            <span>Developed by Parth Khandelwal</span>
          </div>
        </div>
        <nav class="nav" id="nav"></nav>
        <div class="sidebar-foot">
          <div class="row between">
            <span class="tiny faint" id="engine-line">engine starting…</span>
          </div>
          <button class="btn sm ghost block" id="reset-btn" style="margin-top:10px">Start over</button>
          <a class="tiny faint" href="/docs" target="_blank" rel="noopener"
             style="display:block;margin-top:10px;text-align:center">API documentation ↗</a>
        </div>
      </aside>
      <main class="main">
        <header class="topbar">
          <h2 id="page-title">Overview</h2>
          <span class="tiny faint" id="page-subtitle"></span>
          <div class="topbar-meta" id="topbar-meta"></div>
          <button class="btn sm ghost theme-toggle" id="theme-btn" type="button"
                  title="Switch between the light and dark palette"></button>
        </header>
        <div id="view"></div>
      </main>
    </div>`;

  on(root, '[data-nav]', (_ev, node) => navigate(node.dataset.nav));

  const themeButton = document.getElementById('theme-btn');
  const paintThemeButton = () => {
    const dark = getTheme() === 'dark';
    themeButton.textContent = dark ? '☀' : '☾';
    themeButton.setAttribute('aria-label', dark ? 'Switch to the light theme' : 'Switch to the dark theme');
  };
  paintThemeButton();
  themeButton.addEventListener('click', () => {
    toggleTheme();
    paintThemeButton();
    // Charts bake token values into their SVG at render time, so redraw them.
    renderPage();
  });
  document.getElementById('reset-btn').addEventListener('click', () => {
    clearSession();
    refreshShell();
    navigate('home');
    renderPage();
    toast('Session cleared.', 'success');
  });
  refreshShell();
}

function refreshShell() {
  const state = getState();
  const nav = document.getElementById('nav');
  if (!nav) return;

  const groups = [
    ['start', 'Get started'],
    ['results', 'Your analysis'],
  ];
  nav.innerHTML = groups
    .map(
      ([group, label]) => `
      <div class="nav-label">${esc(label)}</div>
      ${Object.entries(ROUTES)
        .filter(([, route]) => route.group === group)
        .map(([key, route]) => {
          const locked = route.needsAnalysis && !state.analysis;
          return `
          <button class="nav-item ${currentRoute === key ? 'active' : ''}" data-nav="${key}" ${locked ? 'disabled' : ''}>
            <span class="ico">${route.icon}</span>${esc(route.label)}
            ${!locked && route.needsAnalysis ? '<span class="badge-dot"></span>' : ''}
          </button>`;
        })
        .join('')}`
    )
    .join('');

  const engineLine = document.getElementById('engine-line');
  if (engineLine && state.health) {
    engineLine.textContent = `NLP: ${state.health.nlp_backend.backend} · AI: ${state.health.ai_engine.mode}`;
  }

  const meta = document.getElementById('topbar-meta');
  if (meta) {
    const chips = [];
    if (state.resume) chips.push(`<span class="chip ok"><span class="dot"></span>${esc(state.resume.file_name)}</span>`);
    if (state.analysis) {
      const score = state.analysis.scoring.overall_score;
      chips.push(
        `<span class="chip solid">${esc(state.analysis.target.company.name)} · ${esc(state.analysis.target.role.title)}</span>`,
        `<span class="chip ${score >= 70 ? 'ok' : score >= 55 ? 'warn' : 'bad'}">${score.toFixed(0)}/100</span>`
      );
    }
    chips.push(
      `<span class="chip ${state.health ? 'mute' : 'warn'}" id="health-chip">${
        state.health ? `v${esc(state.health.version)}` : 'connecting…'
      }</span>`
    );
    meta.innerHTML = chips.join('');
  }
}

function renderPage() {
  const route = ROUTES[currentRoute] || ROUTES.home;
  const view = document.getElementById('view');
  const state = getState();

  document.getElementById('page-title').textContent = route.page.title;
  document.getElementById('page-subtitle').textContent = route.page.subtitle || '';
  document.title = `${route.page.title} · Resume Intelligence`;

  if (state.status === 'analysing') {
    view.innerHTML = loadingPage('Running the analysis pipeline…');
    return;
  }

  view.innerHTML = route.page.render(state);
  try {
    route.page.mount?.(view, ctx);
  } catch (error) {
    // A page-level failure must not take the whole shell down with it.
    console.error(`Failed to mount the ${currentRoute} page:`, error);
    toast('Something went wrong rendering this page. Try reloading.', 'error');
  }
  refreshShell();
  const scroller = document.querySelector('.main');
  if (scroller) scroller.scrollTop = 0;
}

async function runAnalysis() {
  const { resume, target } = getState();
  if (!resume) {
    toast('Upload a resume first.', 'error');
    navigate('upload');
    return;
  }
  if (!target.company || !target.role) {
    toast('Pick a target company and role.', 'error');
    return;
  }

  setState({ status: 'analysing' });
  navigate('dashboard');
  renderPage();

  try {
    const analysis = await api.analyze({
      resume_id: resume.resume_id,
      company: target.company,
      role: target.role,
      level: target.level,
      persist: true,
    });
    setState({ analysis, status: 'ready' });
    renderPage();
    toast(
      `Analysis complete — ${analysis.scoring.overall_score.toFixed(0)}/100 (${analysis.scoring.band}).`,
      'success'
    );
  } catch (error) {
    setState({ status: 'idle' });
    renderPage();
    toast(error.message, 'error', 9000);
  }
}

async function runJobDescriptionAnalysis(jobDescription, fuse) {
  const { resume, target } = getState();
  if (!resume) {
    toast('Upload a resume first.', 'error');
    navigate('upload');
    return;
  }

  setState({ status: 'analysing' });
  navigate('dashboard');
  renderPage();

  try {
    const payload = {
      resume_id: resume.resume_id,
      job_description: jobDescription,
      level: target.level,
      persist: true,
    };
    if (fuse && target.company && target.role) {
      payload.company = target.company;
      payload.role = target.role;
    }
    const analysis = await api.analyzeJobDescription(payload);
    setState({ analysis, status: 'ready' });
    renderPage();
    const detected = analysis.job_description_analysis;
    toast(
      `Job description analysed — ${analysis.scoring.overall_score.toFixed(0)}/100 against ${
        detected.detected_role || 'the posting'
      }.`,
      'success'
    );
  } catch (error) {
    setState({ status: 'idle' });
    renderPage();
    toast(error.message, 'error', 9000);
  }
}
