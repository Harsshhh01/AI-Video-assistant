/* ==========================================================================
   AI Video Assistant — front-end controller
   Plain ES2020, no dependencies. Talks to the FastAPI backend under /api.
   ========================================================================== */
'use strict';

const $ = (sel) => document.querySelector(sel);

const POLL_MS = 1500;
const STORE_KEY = 'ava.jobId';

const el = {
  form: $('#analyse-form'),
  source: $('#source'),
  file: $('#file'),
  fileChosen: $('#file-chosen'),
  dropzone: $('#dropzone'),
  language: $('#language'),
  submit: $('#submit-btn'),
  tabs: document.querySelectorAll('.tab'),
  panes: { url: $('#pane-url'), file: $('#pane-file') },

  progress: $('#progress-card'),
  progressSource: $('#progress-source'),
  progressElapsed: $('#progress-elapsed'),
  progressError: $('#progress-error'),
  progressNote: $('#progress-note'),
  steps: $('#steps'),
  cancel: $('#cancel-btn'),

  results: $('#results'),
  title: $('#result-title'),
  sub: $('#result-sub'),
  summary: $('#out-summary'),
  actions: $('#out-actions'),
  decisions: $('#out-decisions'),
  questions: $('#out-questions'),
  transcript: $('#out-transcript'),
  transcriptWords: $('#transcript-words'),
  copyTranscript: $('#copy-transcript'),
  exportBtn: $('#export-btn'),
  reset: $('#reset-btn'),

  chatForm: $('#chat-form'),
  chatInput: $('#chat-input'),
  chatSend: $('#chat-send'),
  chatLog: $('#chat-log'),
  clearChat: $('#clear-chat'),

  statusPill: $('#status-pill'),
  statusLabel: $('#status-label'),
  statusLed: $('.status-led'),
  statusPanel: $('#status-panel'),
  maxMb: $('#max-mb'),
  version: $('#footer-version'),
  toast: $('#toast'),
};

let mode = 'url';
let jobId = null;
let pollTimer = null;
let toastTimer = null;

/* ── Helpers ─────────────────────────────────────────────────────────────── */

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}

/**
 * Minimal markdown -> HTML for model output. Everything is HTML-escaped first,
 * so nothing the model produces can inject markup.
 */
