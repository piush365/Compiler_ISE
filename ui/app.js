// Compiler Explorer front end. All compiling happens in ui/server.py, which
// runs the real compiler modules; this file only draws what comes back.

const PHASES = [
  { id: 'lex', num: '1', name: 'Lexical', title: 'Module 1 · Lexical analysis' },
  { id: 'parse', num: '2', name: 'Syntax', title: 'Module 2 · Syntax analysis' },
  { id: 'semantic', num: '3', name: 'Semantics', title: 'Module 3 · Syntax-directed translation and type checking' },
  { id: 'icg', num: '4', name: 'Intermediate', title: 'Module 4 · Intermediate code generation' },
  { id: 'opt', num: '5', name: 'Optimize', title: 'Module 5 · Code optimization' },
  { id: 'codegen', num: '6', name: 'Code gen', title: 'Module 6 · Code generation' },
  { id: 'verify', num: '✓', name: 'Check', title: 'Verification · run every representation and compare' },
];
const PHASE_NAMES = { lex: 'lexical analysis', parse: 'syntax analysis', semantic: 'semantic analysis' };
const LH = 20;          // editor line height, must match --lh in style.css

const $ = (id) => document.getElementById(id);
const src = $('src');
const state = {
  parser: 'll',
  active: 'icg',
  data: null,
  ai: { groq: false, gemini: false },
  grammar: null,
  seq: 0,
};

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ error: `server answered ${res.status}` }));
  if (!res.ok) throw new Error(data.error || `server answered ${res.status}`);
  return data;
}

function remember(key, value) {
  try { localStorage.setItem('compiler-explorer.' + key, value); } catch (e) { /* storage unavailable */ }
}
function recall(key) {
  try { return localStorage.getItem('compiler-explorer.' + key); } catch (e) { return null; }
}

// ---------------------------------------------------------------- editor

function lineCount() { return src.value.split('\n').length; }

function renderGutter() {
  const bad = new Set((state.data?.error?.marks || []).map((m) => m.line));
  let html = '';
  for (let i = 1; i <= lineCount(); i++) html += `<div${bad.has(i) ? ' class="bad"' : ''}>${i}</div>`;
  $('gutter').innerHTML = html;
  syncScroll();
}

function renderMarks() {
  const marks = state.data?.error?.marks || [];
  const lines = [...new Set(marks.map((m) => m.line))];
  $('marks').innerHTML = lines.map((l) => `<div style="top:${12 + (l - 1) * LH}px"></div>`).join('');
  syncScroll();
}

function syncScroll() {
  $('gutter').scrollTop = src.scrollTop;
  $('marks').style.transform = `translateY(${-src.scrollTop}px)`;
}

function updateCursor() {
  const before = src.value.slice(0, src.selectionStart);
  const line = before.split('\n').length;
  const col = src.selectionStart - before.lastIndexOf('\n');
  $('cursor').textContent = `line ${line}, col ${col}`;
}

function jumpTo(line, col) {
  const lines = src.value.split('\n');
  let pos = 0;
  for (let i = 0; i < line - 1 && i < lines.length; i++) pos += lines[i].length + 1;
  pos += Math.max(0, (col || 1) - 1);
  src.focus();
  src.setSelectionRange(pos, pos);
  src.scrollTop = Math.max(0, (line - 4) * LH);
  updateCursor();
}

src.addEventListener('input', () => {
  // the old error positions no longer match the text
  if (state.data?.error) { state.data.error.marks = []; renderMarks(); }
  renderGutter();
});
src.addEventListener('scroll', syncScroll);
src.addEventListener('keyup', updateCursor);
src.addEventListener('click', updateCursor);
src.addEventListener('keydown', (e) => {
  if (e.key === 'Tab' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
    e.preventDefault();
    const { selectionStart: a, selectionEnd: b } = src;
    src.setRangeText('    ', a, b, 'end');
    renderGutter();
  }
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); compile(); }
});

// ---------------------------------------------------------------- rail

function phaseState(id) {
  const d = state.data;
  if (!d) return 'pending';
  if (d.error && d.error.phase === id) return 'error';
  const p = d.phases?.[id];
  if (!p) return 'pending';
  if (id === 'verify') return p.ok ? 'done' : 'error';
  return p.skipped ? 'skipped' : 'done';
}

