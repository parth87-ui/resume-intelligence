/** Learning roadmap — phased plan from current skills to job readiness. */

import { readinessBars } from '../components/charts.js';
import { emptyState, esc, on, plural } from '../components/ui.js';
import { getState } from '../services/state.js';

export const roadmapPage = {
  title: 'Learning roadmap',
  subtitle: 'Current skills → gaps → learning path → projects → job readiness',

  render() {
    const { analysis } = getState();
    if (!analysis) {
      return `<div class="page">${emptyState(
        'No analysis yet',
        'Run an analysis and the planner will sequence your gaps into dated phases.',
        'Start here',
        'upload'
      )}</div>`;
    }

    const roadmap = analysis.learning_roadmap;
    const plan = analysis.skill_priority_plan;
    const projection = roadmap.projection;

    return `
    <div class="page fade-up">
      <div class="card pad-lg">
        <div class="row between wrap">
          <div>
            <h2>${esc(roadmap.target)}</h2>
            <p class="small muted" style="margin-top:4px">
              ${plural(roadmap.phases.length, 'phase')} · ${esc(roadmap.estimated_completion)} of focused work ·
              ${roadmap.current_state.matched_count} skills already matched,
              ${roadmap.current_state.gap_count} to close
            </p>
          </div>
          <div class="chip-row">
            <span class="chip mute">${roadmap.total_duration_weeks} weeks total</span>
            <button class="btn sm ghost" data-route="projects">Projects →</button>
          </div>
        </div>
        <div class="row" style="margin-top:16px;padding:13px;border-radius:12px;background:var(--success-soft);border:1px solid color-mix(in srgb, var(--success) 24%, transparent)">
          <span class="small">${esc(roadmap.principle)}</span>
        </div>
      </div>

      <div class="grid split">
        <div class="card">
          <div class="card-head"><div class="title"><h3>The plan</h3>
            <span class="sub">Ordered so the cheapest wins come first</span></div></div>
          <div class="timeline">
            ${roadmap.phases
              .map(
                (phase) => `
              <div class="phase type-${esc(phase.type)}">
                <div class="row wrap" style="gap:9px;margin-bottom:4px">
                  <h3>Phase ${phase.phase} — ${esc(phase.title)}</h3>
                  <span class="chip mute tiny">${phase.duration_weeks} ${phase.duration_weeks === 1 ? 'week' : 'weeks'}</span>
                  <span class="chip ${toneFor(phase.type)} tiny">${esc(phase.type)}</span>
                </div>
                <p class="why">${esc(phase.why)}</p>
                <div class="steps">
                  ${phase.actions
                    .map(
                      (action) => `
                    <div class="step">
                      <div class="a">${esc(action.action)}</div>
                      ${action.detail ? `<div class="d">${esc(action.detail)}</div>` : ''}
                    </div>`
                    )
                    .join('')}
                </div>
              </div>`
              )
              .join('')}
            <div class="phase type-project" style="padding-bottom:0">
              <h3>Target readiness</h3>
              <p class="why">Re-run the analysis after each phase to see the score move for real.</p>
            </div>
          </div>
        </div>

        <div class="col" style="gap:18px">
          <div class="card">
            <div class="card-head"><div class="title"><h3>Projected skills score</h3>
              <span class="sub">Same formula as the live score</span></div></div>
            ${readinessBars({
              current: projection.current_skills_score,
              after_presentation: projection.after_presentation_fixes,
              after_learning: projection.after_closing_high_priority,
            })}
            <p class="tiny faint" style="margin-top:13px">${esc(projection.note)}</p>
          </div>

          <div class="card">
            <div class="card-head"><div class="title"><h3>Already matched</h3>
              <span class="sub">Your foundation for this target</span></div></div>
            <div class="chip-row">
              ${roadmap.current_state.matched_skills.map((skill) => `<span class="chip ok">${esc(skill)}</span>`).join('')
                || '<span class="small muted">No matched skills yet.</span>'}
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <div class="title"><h3>What to learn first</h3>
            <span class="sub">Ordered by importance to the target, then by how quickly it can be acquired</span></div>
        </div>
        <div class="table-scroll">
          <table class="plan-table">
            <thead>
              <tr><th></th><th>Skill</th><th>Category</th><th>Status</th><th>Priority</th>
                  <th>Est. weeks</th><th>Cumulative</th><th>Why</th></tr>
            </thead>
            <tbody>
              ${plan
                .map(
                  (item) => `
                <tr>
                  <td><div class="ord">${item.order}</div></td>
                  <td><strong>${esc(item.skill)}</strong>
                    ${item.related_skills.length ? `<div class="tiny faint">related: ${esc(item.related_skills.join(', '))}</div>` : ''}</td>
                  <td class="small muted">${esc(item.category)}</td>
                  <td><span class="chip ${item.status === 'partial' ? 'warn' : 'bad'} tiny">${esc(item.status)}</span></td>
                  <td><span class="chip ${item.priority === 'high' ? 'bad' : item.priority === 'medium' ? 'warn' : 'mute'} tiny">${esc(item.priority)}</span></td>
                  <td class="tabular">${item.estimated_weeks}</td>
                  <td class="tabular muted">${item.cumulative_weeks}</td>
                  <td class="small muted">${esc(item.why)}</td>
                </tr>`
                )
                .join('')}
            </tbody>
          </table>
        </div>
        ${plan.length ? '' : '<p class="small muted">No gaps to sequence — you already match this target.</p>'}
      </div>
    </div>`;
  },

  mount(root, ctx) {
    on(root, '[data-route]', (_e, node) => ctx.navigate(node.dataset.route));
  },
};

function toneFor(type) {
  return { resume: 'ok', learning: 'warn', project: 'solid', emerging: 'solid' }[type] || 'mute';
}