function renderMarkdown(src) {
  if (!src || !String(src).trim()) {
    return '<p class="muted">Nothing found for this section.</p>';
  }

  let text = String(src).trim();

  // Drop a leading "Here's the summary:"-style preamble. Note the curly
  // apostrophe — models emit ’ far more often than '. This runs before the
  // unwrap below, because the preamble is what pushes the fence off line one.
  text = text.replace(
    /^(?:sure[,!]?\s*)?here(?:['’]s|\s+is|\s+are)[^\n]{0,240}:[ \t]*\r?\n+/i,
    ''
  ).trim();

  // Models sometimes wrap their whole answer in ```markdown … ```. Unwrap it and
  // render the contents, rather than showing a monospace wall (or a stray ```).
  const wrapped = text.match(/^```([A-Za-z]*)[ \t]*\r?\n([\s\S]*?)\r?\n?```$/);
  if (wrapped && ['', 'markdown', 'md', 'text', 'txt'].includes(wrapped[1].toLowerCase())) {
    text = wrapped[2].trim();
  }

  const inline = (s) => escapeHtml(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/(^|[\s(])_([^_\n]+)_/g, '$1<em>$2</em>');

  const out = [];
  // Open lists, outermost first: {kind, indent, owesLi}. `owesLi` records that
  // this list was opened inside its parent's <li>, whose closing tag we removed
  // and must put back. The extractors emit owner/deadline as indented
  // sub-bullets, so nesting has to be real — flattening them restarts the
  // numbering of every top-level item.
  const stack = [];
  let para = [];

  const flushPara = () => {
    if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; }
  };

  const closeOne = () => {
    const level = stack.pop();
    out.push(`</${level.kind}>`);
    if (level.owesLi) out.push('</li>');
  };

  const closeAll = () => { while (stack.length) closeOne(); };

  const openList = (kind, indent) => {
    // Leaving a deeper level: close back out to this indent.
    while (stack.length && indent < stack[stack.length - 1].indent) closeOne();

    const top = stack[stack.length - 1];

    if (top && indent > top.indent) {
      // Nest inside the previous item by reopening its <li>.
      let owesLi = false;
      const last = out.length - 1;
      if (last >= 0 && out[last].endsWith('</li>')) {
        out[last] = out[last].slice(0, -'</li>'.length);
        owesLi = true;
      }
      out.push(`<${kind}>`);
      stack.push({ kind, indent, owesLi });
      return;
    }

    if (!top) {
      out.push(`<${kind}>`);
      stack.push({ kind, indent, owesLi: false });
      return;
    }

    // Same level: only reopen if the list type actually changed.
    if (top.kind !== kind) {
      closeOne();
      out.push(`<${kind}>`);
      stack.push({ kind, indent, owesLi: false });
    }
  };

  const indentOf = (raw) => raw.replace(/\t/g, '    ').match(/^ */)[0].length;

  let fence = null;  // collecting lines inside a ``` block

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trimEnd();

    // Any fence that survived the unwrap above becomes a real code block, so a
    // stray ``` never renders as literal text.
    if (line.trim().startsWith('```')) {
      if (fence === null) {
        flushPara(); closeAll();
        fence = [];
      } else {
        out.push(`<pre><code>${escapeHtml(fence.join('\n'))}</code></pre>`);
        fence = null;
      }
      continue;
    }
    if (fence !== null) { fence.push(rawLine); continue; }

    // A blank line ends a paragraph but not a list — models routinely put blank
    // lines between numbered items.
    if (!line.trim()) { flushPara(); continue; }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      flushPara(); closeAll();
      const level = Math.min(heading[1].length + 2, 4);
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }

    const ordered = line.match(/^(\s*)(\d+)[.)]\s+(.*)$/);
    if (ordered) {
      flushPara();
      openList('ol', indentOf(rawLine));
      out.push(`<li>${inline(ordered[3])}</li>`);
      continue;
    }

    const bullet = line.match(/^(\s*)[-*+•]\s+(.*)$/);
    if (bullet) {
      flushPara();
      openList('ul', indentOf(rawLine));
      out.push(`<li>${inline(bullet[2])}</li>`);
      continue;
    }

    // An indented non-marker line continues the item above it.
    if (stack.length && indentOf(rawLine) >= 2) {
      const last = out.length - 1;
      if (last >= 0 && out[last].endsWith('</li>')) {
        out[last] = out[last].replace(/<\/li>$/, `<br>${inline(line.trim())}</li>`);
        continue;
      }
    }

    closeAll();
    para.push(line.trim());
  }

  if (fence !== null) {  // unterminated fence
    out.push(`<pre><code>${escapeHtml(fence.join('\n'))}</code></pre>`);
  }
  flushPara();
  closeAll();
  return out.join('');
}

function toast(message, kind = 'info', ms = 4500) {
  clearTimeout(toastTimer);
  el.toast.textContent = message;
  el.toast.dataset.kind = kind;
  el.toast.hidden = false;
  toastTimer = setTimeout(() => { el.toast.hidden = true; }, ms);
}

function busy(button, isBusy) {
  button.disabled = isBusy;
  const spinner = button.querySelector('.spinner');
  if (spinner) spinner.hidden = !isBusy;
}

function formatClock(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (response.status === 204) return null;

  const isJson = (response.headers.get('content-type') || '').includes('json');
  const payload = isJson ? await response.json().catch(() => null) : null;

  if (!response.ok) {
    const detail = payload && payload.detail
      ? (typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail))
      : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return payload;
}

/* ── Health ──────────────────────────────────────────────────────────────── */

