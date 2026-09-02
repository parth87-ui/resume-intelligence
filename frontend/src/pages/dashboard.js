/** Analysis dashboard — score, breakdown, charts, ATS and AI rewrites. */

import {
  activateChartTooltips,
  barList,
  donut,
  gauge,
  legend,
  radar,
  readinessBars,
} from '../components/charts.js';
import {
  copyText,
  countUp,
  emptyState,
  esc,
  escWithPlaceholders,
  on,
  plural,
  scoreColor,
} from '../components/ui.js';
import { getState } from '../services/state.js';

// Matched / partial / missing / optional, as design tokens so the slices track
// the active theme (the API also ships fallback hex for non-browser consumers).
const PIE_COLORS = ['var(--success)', 'var(--warn)', 'var(--danger)', 'var(--neutral)'];

export const dashboardPage = {
  title: 'Analysis dashboard',
  subtitle: 'Explainable compatibility scoring for your selected target',

  render() {
    const { analysis } = getState();
    if (!analysis) {
      return `<div class="page">${emptyState(
        'No analysis yet',
        'Upload a resume and pick a target company and role to see your compatibility breakdown.',
        'Start here',
        'upload'
      )}</div>`;
    }

    const scoring = analysis.scoring;
    const ats = analysis.ats;
    const target = analysis.target;
    const overview = analysis.resume_overview;
    const charts = analysis.charts;
    const counts = analysis.skill_gap.counts;

    return `
    <div class="page fade-up">
      <!-- ---------------------------------------------------- overview -- -->
      <div class="grid cols-4">
        ${statCard('Candidate', esc(overview.contact.name || 'Not detected'),
          `${esc(overview.contact.email || 'no email found')}`, true)}
        ${statCard('Target', esc(`${target.company.name}`),
          `${esc(target.role.title)} · ${esc(target.level.title)}`, true)}
        ${statCard('Match score', `<span data-count="${scoring.overall_score}" style="color:${scoreColor(scoring.overall_score)}">0</span>`,
          esc(scoring.band))}
        ${statCard('ATS score', `<span data-count="${ats.score}" style="color:${scoreColor(ats.score)}">0</span>`,
          esc(ats.band))}
      </div>

      <!-- ------------------------------------------------- score + why -- -->
      <div class="grid score-layout">
        <div class="card pad-lg">
          <div class="score-hero">
            <div class="chart-wrap">${gauge(scoring.overall_score, { band: scoring.band })}</div>
            <div class="band" style="color:${scoreColor(scoring.overall_score)}">${esc(scoring.band)}</div>
            <p class="msg">${esc(scoring.band_message)}</p>
            <div class="chip-row" style="justify-content:center">
              <span class="chip ok">${counts.matched} matched</span>
              <span class="chip warn">${counts.partial} partial</span>
              <span class="chip bad">${counts.missing_high + counts.missing_medium + counts.missing_low} missing</span>
            </div>
          </div>
        </div>

        <div class="card pad-lg">
          <div class="card-head">
            <div class="title"><h3>Score breakdown</h3>
              <span class="sub">${esc(scoring.methodology.formula)}</span></div>
            <div class="actions"><button class="btn sm ghost" data-toggle="methodology">Methodology</button></div>
          </div>
          <div id="methodology" hidden>
            <p class="small muted" style="margin-bottom:14px">${esc(scoring.methodology.note)}</p>
          </div>
          ${scoring.breakdown
            .map(
              (component) => `
            <div class="breakdown-row">
              <div class="name">${esc(component.label)}
                <small>${esc(component.method)}</small></div>
              <div class="track" style="height:8px;border-radius:99px;background:var(--track);overflow:hidden">
                <div style="height:100%;width:${component.score}%;border-radius:99px;background:${scoreColor(component.score)};transition:width .9s var(--ease)"></div>
              </div>
              <div class="score-cell">${component.score.toFixed(0)}
                <small>${component.weight_percent.toFixed(0)}% weight</small></div>
            </div>
            <div class="breakdown-detail">${esc(component.detail)}</div>`
            )
            .join('')}
          <div class="row" style="margin-top:12px;padding:12px;border-radius:11px;background:var(--accent-soft);border:1px solid color-mix(in srgb, var(--accent) 22%, transparent)">
            <span class="small">${esc(scoring.narrative)}</span>
          </div>
        </div>
      </div>

      <!-- ------------------------------------------------------ charts -- -->
      <div class="grid cols-3">
        <div class="card">
          <div class="card-head"><div class="title"><h3>Skill coverage</h3>
            <span class="sub">Against ${counts.total_requirements} target requirements</span></div></div>
          <div class="chart-wrap">${donut(charts.skill_pie.labels, charts.skill_pie.values, PIE_COLORS, {
            centreLabel: 'requirements',
          })}</div>
          ${legend(charts.skill_pie.labels, PIE_COLORS, charts.skill_pie.values)}
        </div>

        <div class="card">
          <div class="card-head"><div class="title"><h3>You vs the target</h3>
            <span class="sub">Coverage by skill category</span></div></div>
          <div class="chart-wrap">${radar(charts.radar.axes)}</div>
        </div>

        <div class="card">
          <div class="card-head"><div class="title"><h3>Biggest gaps</h3>
            <span class="sub">Bar length = importance to this target</span></div></div>
          ${barList(
            charts.missing_bar.labels.map((label, i) => ({
              label,
              value: charts.missing_bar.values[i],
              color:
                charts.missing_bar.priorities[i] === 'high'
                  ? 'var(--danger)'
                  : charts.missing_bar.priorities[i] === 'medium'
                  ? 'var(--warn)'
                  : 'var(--neutral)',
              tip: `${label} — ${charts.missing_bar.priorities[i]} priority, currently ${charts.missing_bar.statuses[i]}`,
            })),
            { suffix: '' }
          )}
          <button class="btn sm ghost block" style="margin-top:14px" data-route="gaps">See full gap analysis →</button>
        </div>
      </div>

      <!-- -------------------------------------------- insights + ready -- -->
      <div class="grid split">
        <div class="card">
          <div class="card-head"><div class="title"><h3>What this means</h3>
            <span class="sub">Generated from your analysis, not a template</span></div></div>
          ${analysis.insights
            .map(
              (insight) => `
            <div class="insight ${esc(insight.type)}">
              <div class="mark">${markFor(insight.type)}</div>
              <div><h4>${esc(insight.title)}</h4><p>${esc(insight.body)}</p></div>
            </div>`
            )
            .join('')}
        </div>

        <div class="card">
          <div class="card-head"><div class="title"><h3>Job readiness projection</h3>
            <span class="sub">Same formula, applied to the roadmap outcomes</span></div></div>
          ${readinessBars(charts.readiness)}
          <p class="tiny faint" style="margin-top:14px">
            ${esc(analysis.learning_roadmap.projection.note)}
          </p>
          <button class="btn sm ghost block" style="margin-top:12px" data-route="roadmap">Open the roadmap →</button>
        </div>
      </div>

      <!-- ----------------------------------------------- section scores -- -->
      ${!analysis.section_scores ? '' : `
      <div class="card">
        <div class="card-head">
          <div class="title"><h3>Resume section scores</h3>
            <span class="sub">${esc(analysis.section_scores.summary)}</span></div>
          <div class="actions">
            <span class="chip ${scoreTone(analysis.section_scores.overall)}">
              ${analysis.section_scores.overall.toFixed(0)}/100 average</span>
          </div>
        </div>
        <div class="section-scores">
          ${analysis.section_scores.sections
            .map(
              (section) => `
            <div class="section-row" data-section-toggle="${esc(section.key)}">
              <div class="head">
                <span class="nm">${esc(section.label)}</span>
                <span class="chip ${verdictTone(section.verdict)} tiny">${esc(section.verdict)}</span>
                <span class="spacer"></span>
                <span class="val tabular">${section.score.toFixed(0)}</span>
                <span class="caret" aria-hidden="true">▾</span>
              </div>
              <div class="progress"><span style="width:${Math.max(2, section.score)}%;
                background:${scoreColor(section.score)}"></span></div>
              <div class="checks" id="section-${esc(section.key)}" hidden>
                ${section.checks
                  .map(
                    (check) => `
                  <div class="ats-check">
                    <div class="status ${esc(check.status)}">${
                      check.status === 'pass' ? '✓' : check.status === 'warn' ? '!' : '✗'
                    }</div>
                    <div class="body">
                      <div class="label">${esc(check.label)}
                        <span class="pts">${check.points.toFixed(1)} / ${check.max_points}</span></div>
                      <div class="msg">${esc(check.detail)}</div>
                    </div>
                  </div>`
                  )
                  .join('')}
              </div>
            </div>`
            )
            .join('')}
        </div>
        <p class="tiny faint" style="margin-top:14px">${esc(analysis.section_scores.note)}</p>
      </div>`}

      <!-- --------------------------------------------------------- ATS -- -->
      <div class="grid split">
        <div class="card">
          <div class="card-head">
            <div class="title"><h3>ATS compatibility</h3>
              <span class="sub">${esc(ats.summary)}</span></div>
            <div class="actions"><span class="chip ${ats.score >= 70 ? 'ok' : ats.score >= 55 ? 'warn' : 'bad'}">${ats.score.toFixed(0)}/100</span></div>
          </div>
          <div style="margin-bottom:16px">
            ${barList(
              analysis.charts.ats_families.map((family) => ({
                label: family.label,
                value: family.score,
                color: scoreColor(family.score),
              })),
              { suffix: '' }
            )}
          </div>
          <div id="ats-checks">
            ${ats.checks
              .map(
                (check) => `
              <div class="ats-check">
                <div class="status ${esc(check.status)}">${check.status === 'pass' ? '✓' : check.status === 'warn' ? '!' : '✗'}</div>
                <div class="body">
                  <div class="label">${esc(check.label)}
                    <span class="pts">${check.points.toFixed(1)} / ${check.max_points}</span></div>
                  <div class="msg">${esc(check.message)}</div>
                  ${check.suggestion ? `<div class="fix">→ ${esc(check.suggestion)}</div>` : ''}
                </div>
              </div>`
              )
              .join('')}
          </div>
        </div>

        <div class="card">
          <div class="card-head"><div class="title"><h3>Do these first</h3>
            <span class="sub">Ordered by impact per unit of effort</span></div></div>
          ${
            analysis.ai_suggestions.priority_actions.length
              ? analysis.ai_suggestions.priority_actions
                  .map(
                    (action, i) => `
              <div class="action-item ${esc(action.priority)}">
                <div class="rank">${i + 1}</div>
                <div>
                  <div class="row wrap" style="gap:8px">
                    <strong class="small">${esc(action.action)}</strong>
                    <span class="chip ${action.priority === 'high' ? 'bad' : 'warn'} tiny">${esc(action.priority)}</span>
                    <span class="chip mute tiny">${esc(action.effort)}</span>
                  </div>
                  <p class="small muted" style="margin-top:4px">${esc(action.detail)}</p>
                </div>
              </div>`
                  )
                  .join('')
              : '<p class="small muted">No blocking actions — your resume already covers this target well.</p>'
          }
          <div class="row" style="margin-top:16px;padding:12px;border-radius:11px;background:var(--success-soft);border:1px solid color-mix(in srgb, var(--success) 22%, transparent)">
            <span class="small">${esc(analysis.ai_suggestions.ethics.principle)}</span>
          </div>
        </div>
      </div>

      <!-- ---------------------------------------------- AI suggestions -- -->
      <div class="card">
        <div class="card-head">
          <div class="title"><h3>AI resume improvements</h3>
            <span class="sub">${esc(analysis.ai_suggestions.engine.note)}</span></div>
          <div class="actions">
            <span class="chip ${analysis.ai_suggestions.engine.mode === 'llm' ? 'solid' : 'mute'}">
              ${esc(analysis.ai_suggestions.engine.mode)} engine</span>
          </div>
        </div>
        <div class="chip-row" id="suggestion-tabs" style="margin-bottom:16px">
          ${Object.entries(analysis.ai_suggestions.sections)
            .map(
              ([section, items], index) =>
                `<button class="chip ${index === 0 ? 'solid' : ''}" data-section="${esc(section)}">
                   ${esc(section)} <strong>${items.length}</strong></button>`
            )
            .join('')}
        </div>
        <div id="suggestion-body"></div>
      </div>

      <!-- --------------------------------------------- resume overview -- -->
      <div class="grid split">
        <div class="card">
          <div class="card-head"><div class="title"><h3>Skills we found in your resume</h3>
            <span class="sub">${plural(overview.skill_profile.total, 'skill')} ·
              ${overview.skill_profile.applied} demonstrated in real bullets</span></div></div>
          ${Object.entries(overview.skills_by_category)
            .map(
              ([category, items]) => `
            <div style="margin-bottom:14px">
              <div class="tiny faint" style="margin-bottom:7px">${esc(items[0].category_label.toUpperCase())}</div>
              <div class="chip-row">
                ${items
                  .map(
                    (skill) =>
                      `<span class="chip ${skill.applied ? 'ok' : 'mute'}"
                         data-tip="${esc(skill.evidence[0]?.snippet || 'Listed without supporting evidence')}">
                         ${esc(skill.name)}${skill.applied ? '' : ' <span class="tiny">listed</span>'}</span>`
                  )
                  .join('')}
              </div>
            </div>`
            )
            .join('') || '<p class="small muted">No skills matched the ontology.</p>'}
        </div>

        <div class="card">
          <div class="card-head"><div class="title"><h3>Experience &amp; education parsed</h3>
            <span class="sub">What the ATS would see</span></div></div>
          ${
            overview.experience.length
              ? overview.experience
                  .map(
                    (role) => `
              <div style="padding:11px 0;border-bottom:1px solid var(--border)">
                <div class="row between wrap">
                  <strong class="small">${esc(role.title || 'Role')}</strong>
                  <span class="tiny faint">${esc(role.date_range || 'no dates found')}</span>
                </div>
                <div class="small muted">${esc(role.organisation || '')}${role.months ? ` · ${role.months} months` : ''}</div>
                <div class="tiny faint">${plural(role.bullets.length, 'bullet')}</div>
              </div>`
                  )
                  .join('')
              : '<p class="small muted">No work experience entries were detected.</p>'
          }
          ${
            overview.education.length
              ? overview.education
                  .map(
                    (edu) => `
              <div style="padding:11px 0;border-bottom:1px solid var(--border)">
                <strong class="small">${esc(edu.degree || 'Degree')} ${esc(edu.field ? `in ${edu.field}` : '')}</strong>
                <div class="small muted">${esc(edu.institution || '')} ${edu.year ? `· ${esc(edu.year)}` : ''}
                  ${edu.score ? `· ${esc(edu.score)}` : ''}</div>
              </div>`
                  )
                  .join('')
              : ''
          }
          ${
            overview.certifications.length
              ? `<div style="padding-top:12px"><div class="tiny faint" style="margin-bottom:7px">CERTIFICATIONS</div>
                 <div class="chip-row">${overview.certifications
                   .map((cert) => `<span class="chip mute">${esc(cert)}</span>`)
                   .join('')}</div></div>`
              : ''
          }
        </div>
      </div>

      <p class="tiny faint center">
        Analysed with ${esc(analysis.pipeline.nlp_backend.detail)} ·
        similarity: ${esc(analysis.pipeline.similarity_method)} ·
        generated ${esc(new Date(analysis.generated_at).toLocaleString())}
      </p>
    </div>`;
  },

  mount(root, ctx) {
    const { analysis } = getState();
    if (!analysis) {
      on(root, '[data-route]', (_e, node) => ctx.navigate(node.dataset.route));
      return;
    }

    root.querySelectorAll('[data-count]').forEach((node) => {
      countUp(node, Number(node.dataset.count), { decimals: 0 });
    });
    const gaugeText = root.querySelector('[data-countup]');
    if (gaugeText) countUp(gaugeText, Number(gaugeText.dataset.countup), { decimals: 0 });

    activateChartTooltips(root);

    on(root, '[data-route]', (_e, node) => ctx.navigate(node.dataset.route));
    on(root, '[data-toggle="methodology"]', () => {
      const box = root.querySelector('#methodology');
      box.hidden = !box.hidden;
    });

    on(root, '[data-section-toggle]', (_e, node) => {
      const checks = root.querySelector(`#section-${node.dataset.sectionToggle}`);
      if (!checks) return;
      checks.hidden = !checks.hidden;
      node.classList.toggle('open', !checks.hidden);
    });

    const body = root.querySelector('#suggestion-body');
    const sections = analysis.ai_suggestions.sections;
    const first = Object.keys(sections)[0];
    if (body && first) renderSuggestions(body, sections[first], first);

    on(root, '[data-section]', (_e, node) => {
      root.querySelectorAll('#suggestion-tabs .chip').forEach((chip) => chip.classList.remove('solid'));
      node.classList.add('solid');
      renderSuggestions(body, sections[node.dataset.section], node.dataset.section);
    });

    on(body, '[data-copy]', (_e, node) => {
      copyText(decodeURIComponent(node.dataset.copy), 'Suggestion copied — verify it before using');
    });
  },
};

