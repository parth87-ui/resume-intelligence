/** Target selection — company, role, experience level, or a pasted job description. */

import { api } from '../services/api.js';
import { getState, setState, setTarget } from '../services/state.js';
import { companyMark, esc, on, toast } from '../components/ui.js';

export const targetPage = {
  title: 'Choose your target',
  subtitle: 'Requirements are composed from company + role + level',

  render() {
    const { catalog, target, resume, jobDescription } = getState();
    if (!catalog) return `<div class="page"><div class="skeleton" style="height:420px"></div></div>`;

    return `
    <div class="page fade-up">
      ${
        resume
          ? ''
          : `<div class="card" style="border-color:color-mix(in srgb, var(--warn) 34%, transparent);background:var(--warn-soft)">
               <div class="row between wrap">
                 <div><strong>No resume loaded yet.</strong>
                   <div class="small muted">You can pick a target now, but analysis needs a resume first.</div></div>
                 <button class="btn" data-route="upload">Upload resume</button>
               </div>
             </div>`
      }

      <section>
        <div class="row between wrap" style="margin-bottom:14px">
          <h2>Target company</h2>
          <span class="tiny faint">Each company profile changes which skills are weighted, and how hard</span>
        </div>
        <div class="pick-grid" id="company-grid">
          ${catalog.companies
            .map((company) => {
              const mark = companyMark(company.name);
              const selected = target.company === company.id;
              return `
              <button class="pick ${selected ? 'selected' : ''}" data-company="${esc(company.id)}">
                <div class="name">
                  <span class="logo" style="background:${mark.color}">${esc(mark.letter)}</span>
                  ${esc(company.name)}
                  ${company.curated_roles.length ? '<span class="chip solid tiny" style="margin-left:auto">curated</span>' : ''}
                </div>
                <div class="desc">${esc(company.tagline)}</div>
              </button>`;
            })
            .join('')}
        </div>
      </section>

      <section>
        <h2 style="margin-bottom:14px">Target role</h2>
        <div class="pick-grid" id="role-grid">
          ${catalog.roles
            .map((role) => {
              const selected = target.role === role.id;
              return `
              <button class="pick ${selected ? 'selected' : ''}" data-role="${esc(role.id)}">
                <div class="name">${esc(role.title)}</div>
                <div class="desc">${esc(role.core_skills.slice(0, 4).join(' · '))}</div>
              </button>`;
            })
            .join('')}
        </div>
      </section>

      <section>
        <h2 style="margin-bottom:14px">Experience level</h2>
        <div class="level-row" id="level-row">
          ${catalog.levels
            .map((level) => {
              const selected = target.level === level.id;
              return `
              <button class="pick ${selected ? 'selected' : ''}" data-level="${esc(level.id)}">
                <div class="name">${esc(level.title)}</div>
                <div class="desc">Experience weighted ${(level.weights.experience * 100).toFixed(0)}% ·
                  projects ${(level.weights.projects * 100).toFixed(0)}%</div>
              </button>`;
            })
            .join('')}
        </div>
      </section>

      <section id="requirement-preview"></section>

      <section>
        <div class="card">
          <div class="card-head">
            <div class="title"><h3>Have the actual job posting?</h3>
              <span class="sub">Paste any tech job description and we'll tell you if your resume fits and what's missing.</span></div>
          </div>
          <textarea class="textarea" id="jd-area" placeholder="Paste the full job description, including the qualifications and responsibilities sections…">${esc(jobDescription || '')}</textarea>
          <div id="jd-error" class="jd-error" hidden></div>
          <div class="row wrap" style="margin-top:12px">
            <label class="row small muted" style="gap:7px;cursor:pointer">
              <input type="checkbox" id="jd-fuse" checked /> Fuse with the selected company profile
            </label>
            <span class="spacer"></span>
            <button class="btn" id="jd-btn">Analyse against this posting</button>
          </div>
        </div>
      </section>

      <div class="summary-bar">
        <div class="col" style="gap:2px">
          <span class="tiny faint">SELECTED TARGET</span>
          <strong id="target-label">${targetLabel(catalog, target)}</strong>
        </div>
        <span class="spacer"></span>
        <button class="btn primary" id="run-btn" ${resume && target.company && target.role ? '' : 'disabled'}>
          Run analysis →
        </button>
      </div>
    </div>`;
  },

  mount(root, ctx) {
    // The catalog may still be loading, in which case render() returned a
    // skeleton and none of these controls exist yet. The router re-renders
    // this page once the catalog arrives.
    if (!root.querySelector('#run-btn')) return;

    on(root, '[data-company]', (_e, node) => {
      setTarget({ company: node.dataset.company });
      syncSelection(root, 'company-grid', 'company', node.dataset.company);
      refresh(root, ctx);
    });
    on(root, '[data-role]', (_e, node) => {
      setTarget({ role: node.dataset.role });
      syncSelection(root, 'role-grid', 'role', node.dataset.role);
      refresh(root, ctx);
    });
    on(root, '[data-level]', (_e, node) => {
      setTarget({ level: node.dataset.level });
      syncSelection(root, 'level-row', 'level', node.dataset.level);
      refresh(root, ctx);
    });
    on(root, '[data-route]', (_e, node) => ctx.navigate(node.dataset.route));

    root.querySelector('#run-btn').addEventListener('click', () => ctx.runAnalysis());

    const jdButton = root.querySelector('#jd-btn');
    const jdError = root.querySelector('#jd-error');

    const showJdError = (message) => {
      jdError.innerHTML = `<span aria-hidden="true">⚠</span><span>${esc(message)}</span>`;
      jdError.hidden = false;
    };
    const clearJdError = () => {
      jdError.hidden = true;
      jdError.textContent = '';
    };

    root.querySelector('#jd-area').addEventListener('input', clearJdError);

    jdButton.addEventListener('click', async () => {
      const text = root.querySelector('#jd-area').value.trim();
      clearJdError();
      if (text.split(/\s+/).filter(Boolean).length < 30) {
        toast('Paste the full job description — at least 30 words.', 'error');
        showJdError('Paste the full posting — at least 30 words, including the requirements section.');
        return;
      }

      const fuse = root.querySelector('#jd-fuse').checked;
      setState({ jobDescription: text });

      jdButton.disabled = true;
      jdButton.textContent = 'Analysing…';
      try {
        const result = await ctx.runJobDescriptionAnalysis(text, fuse);
        // A refused posting keeps the user here with their text intact; the
        // analysis path navigates itself on success.
        if (!result?.ok) {
          showJdError(result?.error?.message || 'That posting could not be analysed.');
        }
      } finally {
        jdButton.disabled = false;
        jdButton.textContent = 'Analyse against this posting';
      }
    });

    refresh(root, ctx);

    function syncSelection(scope, gridId, key, value) {
      scope
        .querySelectorAll(`#${gridId} .pick`)
        .forEach((node) => node.classList.toggle('selected', node.dataset[key] === value));
    }
  },
};