async function loadHealth() {
  try {
    const h = await api('/api/health');
    el.maxMb.textContent = h.max_upload_mb;
    el.version.textContent = `v${h.version}`;

    const problems = [];
    if (!h.ffmpeg) problems.push('ffmpeg missing');
    if (!h.mistral_key) problems.push('MISTRAL_API_KEY missing');

    const state = problems.length === 0 ? 'ok' : (!h.ffmpeg || !h.mistral_key ? 'bad' : 'warn');
    el.statusLed.dataset.state = state;
    el.statusLabel.textContent = problems.length ? problems[0] : 'Ready';

    const row = (label, ok, value) =>
      `<div class="status-row"><span class="status-led" data-state="${ok ? 'ok' : 'bad'}"></span>
        ${escapeHtml(label)}<strong>${escapeHtml(value)}</strong></div>`;

    el.statusPanel.innerHTML =
      row('ffmpeg', h.ffmpeg, h.ffmpeg ? 'found' : 'not found') +
      row('Mistral API key', h.mistral_key, h.mistral_key ? 'set' : 'missing') +
      row('Sarvam API key', h.sarvam_key, h.sarvam_key ? 'set' : 'optional') +
      `<div class="status-row"><span class="status-led" data-state="ok"></span>
        Whisper model<strong>${escapeHtml(h.whisper_model)}</strong></div>` +
      `<div class="status-row"><span class="status-led" data-state="ok"></span>
        Language model<strong>${escapeHtml(h.mistral_model)}</strong></div>` +
      (problems.length
        ? `<p class="status-hint">Fix: put your key in <code>.env</code> next to
           <code>requirements.txt</code>, install ffmpeg with
           <code>winget install Gyan.FFmpeg</code>, then restart the server.</p>`
        : '<p class="status-hint">Everything the pipeline needs is configured.</p>');
  } catch {
    el.statusLed.dataset.state = 'bad';
    el.statusLabel.textContent = 'Server unreachable';
  }
}

/* ── Input mode ──────────────────────────────────────────────────────────── */

function setMode(next) {
  mode = next;
  el.tabs.forEach((tab) => {
    const active = tab.dataset.mode === next;
    tab.classList.toggle('is-active', active);
    tab.setAttribute('aria-selected', String(active));
  });
  el.panes.url.hidden = next !== 'url';
  el.panes.file.hidden = next !== 'file';
}

el.tabs.forEach((tab) => tab.addEventListener('click', () => setMode(tab.dataset.mode)));

el.file.addEventListener('change', () => {
  const file = el.file.files[0];
  if (!file) { el.fileChosen.hidden = true; return; }
  const mb = (file.size / 1024 / 1024).toFixed(1);
  el.fileChosen.textContent = `${file.name} · ${mb} MB`;
  el.fileChosen.hidden = false;
});

['dragenter', 'dragover'].forEach((evt) =>
  el.dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    el.dropzone.classList.add('is-over');
  }));

['dragleave', 'drop'].forEach((evt) =>
  el.dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    el.dropzone.classList.remove('is-over');
  }));

el.dropzone.addEventListener('drop', (e) => {
  const file = e.dataTransfer.files[0];
  if (!file) return;
  el.file.files = e.dataTransfer.files;
  el.file.dispatchEvent(new Event('change'));
});

el.dropzone.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); el.file.click(); }
});

/* ── Submit ──────────────────────────────────────────────────────────────── */

el.form.addEventListener('submit', async (event) => {
  event.preventDefault();

  const body = new FormData();
  body.append('language', el.language.value);

  if (mode === 'file') {
    const file = el.file.files[0];
    if (!file) { toast('Choose a file to analyse first.', 'error'); return; }
    body.append('file', file);
  } else {
    const source = el.source.value.trim();
    if (!source) { toast('Paste a YouTube URL first.', 'error'); return; }
    body.append('source', source);
  }

  busy(el.submit, true);
  el.progressError.hidden = true;
  el.results.hidden = true;

  try {
    const job = await api('/api/jobs', { method: 'POST', body });
    startTracking(job);
  } catch (error) {
    toast(error.message, 'error', 9000);
  } finally {
    busy(el.submit, false);
  }
});

/* ── Progress tracking ───────────────────────────────────────────────────── */

