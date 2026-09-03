/** Landing page — what the platform does and how it scores. */

import { esc } from '../components/ui.js';
import { getState } from '../services/state.js';

const FEATURES = [
  {
    icon: '◈',
    title: 'Company-specific requirements',
    body: 'Requirements are composed from a role baseline, the company profile and your experience level — Amazon MLE is not scored like Google SDE.',
  },
  {
    icon: '⛁',
    title: 'Real NLP extraction',
    body: 'spaCy plus a 144-skill ontology with aliases finds what you actually did, and records where in the resume it found each skill.',
  },
  {
    icon: '％',
    title: 'Explainable scoring',
    body: 'Six weighted components, every one traceable to evidence. No black-box number, no hardcoded score.',
  },
  {
    icon: '⚑',
    title: 'ATS compatibility',
    body: 'Sixteen deterministic checks across parsability, structure, content and keywords — each worth a stated number of points.',
  },
  {
    icon: '✎',
    title: 'Truthful rewrites',
    body: 'Bullet rewrites that strengthen verbs and specificity, with bracketed placeholders where a metric belongs. It never invents one for you.',
  },
  {
    icon: '◱',
    title: 'Gap-driven projects',
    body: 'Projects are ranked by how much of your weighted gap they actually close, then sequenced into a dated learning roadmap.',
  },
];

const PIPELINE = [
  'Resume upload',
  'Parsing',
  'NLP skill extraction',
  'Company + role target',
  'Requirement analysis',
  'Similarity & matching',
  'Gap detection',
  'ATS analysis',
  'AI suggestions',
  'Projects',
  'Roadmap',
];

export const landing = {
  title: 'Resume Intelligence',
  subtitle: 'Company-specific resume analysis and career planning',

  render() {
    const { health, catalog } = getState();
    const counts = health?.datasets;
    return `
    <div class="page fade-up">
      <section class="hero">
        <span class="eyebrow"><span class="dot" style="width:6px;height:6px;border-radius:50%;background:var(--accent-2)"></span>
          AI-powered career intelligence</span>
        <h1>Stop guessing why your resume<br/>gets filtered. <span class="grad">See the exact gap.</span></h1>
        <p class="lead">
          Upload your resume, choose a target company and role, and get an explainable compatibility
          score, a prioritised skill-gap analysis, ATS diagnostics, honest rewrite suggestions and a
          project-backed learning roadmap — built for that specific target, not generic advice.
        </p>
        <p class="small faint" style="margin-top:18px">
          Developed by <strong style="color:var(--text-dim)">Parth Khandelwal</strong>
        </p>
        <div class="cta">
          <button class="btn primary" data-route="upload">Analyse my resume →</button>
          <button class="btn ghost" data-route="target">Browse companies &amp; roles</button>
        </div>
        <div class="row wrap" style="margin-top:26px;gap:9px">
          ${
            counts
              ? `<span class="chip mute">${counts.companies} companies</span>
                 <span class="chip mute">${counts.roles} roles</span>
                 <span class="chip mute">${counts.skills} skills tracked</span>
                 <span class="chip mute">${counts.projects} projects</span>
                 <span class="chip mute">${counts.curated_targets} curated company × role profiles</span>`
              : '<span class="chip mute">Connecting to the analysis engine…</span>'
          }
        </div>
      </section>

      <section class="ethics-banner">
        <h3>The rule this tool works under</h3>
        <p class="small muted">
          Optimise the presentation of genuine experience — never fabricate credentials or achievements.
          Missing skills are answered with a way to acquire them, never with a line to paste in.
          Every generated rewrite is labelled for verification, and no metric is ever invented for you.
        </p>
      </section>

      <section>
        <h2 style="margin-bottom:16px">What it actually does</h2>
        <div class="feature-grid">
          ${FEATURES.map(
            (f) => `
            <article class="feature">
              <div class="ico">${f.icon}</div>
              <h3>${esc(f.title)}</h3>
              <p>${esc(f.body)}</p>
            </article>`
          ).join('')}
        </div>
      </section>

      <section>
        <h2 style="margin-bottom:14px">The pipeline</h2>
        <div class="pipeline-strip">
          ${PIPELINE.map(
            (step, i) =>
              `<span class="step">${esc(step)}</span>${
                i < PIPELINE.length - 1 ? '<span class="arrow">→</span>' : ''
              }`
          ).join('')}
        </div>
      </section>

      <section class="grid cols-2">
        <div class="card">
          <div class="card-head"><div class="title"><h3>How the score is built</h3>
            <span class="sub">Weights shift with the experience level you select</span></div></div>
          ${
            catalog
              ? Object.entries(catalog.scoring_weights)
                  .map(
                    ([key, weight]) => `
                <div class="bar-row">
                  <div class="lbl">${esc(labelFor(key))}</div>
                  <div class="track"><div class="fill" style="width:${weight * 100 * 2.6}%"></div></div>
                  <div class="val">${(weight * 100).toFixed(0)}%</div>
                </div>`
                  )
                  .join('')
              : '<div class="skeleton" style="height:150px"></div>'
          }
          <p class="tiny faint" style="margin-top:12px">
            overall = Σ (component score × weight) ÷ Σ weights
          </p>
        </div>

        <div class="card">
          <div class="card-head"><div class="title"><h3>Evidence beats listing</h3>
            <span class="sub">How a skill earns credit</span></div></div>
          <div class="col" style="gap:12px">
            ${creditRow('Applied in experience or projects', '100%', 'ok')}
            ${creditRow('Listed in the skills section only', '80%', 'warn')}
            ${creditRow('Only an adjacent, related skill found', '35%', 'warn')}
            ${creditRow('No evidence anywhere in the resume', '0%', 'bad')}
          </div>
          <p class="tiny faint" style="margin-top:14px">
            This is why moving a skill out of your skills list and into a real bullet raises your
            score without learning anything new.
          </p>
        </div>
      </section>
    </div>`;
  },
};

function creditRow(label, value, tone) {
  return `<div class="row between" style="gap:12px">
    <span class="small">${esc(label)}</span>
    <span class="chip ${tone}">${esc(value)}</span>
  </div>`;
}

function labelFor(key) {
  return {
    skills: 'Skills match',
    keywords: 'Keyword alignment',
    experience: 'Experience relevance',
    projects: 'Project relevance',
    education: 'Education & certifications',
    semantic: 'Semantic similarity',
  }[key] || key;
}