function renderRail() {
  $('rail').innerHTML = PHASES.map((p) => {
    const st = phaseState(p.id);
    const stat = st === 'error' && state.data?.error?.phase === p.id ? 'error'
      : st === 'pending' ? (state.data ? 'not reached' : '…')
      : state.data.phases[p.id].stat;
    const num = p.id === 'verify' && st === 'error' ? '✗' : p.num;
    return `<li data-phase="${p.id}" data-state="${st}">
      <button type="button" class="station" data-phase="${p.id}" aria-current="${state.active === p.id}">
        <span class="st-num">${num}</span><span class="st-name">${p.name}</span><span class="st-stat">${esc(stat)}</span>
      </button></li>`;
  }).join('');
  document.querySelector('.grammar-btn').setAttribute('aria-current', String(state.active === 'grammar'));
}

document.querySelector('.rail').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-phase]');
  if (!btn || btn.tagName !== 'BUTTON') return;
  state.active = btn.dataset.phase;
  remember('phase', state.active);
  renderRail();
  renderFeed();
});

// ---------------------------------------------------------------- listing

function sheet(sec, body) {
  return `<details class="sheet"${sec.open ? ' open' : ''}><summary>${esc(sec.title)}</summary>${body}</details>`;
}

function renderSection(sec) {
  if (sec.kind === 'text') return sheet(sec, `<pre class="bar">${esc(sec.text)}</pre>`);
  if (sec.kind === 'tokens') {
    const rows = sec.tokens.map((t, i) => `<tr><td class="muted">${i + 1}</td><td class="tok-type">${esc(t.type)}</td>`
      + `<td>${esc(t.value)}</td><td class="muted">${t.line}:${t.col}</td></tr>`).join('');
    return sheet({ ...sec, open: true }, `<table class="grid"><thead><tr><th>#</th><th>Token</th><th>Lexeme</th>`
      + `<th>Line:col</th></tr></thead><tbody>${rows}</tbody></table>`);
  }
  if (sec.kind === 'cfg') {
    const legend = `<p class="legend"><span><i class="l-fall"></i>falls through</span><span><i class="l-jump"></i>jumps forward</span>`
      + `<span><i class="l-back"></i>jumps back (loop)</span></p>`;
    const figs = sec.graphs.map((g) => `<figure class="graph">${g.label ? `<figcaption>${esc(g.label)}</figcaption>` : ''}`
      + `${flowGraphSvg(g.blocks)}</figure>`).join('');
    return sheet(sec, `<p class="note">${esc(sec.note || '')}</p>${legend}<div class="graphs">${figs}</div>`);
  }
  if (sec.kind === 'verify') return sheet(sec, verifyHtml(sec));
  return '';
}

function verifyHtml(sec) {
  const ok = sec.rows.every((r) => r.match);
  const rows = sec.rows.map((r) => `<tr><td>${esc(r.stage)}</td>`
    + `<td>${r.output ? esc(r.output.join(', ') || '(no output)') : `<span class="bad">${esc(r.error)}</span>`}</td>`
    + `<td>${r.match ? '<span class="ok">✓ matches</span>' : '<span class="bad">✗ differs</span>'}</td></tr>`).join('');
  const finals = sec.finals.length
    ? `<div class="kv"><span class="label">Final values</span>${sec.finals.map(([k, v, t]) => `<span title="${esc(t)}"><b>${esc(k)}</b> = ${esc(v)}</span>`).join('')}</div>` : '';
  const machine = sec.machine
    ? `<div class="kv"><span class="label">Machine run</span>${Object.entries(sec.machine).map(([k, v]) => `<span>${esc(k)} <b>${esc(v)}</b></span>`).join('')}</div>` : '';
  return `<div class="verdict ${ok ? 'ok' : 'bad'}">${ok ? 'All stages agree' : 'Mismatch between stages'}</div>`
    + `<table class="grid"><thead><tr><th>Representation</th><th>Printed output</th><th>Against the source</th></tr></thead>`
    + `<tbody>${rows}</tbody></table>${finals}${machine}`;
}

