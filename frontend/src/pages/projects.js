/** Project recommendations — ranked by the weighted gap each one closes. */

import { copyText, emptyState, esc, escWithPlaceholders, on, plural } from '../components/ui.js';
import { getState } from '../services/state.js';

export const projectsPage = {
  title: 'Project recommendations',
  subtitle: 'The honest route to a skill you do not have yet: build it, then claim it',

  render() {
    const { analysis } = getState();
    if (!analysis) {
      return `<div class="page">${emptyState(
        'No analysis yet',
        'Run an analysis and the recommender will rank projects by how much of your specific gap each one closes.',
        'Start here',
        'upload'
      )}</div>`;
    }

    const projects = analysis.project_recommendations;
    const target = analysis.target;

    if (!projects.length) {
      return `<div class="page">${emptyState(
        'No project needed',
        'Your resume already evidences the skills this target screens for. Focus on depth and measurable results instead.',
        'Back to dashboard',
        'dashboard'
      )}</div>`;
    }

    return `
    <div class="page fade-up">
      <div class="card">
        <div class="row between wrap">
          <div>
            <h2>Projects that close your ${esc(target.company.name)} gap</h2>
            <p class="small muted">
              Ranked by importance-weighted gap coverage, then role fit, company fit and difficulty
              suitability for ${esc(target.level.title.toLowerCase())}.
            </p>
          </div>
          <span class="chip solid">${plural(projects.length, 'recommendation')}</span>
        </div>
      </div>

      <div class="row" style="padding:14px 18px;border-radius:14px;background:var(--success-soft);border:1px solid color-mix(in srgb, var(--success) 24%, transparent)">
        <span class="small">
          <strong>Add the resume bullet only after you have finished the project</strong> and can demo or
          link it. Each card includes a bullet template with blanks — fill them with your own real numbers.
        </span>
      </div>

      <div class="grid cols-2">
        ${projects.map((project) => projectCard(project)).join('')}
      </div>

      <div class="card">
        <div class="card-head"><div class="title"><h3>Explore other gaps</h3>
          <span class="sub">Enter any skills and see which projects teach them</span></div></div>
        <div class="row wrap" style="gap:10px">
          <input class="input" id="skill-query" style="flex:1;min-width:240px"
                 placeholder="e.g. Kubernetes, Terraform, Kafka" />
          <button class="btn" id="skill-search">Find projects</button>
        </div>
        <div id="adhoc-results" style="margin-top:16px"></div>
      </div>
    </div>`;
  },

  mount(root, ctx) {
    on(root, '[data-route]', (_e, node) => ctx.navigate(node.dataset.route));
    on(root, '[data-copy]', (_e, node) =>
      copyText(decodeURIComponent(node.dataset.copy), 'Template copied — replace every blank with real detail')
    );
    on(root, '[data-expand]', (_e, node) => {
      const box = root.querySelector(`#detail-${node.dataset.expand}`);
      if (!box) return;
      box.hidden = !box.hidden;
      node.textContent = box.hidden ? 'Show learning objectives' : 'Hide learning objectives';
    });

    const search = root.querySelector('#skill-search');
    if (!search) return;
    search.addEventListener('click', async () => {
      const raw = root.querySelector('#skill-query').value.trim();
      const results = root.querySelector('#adhoc-results');
      if (!raw) return;
      const skills = raw.split(/[,;]/).map((s) => s.trim()).filter(Boolean);
      results.innerHTML = '<div class="row"><div class="spinner"></div><span class="small muted">Searching…</span></div>';
      try {
        const { target } = getState();
        const response = await ctx.api.recommendProjects({
          missing_skills: skills,
          role: target.role,
          company: target.company,
          level: target.level,
          limit: 4,
        });
        results.innerHTML = `
          ${
            response.unrecognised_skills.length
              ? `<p class="small muted" style="margin-bottom:10px">Not in the ontology:
                   ${response.unrecognised_skills.map((s) => `<span class="chip mute">${esc(s)}</span>`).join(' ')}</p>`
              : ''
          }
          <div class="grid cols-2">${response.projects.map((p) => projectCard(p, true)).join('')}</div>`;
      } catch (error) {
        results.innerHTML = `<span class="chip bad">${esc(error.message)}</span>`;
      }
    });
  },
};

function projectCard(project, compact = false) {
  const difficultyTone = { Beginner: 'ok', Intermediate: 'warn', Advanced: 'bad' }[project.difficulty] || 'mute';
  return `
  <article class="project-card">
    <header>
      <div class="row between wrap" style="margin-bottom:8px">
        <span class="chip ${project.priority === 'high' ? 'bad' : 'warn'} tiny">${esc(project.priority)} priority</span>
        <span class="chip mute tiny">fit ${project.fit_score.toFixed(0)}/100</span>
      </div>
      <h3>${esc(project.title)}</h3>
      <p class="small muted">${esc(project.description)}</p>
    </header>
    <div class="body">
      <div class="meta-row">
        <span class="chip ${difficultyTone}">${esc(project.difficulty)}</span>
        <span class="chip mute">${esc(project.estimated_duration)}</span>
        <span class="chip solid">closes ${project.skills_closed.length} gap${project.skills_closed.length === 1 ? '' : 's'}</span>
      </div>

      <div>
        <div class="tiny faint" style="margin-bottom:7px">CLOSES THESE GAPS</div>
        <div class="chip-row">${project.skills_closed.map((s) => `<span class="chip bad">${esc(s)}</span>`).join('')}</div>
      </div>

      <div>
        <div class="tiny faint" style="margin-bottom:7px">SKILLS GAINED</div>
        <div class="chip-row">${project.skills_gained
          .map((s) => `<span class="chip mute">${esc(s)}</span>`)
          .join('')}</div>
      </div>

      ${
        compact
          ? ''
          : `<button class="btn sm ghost" data-expand="${esc(project.id)}">Show learning objectives</button>
             <div id="detail-${esc(project.id)}" hidden class="col" style="gap:12px">
               <div>
                 <div class="tiny faint" style="margin-bottom:6px">LEARNING OBJECTIVES</div>
                 <ul class="objectives">${project.learning_objectives
                   .map((objective) => `<li>${esc(objective)}</li>`)
                   .join('')}</ul>
               </div>
               <div>
                 <div class="tiny faint" style="margin-bottom:6px">DELIVERABLES</div>
                 <ul class="objectives">${project.deliverables.map((d) => `<li>${esc(d)}</li>`).join('')}</ul>
               </div>
               ${
                 project.prerequisites?.length
                   ? `<div><div class="tiny faint" style="margin-bottom:6px">PREREQUISITES</div>
                        <div class="chip-row">${project.prerequisites
                          .map((p) => `<span class="chip mute">${esc(p)}</span>`)
                          .join('')}</div></div>`
                   : ''
               }
             </div>`
      }

      <div>
        <div class="row between" style="margin-bottom:7px">
          <span class="tiny faint">RESUME BULLET TEMPLATE — AFTER YOU FINISH IT</span>
          <button class="btn sm ghost" data-copy="${encodeURIComponent(project.resume_bullet_template)}">Copy</button>
        </div>
        <div class="bullet-template">${escWithPlaceholders(project.resume_bullet_template)}</div>
      </div>

      ${
        project.verification
          ? `<p class="tiny" style="color:var(--warn-text)">⚑ ${esc(project.verification)}</p>`
          : ''
      }
    </div>
    <div class="fit">
      <span class="muted">${esc(project.rationale)}</span>
    </div>
  </article>`;
}