function startTracking(job) {
  jobId = job.id;
  localStorage.setItem(STORE_KEY, jobId);
  el.progress.hidden = false;
  renderJob(job);
  el.progress.scrollIntoView({ behavior: 'smooth', block: 'center' });
  poll();
}

function poll() {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    if (!jobId) return;
    try {
      const job = await api(`/api/jobs/${jobId}`);
      renderJob(job);
      if (job.status === 'queued' || job.status === 'running') poll();
    } catch (error) {
      // A restart wipes in-memory jobs; drop the stale reference quietly.
      localStorage.removeItem(STORE_KEY);
      jobId = null;
      el.progressError.textContent = error.message;
      el.progressError.hidden = false;
    }
  }, POLL_MS);
}

function renderJob(job) {
  el.progressSource.textContent = job.source_label || '—';
  el.progressElapsed.textContent = formatClock(job.elapsed);

  // Analyses run one at a time, so a second one waits. Say so, otherwise the
  // all-pending step list looks like nothing is happening.
  const queued = job.status === 'queued';
  el.progressNote.hidden = !queued;
  if (queued) {
    el.progressNote.textContent =
      'Queued — waiting for the current analysis to finish. Transcription is '
      + 'CPU-bound, so they run one at a time.';
  }

  el.steps.innerHTML = job.steps.map((step) => {
    const state = job.status === 'queued' ? 'pending' : step.state;
    return `<li class="step" data-state="${state}">
      <span class="step-dot"></span>
      <span class="step-label">${escapeHtml(step.label)}</span>
      <span class="step-detail">${escapeHtml(step.detail || (state === 'done' ? 'done' : ''))}</span>
    </li>`;
  }).join('');

  if (job.status === 'error') {
    el.progressError.innerHTML = `<strong>Analysis failed.</strong> ${escapeHtml(job.error || 'Unknown error')}`;
    el.progressError.hidden = false;
  }

  if (job.status === 'done' && job.result) {
    el.progressError.hidden = true;
    renderResult(job);
  }
}

/* ── Results ─────────────────────────────────────────────────────────────── */

let renderedFor = null;

function renderResult(job) {
  const r = job.result;
  const firstTime = renderedFor !== job.id;

  el.title.textContent = r.title;
  el.sub.textContent = `${r.source_label} · ${r.language} · analysed in ${formatClock(job.elapsed)}`;
  el.summary.innerHTML = renderMarkdown(r.summary);
  el.actions.innerHTML = renderMarkdown(r.action_items);
  el.decisions.innerHTML = renderMarkdown(r.key_decisions);
  el.questions.innerHTML = renderMarkdown(r.open_questions);
  el.transcript.textContent = r.transcript;
  el.transcriptWords.textContent = `${r.transcript.trim().split(/\s+/).length.toLocaleString()} words`;
  el.exportBtn.href = `/api/jobs/${job.id}/export`;

  el.results.hidden = false;
  renderChat(job.chat || []);

  if (firstTime) {
    renderedFor = job.id;
    document.title = `${r.title} — AI Video Assistant`;
    el.results.scrollIntoView({ behavior: 'smooth', block: 'start' });
    toast('Analysis complete.', 'ok');
  }
}

el.copyTranscript.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(el.transcript.textContent);
    toast('Transcript copied to clipboard.', 'ok', 2500);
  } catch {
    toast('Your browser blocked clipboard access.', 'error');
  }
});

el.reset.addEventListener('click', () => {
  clearTimeout(pollTimer);
  jobId = null;
  renderedFor = null;
  localStorage.removeItem(STORE_KEY);
  el.results.hidden = true;
  el.progress.hidden = true;
  el.source.value = '';
  el.file.value = '';
  el.fileChosen.hidden = true;
  document.title = 'AI Video Assistant — Turn recordings into decisions';
  $('#analyse').scrollIntoView({ behavior: 'smooth', block: 'start' });
});

el.cancel.addEventListener('click', () => {
  clearTimeout(pollTimer);
  el.progress.hidden = true;
});

/* ── Chat ────────────────────────────────────────────────────────────────── */