function renderFeed() {
  const feed = $('feed');
  if (state.active === 'grammar') {
    $('listing-title').textContent = 'Grammar tables';
    $('listing-sub').textContent = 'same for every program';
    if (!state.grammar) {
      feed.innerHTML = '<p class="ai-wait">Building tables…</p>';
      api('/api/grammar').then((g) => { state.grammar = g; if (state.active === 'grammar') renderFeed(); })
        .catch((e) => { feed.innerHTML = `<p class="banner-err">${esc(e.message)}</p>`; });
      return;
    }
    feed.innerHTML = state.grammar.sections.map(renderSection).join('');
    return;
  }
  const meta = PHASES.find((p) => p.id === state.active);
  $('listing-title').textContent = meta.title;
  const d = state.data;
  if (!d) { $('listing-sub').textContent = ''; feed.innerHTML = '<p class="ai-wait">Compiling…</p>'; return; }
  if (d.fatal) {
    $('listing-sub').textContent = '';
    feed.innerHTML = `<p class="banner-err">${esc(d.fatal)}</p>`;
    return;
  }
  const phase = d.phases[state.active];
  $('listing-sub').textContent = phase ? phase.stat : '';
  if (d.error && d.error.phase === state.active) {
    feed.innerHTML = `<div class="stopped"><strong>Compilation stopped here</strong>`
      + `<pre class="banner-err">${esc(d.error.message)}</pre>`
      + `<p class="muted">Marked in the source, with details under it.</p></div>`
      + (phase ? phase.sections.map(renderSection).join('') : '');
    return;
  }
  if (!phase) {
    const where = PHASE_NAMES[d.error?.phase] || 'an earlier phase';
    feed.innerHTML = `<div class="empty"><strong>Not reached</strong>Compilation stopped at ${where}. `
      + `Fix the error marked in the source, then compile again.</div>`;
    return;
  }
  feed.innerHTML = phase.sections.map(renderSection).join('');
}

// ---------------------------------------------------------------- flow graph drawing

function flowGraphSvg(blocks) {
  const CH = 6.9, LINE = 16, HEAD = 22, PADX = 10, GAP = 30, LANE = 12;
  const index = new Map(blocks.map((b, i) => [b.name, i]));
  const longest = Math.max(10, ...blocks.flatMap((b) => b.instrs.map((s) => s.length)));
  const boxW = Math.ceil(longest * CH + 2 * PADX);

  // vertical layout: blocks in program order
  let y = 6;
  const pos = blocks.map((b) => {
    const h = HEAD + Math.max(1, b.instrs.length) * LINE + 8;
    const p = { y, h };
    y += h + GAP;
    return p;
  });
  const height = y - GAP + 6;

  // edges that skip blocks get their own lane; forward on the right, back on the left
  const edges = [];
  blocks.forEach((b, i) => b.succ.forEach((s) => {
    const j = index.get(s);
    if (j !== undefined) edges.push({ i, j, kind: j === i + 1 ? 'fall' : j > i ? 'jump' : 'back' });
  }));
  const lanes = { jump: [], back: [] };
  for (const e of edges.filter((e) => e.kind !== 'fall').sort((a, b) => Math.abs(a.j - a.i) - Math.abs(b.j - b.i))) {
    const lo = Math.min(e.i, e.j), hi = Math.max(e.i, e.j);
    const used = lanes[e.kind];
    let k = 0;
    while (used[k] && used[k].some(([a, b]) => !(hi < a || lo > b))) k++;
    (used[k] = used[k] || []).push([lo, hi]);
    e.lane = k;
  }
  const left = 14 + lanes.back.length * LANE;
  const width = left + boxW + 14 + lanes.jump.length * LANE;

  let out = '';
  for (const e of edges) {
    const a = pos[e.i], b = pos[e.j];
    if (e.kind === 'fall') {
      const x = left + boxW / 2;
      out += `<path class="g-edge g-fall" d="M${x},${a.y + a.h} V${b.y - 1}" marker-end="url(#ah-fall)"/>`;
    } else if (e.kind === 'jump') {
      const x0 = left + boxW, xl = x0 + 14 + e.lane * LANE;
      out += `<path class="g-edge g-jump" d="M${x0},${a.y + a.h - 10} H${xl} V${b.y + 11} H${x0 + 1}" marker-end="url(#ah-jump)"/>`;
    } else {
      const xl = left - 14 - e.lane * LANE;
      out += `<path class="g-edge g-back" d="M${left},${a.y + a.h - 10} H${xl} V${b.y + 11} H${left - 1}" marker-end="url(#ah-jump)"/>`;
    }
  }
  blocks.forEach((b, i) => {
    const p = pos[i];
    out += `<g><rect class="g-box" x="${left}" y="${p.y}" width="${boxW}" height="${p.h}" rx="3"/>`
      + `<rect class="g-head" x="${left + 0.7}" y="${p.y + 0.7}" width="${boxW - 1.4}" height="${HEAD - 2}" rx="2"/>`
      + `<text class="g-name" x="${left + PADX}" y="${p.y + 15}">${esc(b.name)}</text>`
      + (i === 0 ? `<text class="g-entry" x="${left + boxW - PADX}" y="${p.y + 15}" text-anchor="end">ENTRY</text>` : '');
    if (!b.instrs.length) out += `<text class="g-empty" x="${left + PADX}" y="${p.y + HEAD + 12}">(empty)</text>`;
    b.instrs.forEach((s, k) => {
      out += `<text class="g-code" x="${left + PADX}" y="${p.y + HEAD + 12 + k * LINE}" xml:space="preserve">${esc(s)}</text>`;
    });
    out += '</g>';
  });
  const defs = '<defs>'
    + '<marker id="ah-fall" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="g-arrow-fall" d="M0,0 L8,4 L0,8 z"/></marker>'
    + '<marker id="ah-jump" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="g-arrow-jump" d="M0,0 L8,4 L0,8 z"/></marker>'
    + '</defs>';
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" `
    + `aria-label="Flow graph with ${blocks.length} basic blocks">${defs}${out}</svg>`;
}

