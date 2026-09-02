/**
 * Career assistant panel.
 *
 * Grounded in the current analysis: the backend answers with the user's own
 * numbers. Refuses to help fabricate, and says so in plain language.
 */

import { api } from '../services/api.js';
import { getState } from '../services/state.js';
import { el, esc } from './ui.js';

const DEFAULT_STARTERS = [
  'Why is my compatibility score what it is?',
  'What skills should I learn first?',
  'Which project will improve my profile the most?',
  'How can I improve my resume without adding fake experience?',
];

export function initChat() {
  const fab = el('button', 'chat-fab', '✦');
  fab.setAttribute('aria-label', 'Open the career assistant');
  fab.title = 'Career assistant';
  document.body.appendChild(fab);

  let panel = null;
  const history = [];

  fab.addEventListener('click', () => {
    if (panel) {
      close();
      return;
    }
    open();
  });

  function close() {
    panel?.remove();
    panel = null;
    fab.style.display = 'grid';
  }

  function open() {
    fab.style.display = 'none';
    panel = el('section', 'chat-panel');
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Career assistant');
    panel.innerHTML = `
      <header>
        <div class="brand-mark" style="width:28px;height:28px;flex:0 0 28px;font-size:13px">✦</div>
        <div style="line-height:1.25">
          <strong style="font-size:0.9rem">Career assistant</strong>
          <div class="tiny faint" id="chat-context">grounded in your analysis</div>
        </div>
        <span class="spacer"></span>
        <button class="btn sm ghost" id="chat-close" aria-label="Close">✕</button>
      </header>
      <div class="chat-log" id="chat-log"></div>
      <div class="chat-suggestions" id="chat-suggestions"></div>
      <form class="chat-input" id="chat-form">
        <input class="input" id="chat-text" autocomplete="off" placeholder="Ask about your score, gaps or plan…" />
        <button class="btn primary" type="submit" aria-label="Send">→</button>
      </form>`;
    document.body.appendChild(panel);

    const log = panel.querySelector('#chat-log');
    const suggestionHost = panel.querySelector('#chat-suggestions');
    const contextLine = panel.querySelector('#chat-context');
    const { analysis } = getState();

    contextLine.textContent = analysis
      ? `${analysis.target.company.name} · ${analysis.target.role.title} · ${analysis.scoring.overall_score.toFixed(0)}/100`
      : 'no analysis loaded yet';

    if (!history.length) {
      history.push({
        role: 'bot',
        text: analysis
          ? `I can see your ${analysis.target.company.name} ${analysis.target.role.title} analysis — ` +
            `${analysis.scoring.overall_score.toFixed(0)}/100, ${analysis.scoring.band}. Ask me anything about it.`
          : 'Run an analysis first and I can answer using your actual numbers rather than generic advice.',
      });
    }
    renderLog();
    renderSuggestions(DEFAULT_STARTERS);

    panel.querySelector('#chat-close').addEventListener('click', close);
    panel.querySelector('#chat-form').addEventListener('submit', (ev) => {
      ev.preventDefault();
      const input = panel.querySelector('#chat-text');
      const question = input.value.trim();
      if (!question) return;
      input.value = '';
      ask(question);
    });

    suggestionHost.addEventListener('click', (ev) => {
      const button = ev.target.closest('button');
      if (button) ask(button.textContent);
    });

    function renderLog() {
      log.innerHTML = history
        .map((message) => `<div class="msg ${message.role}">${esc(message.text)}</div>`)
        .join('');
      log.scrollTop = log.scrollHeight;
    }

    function renderSuggestions(items) {
      suggestionHost.innerHTML = items.map((item) => `<button type="button">${esc(item)}</button>`).join('');
    }

    async function ask(question) {
      history.push({ role: 'user', text: question });
      renderLog();
      const thinking = el('div', 'msg bot', '<span class="spinner" style="display:inline-block"></span>');
      log.appendChild(thinking);
      log.scrollTop = log.scrollHeight;

      try {
        const state = getState();
        const response = await api.chat({
          question,
          analysis_id: state.analysis?.analysis_id ?? null,
          analysis: state.analysis?.analysis_id ? null : state.analysis,
        });
        history.push({ role: 'bot', text: response.answer });
        renderSuggestions(response.suggested_questions?.length ? response.suggested_questions : DEFAULT_STARTERS);
      } catch (error) {
        history.push({ role: 'bot', text: `Sorry — ${error.message}` });
      } finally {
        thinking.remove();
        renderLog();
      }
    }
  }

  return { open, close };
}
