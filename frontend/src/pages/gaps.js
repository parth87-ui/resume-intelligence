/** Skill gap page — five buckets, keyword analysis and the experience read. */

import { activateChartTooltips, barList, radar } from '../components/charts.js';
import { emptyState, esc, on, plural } from '../components/ui.js';
import { getState } from '../services/state.js';

export const gapsPage = {
  title: 'Skill gap analysis',
  subtitle: 'Every requirement, resolved against your resume with its evidence',

  render() {
    const { analysis } = getState();
    if (!analysis) {
      return `<div class="page">${emptyState(
        'No analysis yet',
        'Run an analysis to see which requirements you meet and which you do not.',
        'Start here',
        'upload'
      )}</div>`;
    }

    const gap = analysis.skill_gap;
    const keywords = analysis.keyword_analysis;
    const experience = analysis.experience_analysis;
    const target = analysis.target;

    const missingAll = [
      ...gap.missing_high_priority,
      ...gap.missing_medium_priority,
      ...gap.missing_low_priority,
    ];

    return `
    <div class="page fade-up">
      <div class="card">
        <div class="row between wrap">
          <div>
            <h2>${esc(target.company.name)} · ${esc(target.role.title)}</h2>
            <p class="small muted">${esc(target.level.title)} — ${gap.counts.total_requirements} requirements evaluated,
              each weighted by how hard this target screens for it.</p>
          </div>
          <div class="chip-row">
            <span class="chip ok">${gap.counts.matched} matched</span>
            <span class="chip warn">${gap.counts.partial} partial</span>
            <span class="chip bad">${gap.counts.missing_high} high-priority gaps</span>
          </div>
        </div>
      </div>

      <div class="gap-columns">
        ${column('matched', 'Matched', gap.matched, 'Fully evidenced in your resume')}
        ${column('partial', 'Partially matched', gap.partially_matched, 'Present but not demonstrated, or only adjacent')}
        ${column('missing', 'Missing — high priority', gap.missing_high_priority, 'Essential for this role')}
        ${column('missing', 'Missing — medium priority', gap.missing_medium_priority, 'Frequently requested')}
        ${column('optional', 'Optional & nice to have', [...gap.missing_low_priority, ...gap.optional], 'Differentiators, not blockers')}
        ${
          gap.emerging.length
            ? column('optional', 'Emerging skills', gap.emerging, 'Fast-growing — few candidates can evidence these yet')
            : ''
        }
      </div>

      <div class="grid split">
        <div class="card">
          <div class="card-head"><div class="title"><h3>Gap weight by skill</h3>
            <span class="sub">How much each missing skill costs you</span></div></div>
          ${barList(
            missingAll.slice(0, 12).map((item) => ({
              label: item.skill,
              value: item.importance * 100,
              color: item.priority === 'high' ? 'var(--danger)' : item.priority === 'medium' ? 'var(--warn)' : 'var(--neutral)',
              tip: `${item.skill} — ${item.priority} priority, ${item.tier} tier, about ${item.learn_weeks} weeks to learn`,
            })),
            {}
          ) || '<p class="small muted">No missing skills.</p>'}
        </div>

        <div class="card">
          <div class="card-head"><div class="title"><h3>Coverage by category</h3>
            <span class="sub">Cyan = you, outer ring = the target</span></div></div>
          <div class="chart-wrap">${radar(analysis.charts.radar.axes)}</div>
        </div>
      </div>

      <div class="grid split">
        <div class="card">
          <div class="card-head">
            <div class="title"><h3>Keyword analysis</h3>
              <span class="sub">${keywords.present.length} of ${keywords.total} fully present ·
                ${(keywords.partial || []).length} partial · coverage ${(keywords.coverage * 100).toFixed(0)}%</span></div>
          </div>
          <div class="col" style="gap:14px">
            ${keywordGroup('Present in your resume', keywords.present, 'ok')}
            ${keywordGroup('Partially present', keywords.partial || [], 'warn')}
            ${keywordGroup('Absent', keywords.missing, 'bad')}
          </div>
          <div class="row" style="margin-top:16px;padding:12px;border-radius:11px;background:var(--warn-soft);border:1px solid color-mix(in srgb, var(--warn) 24%, transparent)">
            <span class="small">${esc(keywords.note)}</span>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><div class="title"><h3>Experience gap</h3>
            <span class="sub">${esc(experience.detail)}</span></div></div>
          <div class="grid cols-2" style="gap:14px;margin-bottom:16px">
            ${miniStat('Detected', `${experience.detected_years}`, 'years')}
            ${miniStat('Expected', `${experience.expected_years}`, 'years for this level')}
            ${miniStat('Relevance', experience.relevance.toFixed(2), 'cosine vs target')}
            ${miniStat('Quantified', `${experience.quantified_bullets}/${experience.total_bullets}`, 'bullets with a metric')}
          </div>
          ${
            experience.roles_found.length
              ? experience.roles_found
                  .map(
                    (role) => `
              <div class="row between" style="padding:9px 0;border-bottom:1px solid var(--border)">
                <div><strong class="small">${esc(role.title || 'Role')}</strong>
                  <div class="tiny faint">${esc(role.organisation || '')}</div></div>
                <div class="tiny faint">${esc(role.date_range || '—')}${role.months ? ` · ${role.months} mo` : ''}</div>
              </div>`
                  )
                  .join('')
              : '<p class="small muted">No dated work experience was detected.</p>'
          }
        </div>
      </div>

      ${
        gap.additional_skills.length
          ? `<div class="card">
              <div class="card-head"><div class="title"><h3>Skills you have that this target does not ask for</h3>
                <span class="sub">${plural(gap.additional_skills.length, 'skill')} — keep them, but let the relevant ones lead</span></div></div>
              <div class="chip-row">${gap.additional_skills.map((s) => `<span class="chip mute">${esc(s)}</span>`).join('')}</div>
            </div>`
          : ''
      }

      <div class="row wrap" style="gap:12px">
        <button class="btn primary" data-route="projects">See projects that close these gaps →</button>
        <button class="btn ghost" data-route="roadmap">Open the learning roadmap</button>
      </div>
    </div>`;
  },

  mount(root, ctx) {
    activateChartTooltips(root);
    on(root, '[data-route]', (_e, node) => ctx.navigate(node.dataset.route));
  },
};

