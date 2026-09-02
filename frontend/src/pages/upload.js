/** Resume upload page — drag & drop, validation, parse preview. */

import { api } from '../services/api.js';
import { getState, setState } from '../services/state.js';
import { esc, on, plural, toast } from '../components/ui.js';

const MAX_MB = 10;
const ALLOWED = ['.pdf', '.docx', '.txt'];

export const uploadPage = {
  title: 'Upload resume',
  subtitle: 'PDF, DOCX or TXT — parsed locally by the analysis engine',

  render() {
    const { resume } = getState();
    return `
    <div class="page fade-up">
      <div class="grid split">
        <div class="col" style="gap:18px">
          <div class="card pad-lg">
            <div class="card-head">
              <div class="title"><h3>Upload your resume</h3>
                <span class="sub">Nothing is sent anywhere except your own local backend</span></div>
            </div>
            <div class="dropzone" id="dropzone" tabindex="0" role="button"
                 aria-label="Upload a resume file. PDF, DOCX or TXT, up to ${MAX_MB} megabytes.">
              <div class="icon">⬆</div>
              <h3>Drop your resume here</h3>
              <p class="small muted">or click to browse your files</p>
              <div class="formats">PDF · DOCX · TXT &nbsp;•&nbsp; up to ${MAX_MB} MB</div>
            </div>
            <input type="file" id="file-input" accept=".pdf,.docx,.txt" hidden />
            <div id="upload-status" style="margin-top:16px"></div>
          </div>

          <div class="card">
            <div class="card-head">
              <div class="title"><h3>Or paste the text</h3>
                <span class="sub">Useful when your resume lives in a web editor</span></div>
            </div>
            <textarea class="textarea" id="paste-area" placeholder="Paste your full resume text here (minimum 40 words)…"></textarea>
            <div class="row" style="margin-top:12px">
              <button class="btn" id="paste-btn">Parse pasted text</button>
              <span class="tiny faint" id="paste-count">0 words</span>
            </div>
          </div>
        </div>

        <div class="col" style="gap:18px">
          <div class="card">
            <div class="card-head"><div class="title"><h3>What gets extracted</h3>
              <span class="sub">Structured JSON, not a keyword blob</span></div></div>
            <div class="chip-row">
              ${[
                'Name', 'Email', 'Phone', 'LinkedIn', 'GitHub', 'Education', 'Skills',
                'Programming languages', 'Frameworks', 'Libraries', 'Tools', 'Cloud platforms',
                'Work experience', 'Projects', 'Certifications', 'Achievements',
              ].map((item) => `<span class="chip mute">${esc(item)}</span>`).join('')}
            </div>
          </div>

          <div class="card">
            <div class="card-head"><div class="title"><h3>For the most accurate parse</h3></div></div>
            <ul class="col small muted" style="gap:9px;padding-left:18px;margin:0">
              <li>Export a text-based PDF, not a scan or screenshot</li>
              <li>Use a single-column layout — columns and tables confuse ATS parsers</li>
              <li>Keep standard headings: Skills, Experience, Projects, Education</li>
              <li>Write dates as <span class="mono">Jun 2024 - Dec 2024</span></li>
              <li>Avoid graphical skill bars — the text inside images cannot be read</li>
            </ul>
          </div>

          <div id="parsed-card">${resume ? parsedCard(resume) : ''}</div>
        </div>
      </div>
    </div>`;
  },

  mount(root, ctx) {
    const dropzone = root.querySelector('#dropzone');
    const input = root.querySelector('#file-input');
    const status = root.querySelector('#upload-status');
    const parsedCardHost = root.querySelector('#parsed-card');
    const pasteArea = root.querySelector('#paste-area');
    const pasteCount = root.querySelector('#paste-count');

    const openPicker = () => input.click();
    dropzone.addEventListener('click', openPicker);
    dropzone.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        openPicker();
      }
    });

    ['dragenter', 'dragover'].forEach((evt) =>
      dropzone.addEventListener(evt, (ev) => {
        ev.preventDefault();
        dropzone.classList.add('dragging');
      })
    );
    ['dragleave', 'drop'].forEach((evt) =>
      dropzone.addEventListener(evt, (ev) => {
        ev.preventDefault();
        dropzone.classList.remove('dragging');
      })
    );
    dropzone.addEventListener('drop', (ev) => {
      const file = ev.dataTransfer?.files?.[0];
      if (file) handleFile(file);
    });
    input.addEventListener('change', () => {
      if (input.files?.[0]) handleFile(input.files[0]);
      input.value = '';
    });

    pasteArea.addEventListener('input', () => {
      const words = pasteArea.value.trim().split(/\s+/).filter(Boolean).length;
      pasteCount.textContent = plural(words, 'word');
      pasteCount.style.color = words >= 40 ? 'var(--success)' : 'var(--text-faint)';
    });

    root.querySelector('#paste-btn').addEventListener('click', async () => {
      const text = pasteArea.value.trim();
      if (text.split(/\s+/).filter(Boolean).length < 40) {
        toast('Paste at least 40 words so the parser has something to work with.', 'error');
        return;
      }
      await run(() => api.parseText(text), 'Parsing pasted resume…');
    });

    on(parsedCardHost, '[data-route]', (_ev, node) => ctx.navigate(node.dataset.route));

    function validate(file) {
      const name = file.name.toLowerCase();
      if (!ALLOWED.some((ext) => name.endsWith(ext))) {
        return `Unsupported file type. Upload ${ALLOWED.join(', ')}.`;
      }
      if (file.size > MAX_MB * 1024 * 1024) {
        return `That file is ${(file.size / 1048576).toFixed(1)} MB. The limit is ${MAX_MB} MB.`;
      }
      if (file.size === 0) return 'That file is empty.';
      return null;
    }

    async function handleFile(file) {
      const problem = validate(file);
      if (problem) {
        toast(problem, 'error');
        status.innerHTML = `<div class="chip bad">${esc(problem)}</div>`;
        return;
      }
      await run(() => api.uploadResume(file), `Parsing ${file.name}…`);
    }

    async function run(work, message) {
      dropzone.classList.add('busy');
      status.innerHTML = `<div class="row"><div class="spinner"></div><span class="small muted">${esc(message)}</span></div>`;
      try {
        const result = await work();
        setState({ resume: result, analysis: null, status: 'idle' });
        status.innerHTML = `
          <div class="file-pill">
            <span style="font-size:18px">✓</span>
            <div>
              <div class="name">${esc(result.file_name)}</div>
              <div class="tiny muted">${result.metadata.words} words · ${plural(result.skills_detected.length, 'skill')} detected
                · ${plural(result.sections_detected.length, 'section')}</div>
            </div>
          </div>`;
        parsedCardHost.innerHTML = parsedCard(result);
        (result.warnings || []).forEach((warning) => toast(warning, 'info', 7000));
        toast('Resume parsed. Choose your target next.', 'success');
        ctx.refreshShell();
      } catch (error) {
        status.innerHTML = `<div class="chip bad">${esc(error.message)}</div>`;
        toast(error.message, 'error', 7000);
      } finally {
        dropzone.classList.remove('busy');
      }
    }
  },
};