function renderChat(history) {
  if (!history.length) {
    if (!el.chatLog.querySelector('.chat-empty')) {
      el.chatLog.innerHTML = `<div class="chat-empty">
        <p>Try one of these to start:</p>
        <div class="suggestions">
          ${['What were the main decisions made?',
             'Who is responsible for what, and by when?',
             'What risks or blockers were raised?',
             'Summarise this meeting in three sentences.']
            .map((q) => `<button type="button" class="chip" data-q="${escapeHtml(q)}">${escapeHtml(q)}</button>`)
            .join('')}
        </div></div>`;
    }
    el.clearChat.hidden = true;
    return;
  }

  el.clearChat.hidden = false;
  el.chatLog.innerHTML = history.map((msg) => {
    const isUser = msg.role === 'user';
    return `<div class="msg ${isUser ? 'msg-user' : 'msg-bot'}">
      <span class="msg-who">${isUser ? 'You' : 'Assistant'}</span>
      <div class="msg-body">${isUser ? escapeHtml(msg.content) : renderMarkdown(msg.content)}</div>
    </div>`;
  }).join('');
  el.chatLog.scrollTop = el.chatLog.scrollHeight;
}

function appendPending(question) {
  if (el.chatLog.querySelector('.chat-empty')) el.chatLog.innerHTML = '';
  el.chatLog.insertAdjacentHTML('beforeend', `
    <div class="msg msg-user">
      <span class="msg-who">You</span>
      <div class="msg-body">${escapeHtml(question)}</div>
    </div>
    <div class="msg msg-bot" id="pending">
      <span class="msg-who">Assistant</span>
      <div class="msg-body"><span class="typing"><i></i><i></i><i></i></span></div>
    </div>`);
  el.chatLog.scrollTop = el.chatLog.scrollHeight;
}

async function ask(question) {
  if (!jobId || !question.trim()) return;

  appendPending(question);
  el.chatInput.value = '';
  busy(el.chatSend, true);

  try {
    const data = await api(`/api/jobs/${jobId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    });
    renderChat(data.chat);
  } catch (error) {
    const pending = $('#pending');
    if (pending) {
      pending.querySelector('.msg-body').innerHTML =
        `<span style="color:var(--red)">${escapeHtml(error.message)}</span>`;
      pending.removeAttribute('id');
    }
    toast(error.message, 'error', 8000);
  } finally {
    busy(el.chatSend, false);
    el.chatInput.focus();
  }
}

el.chatForm.addEventListener('submit', (event) => {
  event.preventDefault();
  ask(el.chatInput.value.trim());
});

el.chatLog.addEventListener('click', (event) => {
  const chip = event.target.closest('.chip');
  if (chip) ask(chip.dataset.q);
});

el.clearChat.addEventListener('click', async () => {
  if (!jobId) return;
  try {
    await api(`/api/jobs/${jobId}/chat`, { method: 'DELETE' });
    renderChat([]);
  } catch (error) {
    toast(error.message, 'error');
  }
});

/* ── Status popover ──────────────────────────────────────────────────────── */

el.statusPill.addEventListener('click', () => {
  const open = el.statusPanel.hidden;
  el.statusPanel.hidden = !open;
  el.statusPill.setAttribute('aria-expanded', String(open));
});

document.addEventListener('click', (event) => {
  if (!el.statusPanel.hidden && !event.target.closest('.header-status')) {
    el.statusPanel.hidden = true;
    el.statusPill.setAttribute('aria-expanded', 'false');
  }
});

/* ── Boot ────────────────────────────────────────────────────────────────── */

(async function boot() {
  await loadHealth();

  // Reattach to an analysis that was still running when the page was reloaded.
  const saved = localStorage.getItem(STORE_KEY);
  if (!saved) return;
  try {
    const job = await api(`/api/jobs/${saved}`);
    jobId = saved;
    el.progress.hidden = false;
    renderJob(job);
    if (job.status === 'queued' || job.status === 'running') poll();
  } catch {
    localStorage.removeItem(STORE_KEY);
  }
})();
