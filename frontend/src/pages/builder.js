/**
 * Resume builder — generate a corrected resume for the analysed target.
 *
 * The page's job is consent. The backend will happily add every missing skill
 * to the document, so the UI makes that an explicit, clearly-labelled choice
 * and defaults to the honest path: nothing is claimed unless the user ticks it.
 */

import {
  copyText,
  downloadBlob,
  emptyState,
  esc,
  escWithPlaceholders,
  on,
  plural,
  toast,
} from '../components/ui.js';
import { getState } from '../services/state.js';

const CONTACT_FIELDS = [
  { key: 'name', label: 'Full name', placeholder: 'Ananya Sharma' },
  { key: 'email', label: 'Email', placeholder: 'you@example.com' },
  { key: 'phone', label: 'Phone', placeholder: '+91 98765 43210' },
  { key: 'location', label: 'Location', placeholder: 'Bengaluru, India' },
  { key: 'linkedin', label: 'LinkedIn', placeholder: 'linkedin.com/in/you' },
  { key: 'github', label: 'GitHub', placeholder: 'github.com/you' },
  { key: 'portfolio', label: 'Portfolio', placeholder: 'yoursite.dev (optional)' },
];

export const builderPage = {
  title: 'Resume builder',
  subtitle: 'Generate a corrected resume from your real experience',

  render() {
    const { analysis } = getState();
    if (!analysis) {
      return `<div class="page">${emptyState(
        'No analysis yet',
        'Run an analysis first — the builder rewrites your resume against a specific target.',
        'Start here',
        'upload'
      )}</div>`;
    }

    if (!analysis.analysis_id) {
      return `<div class="page">${emptyState(
        'This analysis was not saved',
        'The builder works from a stored analysis. Run the analysis again with saving enabled.',
        'Back to target selection',
        'target'
      )}</div>`;
    }

    const contact = analysis.resume_overview.contact || {};
    const target = analysis.target;
    const candidates = gapCandidates(analysis.skill_gap);

    return `
    <div class="page fade-up">
      <div class="card">
        <div class="row between wrap">
          <div>
            <h2>Rebuild for ${esc(target.company.name)} · ${esc(target.role.title)}</h2>
            <p class="small muted">
              Every bullet is rewritten from what your resume already says. Nothing is invented —
              where a number belongs you get a blank to fill in yourself.
            </p>
          </div>
          <span class="chip solid">${esc(target.level.title)}</span>
        </div>
      </div>

      <!-- ------------------------------------------------- 1. details -- -->
      <div class="card">
        <div class="card-head"><div class="title"><h3>1. Contact details</h3>
          <span class="sub">Prefilled from your resume — fill in anything it could not find</span></div></div>
        <div class="grid cols-2 detail-grid">
          ${CONTACT_FIELDS.map(
            (f) => `
            <div class="field">
              <label for="detail-${esc(f.key)}">${esc(f.label)}
                ${contact[f.key] ? '' : '<span class="missing-flag">missing</span>'}</label>
              <input class="input" id="detail-${esc(f.key)}" data-detail="${esc(f.key)}"
                     value="${esc(contact[f.key] || '')}"
                     placeholder="${esc(f.placeholder)}" autocomplete="off" spellcheck="false" />
            </div>`
          ).join('')}
        </div>
      </div>

      <!-- -------------------------------------------------- 2. skills -- -->
      <div class="card">
        <div class="card-head">
          <div class="title"><h3>2. Missing skills</h3>
            <span class="sub">
              ${plural(candidates.length, 'skill')} this target wants that your resume does not evidence
            </span></div>
        </div>

        ${
          candidates.length
            ? `<div class="skill-picker">
                 ${candidates.map((item) => skillRow(item)).join('')}
               </div>
               <p class="tiny faint" style="margin-top:12px">
                 Tick <strong>I have this</strong> only for skills you could be questioned on in an
                 interview. <strong>Learning</strong> goes on a separate line and is never presented
                 as something you already have.
               </p>`
            : '<p class="small muted">No gaps to add — your resume already evidences every skill this target asks for.</p>'
        }
      </div>

      <!-- ------------------------------------------------ 3. projects -- -->
      <div class="card">
        <div class="card-head">
          <div class="title"><h3>3. Projects that would close your gaps</h3>
            <span class="sub">Tick one only if you have genuinely built it</span></div>
        </div>
        <div id="project-picker">
          <p class="small muted">Loading suggestions…</p>
        </div>
      </div>

      <!-- ---------------------------------------------------- 4. mode -- -->
      <div class="card">
        <div class="card-head"><div class="title"><h3>4. How should missing skills be handled?</h3>
          <span class="sub">This is the one decision that can put an unproven claim on your resume</span></div></div>

        <div class="mode-options">
          <label class="mode-option selected" data-mode-option="confirmed">
            <input type="radio" name="build-mode" value="confirmed" checked />
            <div>
              <strong>Only skills I confirm</strong>
              <span class="chip ok tiny">recommended</span>
              <p class="small muted">Adds nothing you have not ticked above.</p>
            </div>
          </label>

          <label class="mode-option" data-mode-option="auto_add">
            <input type="radio" name="build-mode" value="auto_add" />
            <div>
              <strong>Add all missing skills automatically</strong>
              <p class="small muted">Adds every missing required and preferred skill without asking.</p>
            </div>
          </label>
        </div>

        <div class="auto-warning" id="auto-warning" hidden>
          <span aria-hidden="true">⚠</span>
          <div>
            <strong>This puts skills on your resume that it does not evidence.</strong>
            Every added skill is listed in the result so you can remove any you could not defend in
            an interview. You are responsible for what stays on the page.
          </div>
        </div>
      </div>

      <div class="row wrap" style="gap:12px">
        <button class="btn primary" id="build-btn">Generate new resume</button>
        <button class="btn ghost" data-route="gaps">Review the gaps first</button>
      </div>

      <div id="build-result"></div>
    </div>`;
  },

  mount(root, ctx) {
    on(root, '[data-route]', (_e, node) => ctx.navigate(node.dataset.route));

    const warning = root.querySelector('#auto-warning');
    const picker = root.querySelector('.skill-picker');

    // Mode switch: auto mode makes the per-skill ticks irrelevant, so they are
    // visibly disabled rather than silently ignored.
    root.querySelectorAll('[data-mode-option]').forEach((option) => {
      option.addEventListener('change', () => {
        const mode = option.dataset.modeOption;
        root.querySelectorAll('[data-mode-option]').forEach((o) =>
          o.classList.toggle('selected', o === option)
        );
        if (warning) warning.hidden = mode !== 'auto_add';
        if (picker) picker.classList.toggle('dimmed', mode === 'auto_add');
        picker?.querySelectorAll('input[type="checkbox"]').forEach((box) => {
          box.disabled = mode === 'auto_add';
        });
      });
    });

    // "I have this" and "Currently learning" are mutually exclusive - the API
    // rejects both, so the UI never lets it happen.
    on(
      root,
      'input[data-skill-have], input[data-skill-learning]',
      (_e, node) => {
        if (!node.checked) return;
        const row = node.closest('.skill-pick');
        const other = node.dataset.skillHave
          ? row.querySelector('input[data-skill-learning]')
          : row.querySelector('input[data-skill-have]');
        if (other) other.checked = false;
        row.classList.toggle('claimed', node.dataset.skillHave !== undefined);
        row.classList.toggle('learning', node.dataset.skillLearning !== undefined);
      },
      'change'
    );

    // The recommendations come from the same engine the Projects page uses, so
    // a dry run of the builder is the cheapest way to get them for this target.
    const projectPicker = root.querySelector('#project-picker');
    const { analysis: current } = getState();
    if (projectPicker && current?.analysis_id) {
      ctx.api
        .buildResume({ analysis_id: current.analysis_id })
        .then((preview) => {
          const items = preview.recommended_projects || [];
          projectPicker.innerHTML = items.length
            ? items.map((p) => projectRow(p)).join('') +
              `<p class="tiny faint" style="margin-top:12px">
                 A ticked project is added as a <strong>template with blanks</strong>, not a
                 finished claim. The download stays blocked until you fill them in.
               </p>`
            : '<p class="small muted">No project gaps to close for this target.</p>';
        })
        .catch(() => {
          projectPicker.innerHTML =
            '<p class="small muted">Could not load project suggestions.</p>';
        });
    }

    // Built and in-progress are mutually exclusive, same as the skill ticks.
    on(
      root,
      'input[data-project-built], input[data-project-progress]',
      (_e, node) => {
        if (!node.checked) return;
        const row = node.closest('.project-pick');
        const other = node.dataset.projectBuilt
          ? row.querySelector('input[data-project-progress]')
          : row.querySelector('input[data-project-built]');
        if (other) other.checked = false;
        row.classList.toggle('claimed', node.dataset.projectBuilt !== undefined);
        row.classList.toggle('learning', node.dataset.projectProgress !== undefined);
      },
      'change'
    );

    const button = root.querySelector('#build-btn');
    if (!button) return;

    button.addEventListener('click', async () => {
      const { analysis } = getState();
      const mode =
        root.querySelector('input[name="build-mode"]:checked')?.value || 'confirmed';

      const details = {};
      root.querySelectorAll('[data-detail]').forEach((input) => {
        details[input.dataset.detail] = input.value.trim();
      });

      const confirmed = [...root.querySelectorAll('input[data-skill-have]:checked')].map(
        (n) => n.dataset.skillHave
      );
      const learning = [...root.querySelectorAll('input[data-skill-learning]:checked')].map(
        (n) => n.dataset.skillLearning
      );

      const host = root.querySelector('#build-result');
      button.disabled = true;
      button.textContent = 'Generating…';
      host.innerHTML = `
        <div class="card pad-lg">
          <div class="row" style="gap:12px"><div class="spinner"></div>
            <strong>Rewriting and re-scoring…</strong></div>
          <p class="small muted" style="margin-top:8px">
            The generated resume is parsed and scored again from scratch, so the after-score is
            measured rather than estimated.
          </p>
        </div>`;

      try {
        const result = await ctx.api.buildResume({
          analysis_id: analysis.analysis_id,
          mode,
          confirmed_skills: mode === 'auto_add' ? [] : confirmed,
          learning_skills: mode === 'auto_add' ? [] : learning,
          details,
          projects_built: [...root.querySelectorAll('input[data-project-built]:checked')].map(
            (n) => n.dataset.projectBuilt
          ),
          projects_in_progress: [
            ...root.querySelectorAll('input[data-project-progress]:checked'),
          ].map((n) => n.dataset.projectProgress),
        });
        host.innerHTML = resultCard(result);
        wireResult(ctx, host, result);
        host.scrollIntoView({ behavior: 'smooth', block: 'start' });
        toast(
          `Resume rebuilt — ${result.score.before.toFixed(0)} → ${result.score.after.toFixed(0)}/100.`,
          'success'
        );
      } catch (error) {
        host.innerHTML = `<div class="card"><span class="chip bad">${esc(error.message)}</span></div>`;
        toast(error.message, 'error', 8000);
      } finally {
        button.disabled = false;
        button.textContent = 'Generate new resume';
      }
    });
  },
};