function parsedCard(resume) {
  const contact = resume.contact || {};
  const profile = resume.skill_profile || {};
  const categories = profile.by_category || {};
  return `
  <div class="card fade-up">
    <div class="card-head">
      <div class="title"><h3>Parsed profile</h3><span class="sub">Check this looks right before analysing</span></div>
      <div class="actions"><span class="chip ok">Ready</span></div>
    </div>
    <div class="parsed-preview">
      ${field('Name', contact.name)}
      ${field('Email', contact.email)}
      ${field('Phone', contact.phone)}
      ${field('LinkedIn', contact.linkedin)}
      ${field('GitHub', contact.github)}
      ${field('Location', contact.location)}
    </div>
    <hr class="divider"/>
    <div class="row between" style="margin-bottom:10px">
      <strong class="small">${plural(profile.total || 0, 'skill')} detected</strong>
      <span class="tiny faint">${profile.applied || 0} demonstrated in experience or projects</span>
    </div>
    <div class="chip-row">
      ${Object.entries(categories)
        .map(([name, count]) => `<span class="chip mute">${esc(name)} <strong style="color:var(--text)">${count}</strong></span>`)
        .join('') || '<span class="tiny faint">No skills matched the ontology.</span>'}
    </div>
    <hr class="divider"/>
    <div class="chip-row">
      ${(resume.sections_detected || [])
        .filter((s) => s !== 'header')
        .map((section) => `<span class="chip ok"><span class="dot"></span>${esc(section)}</span>`)
        .join('')}
    </div>
    <button class="btn primary block" style="margin-top:18px" data-route="target">Choose target company &amp; role →</button>
  </div>`;
}

function field(label, value) {
  return `<div class="item"><div class="k">${esc(label)}</div>
    <div class="v ${value ? '' : 'faint'}">${value ? esc(value) : 'not detected'}</div></div>`;
}