function renderSuggestions(host, items, section) {
  if (!items || !items.length) {
    host.innerHTML = `<p class="small muted">No changes suggested for your ${esc(section)} section — it already reads well for this target.</p>`;
    return;
  }
  host.innerHTML = items
    .map(
      (item) => `
    <article class="suggestion">
      <header>
        <span class="sec-name">${esc(item.section)}</span>
        <span class="chip mute tiny">${esc(item.kind)}</span>
        ${item.tags.map((tag) => `<span class="chip tiny ${tag === 'high-impact' ? 'bad' : 'mute'}">${esc(tag)}</span>`).join('')}
        <span class="spacer"></span>
        <button class="btn sm ghost" data-copy="${encodeURIComponent(item.suggested)}">Copy suggestion</button>
      </header>
      <div class="compare">
        <div class="before">
          <div class="k">Current</div>
          <div class="text muted">${esc(item.original)}</div>
        </div>
        <div class="after">
          <div class="k" style="color:var(--ok-text)">Suggested</div>
          <div class="text">${escWithPlaceholders(item.suggested)}</div>
        </div>
      </div>
      <div class="why"><strong>Why:</strong> ${esc(item.rationale)}</div>
      ${item.label ? `<div class="verify">⚠ ${esc(item.label)}</div>` : ''}
    </article>`
    )
    .join('');
}

function statCard(label, value, hint, isText = false) {
  return `
  <div class="card">
    <div class="stat">
      <span class="label">${label}</span>
      <span class="value ${isText ? 'text-value' : ''}">${value}</span>
      <span class="hint">${hint}</span>
    </div>
  </div>`;
}

function markFor(type) {
  return {
    score: '◎', gap: '△', strength: '★', 'quick-win': '⚡',
    ats: '⚑', company: '◈', section: '¶',
  }[type] || '•';
}

function scoreTone(score) {
  return score >= 80 ? 'ok' : score >= 55 ? 'warn' : 'bad';
}

function verdictTone(verdict) {
  return { strong: 'ok', adequate: 'warn', weak: 'bad', missing: 'bad' }[verdict] || 'mute';
}