// ---------------------------------------------------------------- helpers --

function gapCandidates(gap) {
  const rows = [
    ...(gap.missing_high_priority || []).map((m) => ({ ...m, bucket: 'high' })),
    ...(gap.missing_medium_priority || []).map((m) => ({ ...m, bucket: 'medium' })),
    // Adjacent partials: the resume hints at these through a related skill, so
    // they are the likeliest to be genuinely held but badly stated.
    ...(gap.partially_matched || []).filter((m) => m.via).map((m) => ({ ...m, bucket: 'adjacent' })),
  ];
  const seen = new Set();
  return rows.filter((row) => {
    const key = row.skill.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function projectRow(project) {
  return `
  <div class="project-pick">
    <div class="info">
      <div class="nm">${esc(project.title)}
        <span class="chip mute tiny">${esc(project.difficulty)}</span>
        <span class="chip mute tiny">${esc(project.estimated_duration)}</span></div>
      <div class="why">${esc(project.description)}</div>
      <div class="chip-row" style="margin-top:6px">
        ${project.skills_closed.map((s) => `<span class="chip bad tiny">${esc(s)}</span>`).join('')}
      </div>
    </div>
    <div class="picks">
      <label class="tickbox">
        <input type="checkbox" data-project-built="${esc(project.id)}" />
        <span>I built this</span>
      </label>
      <label class="tickbox">
        <input type="checkbox" data-project-progress="${esc(project.id)}" />
        <span>Building it</span>
      </label>
    </div>
  </div>`;
}

function skillRow(item) {
  const tone = { high: 'bad', medium: 'warn', adjacent: 'mute' }[item.bucket] || 'mute';
  const label = { high: 'high priority', medium: 'medium priority', adjacent: 'adjacent' }[
    item.bucket
  ];
  return `
  <div class="skill-pick">
    <div class="info">
      <div class="nm">${esc(item.skill)}
        <span class="chip ${esc(tone)} tiny">${esc(label)}</span></div>
      <div class="why">${esc(item.reason || '')}</div>
    </div>
    <div class="picks">
      <label class="tickbox">
        <input type="checkbox" data-skill-have="${esc(item.skill)}" />
        <span>I have this</span>
      </label>
      <label class="tickbox">
        <input type="checkbox" data-skill-learning="${esc(item.skill)}" />
        <span>Learning</span>
      </label>
    </div>
  </div>`;
}

function resultCard(result) {
  const before = result.score.before;
  const after = result.score.after;
  const delta = after - before;
  const added = result.skills_added;

  return `
  <div class="card pad-lg fade-up">
    <div class="card-head">
      <div class="title"><h3>Your rebuilt resume</h3>
        <span class="sub">Re-parsed and re-scored against the same target</span></div>
      <div class="actions">
        <span class="chip ${delta >= 0 ? 'ok' : 'warn'}">
          ${before.toFixed(0)} → ${after.toFixed(0)}/100 ${delta >= 0 ? '▲' : '▼'} ${Math.abs(delta).toFixed(1)}
        </span>
      </div>
    </div>

    <div class="build-summary">
      <div class="stat">
        <span class="k">Verdict</span>
        <span class="v">${esc(result.score.fit_before)} → <strong>${esc(result.score.fit_after)}</strong></span>
      </div>
      <div class="stat">
        <span class="k">Blanks to fill</span>
        <span class="v">${result.placeholder_count}</span>
      </div>
      <div class="stat">
        <span class="k">Skills added</span>
        <span class="v">${added.confirmed.length + added.auto_added.length}</span>
      </div>
      <div class="stat">
        <span class="k">Marked learning</span>
        <span class="v">${added.learning.length}</span>
      </div>
      <div class="stat">
        <span class="k">Projects added</span>
        <span class="v">${(result.projects_added?.built || []).length}${
          (result.projects_added?.in_progress || []).length
            ? ` + ${result.projects_added.in_progress.length} in progress`
            : ''
        }</span>
      </div>
    </div>

    ${
      result.auto_added_skills.length
        ? `<div class="auto-warning" style="margin-top:14px">
             <span aria-hidden="true">⚠</span>
             <div><strong>${esc(result.auto_add_warning)}</strong>
               <div class="chip-row" style="margin-top:8px">
                 ${result.auto_added_skills.map((s) => `<span class="chip warn">${esc(s)}</span>`).join('')}
               </div>
             </div>
           </div>`
        : ''
    }

    ${
      result.unfilled_blanks
        ? `<div class="auto-warning" style="margin-top:14px">
             <span aria-hidden="true">✎</span>
             <div><strong>${result.unfilled_blanks} blank(s) need your own details before you can download.</strong>
               ${result.added_project_warning ? esc(result.added_project_warning) : ''}
               Fill in every <span class="mono">&lt; … &gt;</span> in the text below — the export
               will not remove them for you, because that would turn a scaffold into a claim.
             </div>
           </div>`
        : ''
    }

    ${
      result.missing_details.length
        ? `<div class="missing-details">
             <div class="tiny faint">STILL MISSING FROM YOUR HEADER</div>
             <div class="chip-row">
               ${result.missing_details
                 .map(
                   (d) =>
                     `<span class="chip ${d.essential ? 'bad' : 'mute'}">${esc(d.label)}</span>`
                 )
                 .join('')}
             </div>
           </div>`
        : ''
    }

    ${
      (result.recommended_projects || []).length
        ? `<div class="rec-projects">
             <div class="tiny faint" style="margin-bottom:8px">PROJECTS THAT WOULD CLOSE YOUR GAPS</div>
             <p class="small muted" style="margin-bottom:12px">${esc(result.projects_note)}</p>
             ${result.recommended_projects
               .map(
                 (p) => `
               <div class="rec-project">
                 <div class="head">
                   <strong class="small">${esc(p.title)}</strong>
                   <span class="chip mute tiny">${esc(p.difficulty)}</span>
                   <span class="chip mute tiny">${esc(p.estimated_duration)}</span>
                 </div>
                 <div class="tiny faint">${esc(p.description)}</div>
                 <div class="chip-row" style="margin-top:7px">
                   ${p.skills_closed.map((sk) => `<span class="chip bad tiny">${esc(sk)}</span>`).join('')}
                 </div>
                 <div class="row between wrap" style="margin-top:9px;gap:8px">
                   <span class="tiny faint">Bullet to use <em>after</em> you finish it</span>
                   <button class="btn sm ghost" data-copy-template="${encodeURIComponent(
                     p.resume_bullet_template
                   )}">Copy bullet</button>
                 </div>
                 <div class="template">${escWithPlaceholders(p.resume_bullet_template)}</div>
               </div>`
               )
               .join('')}
           </div>`
        : ''
    }

    <div class="changes">
      <div class="tiny faint" style="margin-bottom:8px">WHAT CHANGED</div>
      ${result.changes
        .map(
          (c) => `
        <div class="change-row">
          <span class="chip mute tiny">${esc(c.section)}</span>
          <div>
            <strong class="small">${esc(c.action)}</strong>
            <div class="tiny faint">${esc(c.detail)}</div>
          </div>
        </div>`
        )
        .join('')}
    </div>

    <div class="row between wrap" style="margin-top:18px;margin-bottom:8px">
      <strong class="small">Edit before you download</strong>
      <span class="tiny faint">${result.placeholder_count} blank(s) marked [ ] and &lt; &gt;</span>
    </div>
    <textarea class="textarea mono" id="build-text" rows="22" spellcheck="false">${esc(result.text)}</textarea>
    <p class="tiny faint" style="margin-top:8px">${esc(result.verification_note)}</p>

    <div class="row wrap" style="gap:10px;margin-top:14px">
      <button class="btn primary" data-export="docx">Download DOCX</button>
      <button class="btn" data-export="pdf">Download PDF</button>
      <button class="btn ghost" data-export="txt">Download TXT</button>
      <button class="btn ghost" id="copy-text">Copy</button>
      <span class="spacer"></span>
      <label class="row small muted" style="gap:7px;cursor:pointer">
        <input type="checkbox" id="keep-placeholders" /> Keep the blanks in the file
      </label>
    </div>
  </div>`;
}

function wireResult(ctx, host, result) {
  const textarea = host.querySelector('#build-text');

  host.querySelector('#copy-text')?.addEventListener('click', () => {
    copyText(textarea.value, 'Resume copied — paste it wherever you need it');
  });

  on(host, '[data-copy-template]', (_e, node) =>
    copyText(
      decodeURIComponent(node.dataset.copyTemplate),
      'Template copied — add it only once the project is finished'
    )
  );

  on(host, '[data-export]', async (_e, node) => {
    const format = node.dataset.export;
    const keep = host.querySelector('#keep-placeholders')?.checked;
    const original = node.textContent;
    node.disabled = true;
    node.textContent = 'Preparing…';
    try {
      // Always the edited text, never the generated original.
      const { blob, fileName } = await ctx.api.exportResume({
        text: textarea.value,
        format,
        strip_placeholders: !keep,
        file_name: fileNameFor(result),
      });
      downloadBlob(blob, fileName || `${fileNameFor(result)}.${format}`);
      toast(`${format.toUpperCase()} downloaded.`, 'success', 2600);
    } catch (error) {
      toast(error.message, 'error', 8000);
    } finally {
      node.disabled = false;
      node.textContent = original;
    }
  });
}

function fileNameFor(result) {
  const name = result.resume?.contact?.name || 'resume';
  return `${name} resume`.trim();
}