function column(kind, title, items, subtitle) {
  return `
  <section class="gap-col ${kind}">
    <header>${title}<span class="count">${items.length}</span></header>
    <div class="list">
      ${
        items.length
          ? items.map((item) => skillRow(item)).join('')
          : `<p class="small faint" style="padding:12px">Nothing in this bucket.</p>`
      }
    </div>
    <div class="tiny faint" style="padding:9px 16px;border-top:1px solid var(--border)">${esc(subtitle)}</div>
  </section>`;
}

function skillRow(item) {
  return `
  <div class="skill-row">
    <div class="top">
      <span class="priority-pip ${esc(item.priority)}"></span>
      <span class="nm">${esc(item.skill)}</span>
      ${item.emerging ? '<span class="chip solid tiny">emerging</span>' : ''}
      <span class="weight" title="importance to this target">${(item.importance * 100).toFixed(0)}</span>
    </div>
    <div class="why">${esc(item.reason)}${
      item.status === 'missing' ? ` · about ${item.learn_weeks} weeks to learn` : ''
    }</div>
    ${item.evidence ? `<div class="evidence">${esc(item.evidence)}</div>` : ''}
  </div>`;
}

function keywordGroup(title, items, tone) {
  if (!items.length) return '';
  return `
  <div>
    <div class="tiny faint" style="margin-bottom:7px">${esc(title.toUpperCase())} (${items.length})</div>
    <div class="chip-row">${items.map((k) => `<span class="chip ${tone}">${esc(k)}</span>`).join('')}</div>
  </div>`;
}

function miniStat(label, value, hint) {
  return `
  <div style="padding:12px 14px;border-radius:12px;background:var(--raised);border:1px solid var(--border)">
    <div class="tiny faint">${esc(label.toUpperCase())}</div>
    <div style="font-size:1.28rem;font-weight:650;font-variant-numeric:tabular-nums">${esc(value)}</div>
    <div class="tiny faint">${esc(hint)}</div>
  </div>`;
}