function targetLabel(catalog, target) {
  const company = catalog.companies.find((c) => c.id === target.company);
  const role = catalog.roles.find((r) => r.id === target.role);
  const level = catalog.levels.find((l) => l.id === target.level);
  if (!company && !role) return 'Nothing selected yet';
  return `${company ? company.name : '—'} · ${role ? role.title : '—'} · ${level ? level.title : ''}`;
}

async function refresh(root, ctx) {
  const { catalog, target, resume } = getState();
  const label = root.querySelector('#target-label');
  if (label) label.textContent = targetLabel(catalog, target);
  const button = root.querySelector('#run-btn');
  if (button) button.disabled = !(resume && target.company && target.role);
  ctx.refreshShell();

  const host = root.querySelector('#requirement-preview');
  if (!host || !target.company || !target.role) return;

  host.innerHTML = `<div class="skeleton" style="height:190px"></div>`;
  try {
    const requirement = await api.requirements(target.company, target.role, target.level);
    host.innerHTML = requirementCard(requirement);
  } catch (error) {
    host.innerHTML = `<div class="card"><span class="chip bad">${esc(error.message)}</span></div>`;
  }
}

function requirementCard(requirement) {
  const skillChips = (list, tone) =>
    list
      .slice(0, 14)
      .map(
        (skill) =>
          `<span class="chip ${tone}" title="importance ${skill.importance}">${esc(skill.skill)}
             <span class="tiny faint">${(skill.importance * 100).toFixed(0)}</span></span>`
      )
      .join('');

  return `
  <div class="card fade-up">
    <div class="card-head">
      <div class="title">
        <h3>${esc(requirement.company.name)} · ${esc(requirement.role.title)}</h3>
        <span class="sub">${esc(requirement.level.title)} — what this specific target screens for</span>
      </div>
      <div class="actions">
        <span class="chip ${requirement.curated ? 'solid' : 'mute'}">
          ${requirement.curated ? 'curated profile' : 'composed profile'}
        </span>
      </div>
    </div>

    <div class="grid cols-2" style="gap:18px">
      <div class="col" style="gap:14px">
        <div>
          <div class="tiny faint" style="margin-bottom:7px">REQUIRED (${requirement.required_skills.length})</div>
          <div class="chip-row">${skillChips(requirement.required_skills, 'bad')}</div>
        </div>
        <div>
          <div class="tiny faint" style="margin-bottom:7px">PREFERRED (${requirement.preferred_skills.length})</div>
          <div class="chip-row">${skillChips(requirement.preferred_skills, 'warn')}</div>
        </div>
        ${
          requirement.optional_skills.length
            ? `<div><div class="tiny faint" style="margin-bottom:7px">OPTIONAL</div>
                 <div class="chip-row">${skillChips(requirement.optional_skills, 'mute')}</div></div>`
            : ''
        }
      </div>
      <div class="col" style="gap:14px">
        <div>
          <div class="tiny faint" style="margin-bottom:7px">KEYWORDS THEY USE</div>
          <div class="chip-row">${requirement.keywords
            .slice(0, 14)
            .map((keyword) => `<span class="chip mute">${esc(keyword)}</span>`)
            .join('')}</div>
        </div>
        ${
          requirement.screen_notes
            ? `<div><div class="tiny faint" style="margin-bottom:7px">HOW THEY SCREEN</div>
                 <p class="small muted">${esc(requirement.screen_notes)}</p></div>`
            : ''
        }
        ${
          requirement.hiring_signals?.length
            ? `<div><div class="tiny faint" style="margin-bottom:7px">WHAT MOVES THE NEEDLE</div>
                 <ul class="small muted" style="margin:0;padding-left:17px">
                   ${requirement.hiring_signals.map((signal) => `<li>${esc(signal)}</li>`).join('')}
                 </ul></div>`
            : ''
        }
      </div>
    </div>
  </div>`;
}