// ---------------------------------------------------------------- diagnostics + AI

function renderDiagnostics() {
  const box = $('diagnostics');
  const err = state.data?.error;
  if (!err) { box.hidden = true; box.innerHTML = ''; return; }
  box.hidden = false;
  const loc = (m) => `line ${m.line}, col ${m.col}`;
  if (err.phase === 'semantic') {
    box.innerHTML = `<h2 class="diag-title">${esc(err.title)}</h2><p class="diag-msg muted">The program parses, `
      + `but type checking rejects it. Select an error to jump to it.</p><ul class="diag-list">`
      + err.marks.map((m) => `<li><button type="button" data-line="${m.line}" data-col="${m.col}">`
        + `<span class="loc">${m.line}:${m.col}</span><span>${esc(m.message)}</span></button></li>`).join('')
      + '</ul>';
    return;
  }
  if (err.phase === 'lex') {
    const m = err.marks[0];
    box.innerHTML = `<h2 class="diag-title">Lexical error · ${loc(m)}</h2><p class="diag-msg">${esc(m.message)}</p>`
      + `<button type="button" class="linkish" data-line="${m.line}" data-col="${m.col}">Show in source</button>`;
    return;
  }
  // syntax error: raw parser facts first, then the AI explanation of exactly those facts
  const m = err.marks[0];
  const found = err.found.value ? `${err.found.type} '${err.found.value}'` : err.found.type;
  box.innerHTML = `<h2 class="diag-title">Syntax error · ${loc(m)}</h2>`
    + `<pre class="snippet">${esc(err.snippet)}</pre>`
    + `<div class="label">Found</div><div class="expected"><span class="chip found">${esc(found)}</span></div>`
    + `<div class="label">Parser expected one of</div><div class="expected">${err.expected.map((t) => `<span class="chip">${esc(t)}</span>`).join('')}</div>`
    + `<div class="ai"><div class="ai-head"><h3>Plain-English explanation</h3><span class="muted" id="ai-src"></span></div>`
    + `<div class="ai-body" id="ai-body"></div>`
    + `<p class="ai-note">The AI gets only the parser's error and expected tokens. It does not parse your code.</p></div>`;
  explain();
}

$('diagnostics').addEventListener('click', (e) => {
  const b = e.target.closest('[data-line]');
  if (b) jumpTo(+b.dataset.line, +b.dataset.col);
  if (e.target.closest('#ai-retry')) explain();
});

function providers() {
  const p = [];
  if (state.ai.groq) p.push('Groq');
  if (state.ai.gemini) p.push(p.length ? 'Gemini fallback' : 'Gemini');
  return p.join(', ');
}

async function explain() {
  const body = $('ai-body');
  if (!body) return;
  if (!state.ai.groq && !state.ai.gemini) {
    $('ai-src').textContent = 'off';
    body.innerHTML = '<p class="muted">To turn this on, set <code>GROQ_API_KEY</code> or <code>GEMINI_API_KEY</code> '
      + 'in the terminal, then restart <code>python3 ui/server.py</code>.</p>';
    return;
  }
  const seq = state.seq;
  $('ai-src').textContent = providers();
  body.innerHTML = `<p class="ai-wait">Asking ${state.ai.groq ? 'Groq' : 'Gemini'}…</p>`;
  try {
    const r = await api('/api/explain', { source: src.value, parser: state.parser });
    if (seq !== state.seq || !$('ai-body')) return;      // a newer compile replaced this panel
    if (!r.text) { body.innerHTML = '<p class="muted">The source has changed and no longer has a syntax error.</p>'; return; }
    if (/^\[(API Error|Fallback Error)/.test(r.text)) {
      body.innerHTML = `<div class="ai-warn">${esc(r.text)}</div><p><button type="button" class="linkish" id="ai-retry">Try again</button></p>`;
    } else {
      body.innerHTML = markdown(r.text);
    }
  } catch (e) {
    if (seq === state.seq && $('ai-body')) {
      $('ai-body').innerHTML = `<div class="ai-warn">${esc(e.message)}</div><p><button type="button" class="linkish" id="ai-retry">Try again</button></p>`;
    }
  }
}

// Small, safe Markdown subset for the model's answer: paragraphs, lists, code, bold.
function markdown(text) {
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>');
  const out = [];
  let list = null, para = [], code = null;
  const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join('')}</${list.tag}>`); list = null; } };
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd();
    if (code !== null) {
      if (/^```/.test(line)) { out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`); code = null; } else code.push(raw);
      continue;
    }
    if (/^```/.test(line)) { flushPara(); flushList(); code = []; continue; }
    const ul = line.match(/^\s*[-*•]\s+(.*)/), ol = line.match(/^\s*\d+[.)]\s+(.*)/);
    if (ul || ol) {
      flushPara();
      const tag = ul ? 'ul' : 'ol';
      if (!list || list.tag !== tag) { flushList(); list = { tag, items: [] }; }
      list.items.push((ul || ol)[1]);
      continue;
    }
    if (!line.trim()) { flushPara(); flushList(); continue; }
    flushList();
    const h = line.match(/^#{1,6}\s+(.*)/);
    if (h) { flushPara(); out.push(`<p><strong>${inline(h[1])}</strong></p>`); continue; }
    para.push(line.trim());
  }
  if (code !== null) out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
  flushPara(); flushList();
  return out.join('');
}

// ---------------------------------------------------------------- compile

async function compile() {
  const seq = ++state.seq;
  const btn = $('compile');
  btn.setAttribute('aria-busy', 'true');
  const regs = Math.min(16, Math.max(2, parseInt($('regs').value, 10) || 4));
  $('regs').value = regs;
  try {
    const data = await api('/api/compile', { source: src.value, parser: state.parser, regs, opt: $('opt').checked });
    if (seq !== state.seq) return;
    state.data = data;
    // when compilation stops early, show the failing phase
    if (data.error && state.active !== 'grammar') state.active = data.error.phase;
  } catch (e) {
    if (seq !== state.seq) return;
    state.data = { phases: {}, error: null, fatal: e.message };
  } finally {
    if (seq === state.seq) btn.removeAttribute('aria-busy');
  }
  renderRail();
  renderFeed();
  renderGutter();
  renderMarks();
  renderDiagnostics();
}

$('compile').addEventListener('click', compile);
$('opt').addEventListener('change', compile);
$('regs').addEventListener('change', compile);
document.querySelector('.seg').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-parser]');
  if (!b) return;
  state.parser = b.dataset.parser;
  document.querySelectorAll('.seg button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
  remember('parser', state.parser);
  compile();
});

async function init() {
  const saved = recall('phase');
  if (saved && (saved === 'grammar' || PHASES.some((p) => p.id === saved))) state.active = saved;
  const parser = recall('parser');
  if (parser === 'll' || parser === 'slr') {
    state.parser = parser;
    document.querySelectorAll('.seg button').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.parser === parser)));
  }
  renderRail();
  renderFeed();
  try {
    const [examples, ai] = await Promise.all([api('/api/examples'), api('/api/status')]);
    state.ai = ai;
    const sel = $('example');
    sel.innerHTML = examples.map((ex, i) => `<option value="${i}">${esc(ex.name.replace(/\.src$/, '').replace(/^\d+_/, '').replace(/_/g, ' '))}</option>`).join('');
    const start = Math.max(0, examples.findIndex((ex) => ex.name.startsWith('03')));
    sel.value = String(start);
    src.value = examples[start].source;
    src.setSelectionRange(0, 0);
    sel.addEventListener('change', () => {
      src.value = examples[+sel.value].source;
      src.setSelectionRange(0, 0);
      src.scrollTop = 0;
      updateCursor();
      compile();
    });
  } catch (e) {
    src.value = '';
    state.data = { phases: {}, error: null, fatal: `Could not reach the compiler server: ${e.message}` };
    renderFeed();
    return;
  }
  renderGutter();
  updateCursor();
  compile();
}

init();
