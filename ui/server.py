"""
ui/server.py - Browser UI for the compiler. Standard library only.

    python3 ui/server.py                  then open http://localhost:8000
    python3 ui/server.py --port 9000
    python3 ui/server.py --host 0.0.0.0   reachable from other devices on the network

Every request runs the real compiler modules from the project folder, so the
UI shows exactly what main.py prints, phase by phase. The AI error explainer
reads GROQ_API_KEY / GEMINI_API_KEY from the environment of this process; the
keys never reach the browser.
"""
import argparse
import contextlib
import io
import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UI_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(UI_DIR)
sys.path.insert(0, ROOT)

import ai_error_explainer
import grammar
from ast_nodes import format_tree
from cfg import leaders_report
from compiler import CompileError, compile_source, verify
from dag import format_dags
from icg import format_indirect_triples, format_quadruples, format_tac, format_triples
from lexer import LexError, Lexer
from parser_bottom_up import ParserBottomUp
from runtime import storage_report
from target import format_code

EXAMPLES_DIR = os.path.join(ROOT, 'examples')
MAX_SOURCE = 20_000
MAX_REGS = 16
STATIC = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
    '/style.css': ('style.css', 'text/css; charset=utf-8'),
}

# The parsers print their traces to stdout; capture them one request at a time.
_stdout_lock = threading.Lock()


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def section(title, text, open_=True):
    return {'kind': 'text', 'title': title, 'text': text, 'open': open_}


def cfg_blocks(g):
    return [{'name': b.name, 'instrs': [str(q) for q in b.instrs], 'succ': list(b.succ)} for b in g.blocks]


def counts(stats):
    return '\n'.join(f"{n:>3} x {kind}" for kind, n in sorted(stats.items(), key=lambda x: -x[1]))


def agrees(row, ref):
    """Same comparison verify() makes, per row, so the UI can mark each stage."""
    if row[1] is None or ref[1] is None:
        return row[1] is None and ref[1] is None
    return row[1] == ref[1] and all(type(row[2][k]) is type(v) and row[2][k] == v for k, v in ref[2].items())


def compile_view(source, parser='ll', regs=4, opt=True):
    """Run the pipeline phase by phase, keeping every phase that finished."""
    view = {'phases': {}, 'error': None}
    P = view['phases']
    slr = parser == 'slr'

    # ---------------- Module 1: lexical analysis ----------------
    try:
        tokens = Lexer(source).tokenize()
    except LexError as e:
        view['error'] = {'phase': 'lex', 'title': 'Lexical error', 'message': str(e),
                         'marks': [{'line': e.line, 'col': e.column, 'message': e.message}]}
        return view
    P['lex'] = {'stat': plural(len(tokens), 'token'), 'sections': [
        {'kind': 'tokens', 'title': 'Token stream',
         'tokens': [{'type': t.type, 'value': t.value, 'line': t.line, 'col': t.column} for t in tokens]}]}

    # ---------------- Module 2: syntax analysis ----------------
    trace = io.StringIO()
    try:
        with contextlib.redirect_stdout(trace):
            c = compile_source(source, parser=parser, upto='parse', slr_trace=slr)
    except CompileError as e:
        info = e.detail.error_info
        view['error'] = {'phase': 'parse', 'title': 'Syntax error', 'message': info.message,
                         'snippet': info.source_snippet, 'expected': sorted(info.expected_tokens),
                         'found': {'type': info.token.type, 'value': info.token.value},
                         'marks': [{'line': info.token.line, 'col': info.token.column, 'message': info.message}]}
        if slr:
            P['parse'] = {'stat': 'error', 'sections': [
                section('SLR(1) shift/reduce trace, up to the error', trace.getvalue())]}
        return view
    how = 'SLR(1) bottom-up, S-attributed' if slr else 'LL(1) recursive descent, L-attributed'
    parse_sections = [section(f'Abstract syntax tree ({how})', format_tree(c.ast, 1))]
    if slr:
        parse_sections.append(section('SLR(1) shift/reduce trace', trace.getvalue(), open_=False))
    P['parse'] = {'stat': plural(len(c.ast), 'statement'), 'sections': parse_sections}

    # ---------------- Modules 3-6 ----------------
    try:
        c = compile_source(source, parser=parser, nregs=regs, opt=opt)
    except CompileError as e:
        if e.phase != 'semantic':
            raise
        view['error'] = {'phase': 'semantic', 'message': e.message,
                         'title': f"{len(e.detail)} semantic error{'s' if len(e.detail) != 1 else ''}",
                         'marks': [{'line': s.line, 'col': s.col, 'message': s.message} for s in e.detail]}
        return view

    P['semantic'] = {'stat': plural(len(c.user_vars), 'variable'), 'sections': [
        section('Annotated syntax tree (synthesized attribute .ty)', format_tree(c.ast, 1, show_types=True)),
        section('Symbol table (hash table, hashpjw, 211 buckets, separate chaining)', c.symtab.format()),
        section('Attribute evaluation order (post-order = S-attributed evaluation)',
                '\n'.join(c.analyzer.trace), open_=False),
    ]}

    quads = c.icg.quads
    P['icg'] = {'stat': f"{plural(len(quads), 'quad')} · {plural(len(c.cfg.blocks), 'block')}", 'sections': [
        section('Three-address code (backpatching)', format_tac(quads)),
        {'kind': 'cfg', 'title': 'Flow graph', 'open': True, 'note': 'Leaders: ' + leaders_report(quads),
         'graphs': [{'label': None, 'blocks': cfg_blocks(c.cfg)}]},
        section('SSA form', c.ssa.format()),
        section('Quadruples', format_quadruples(quads), open_=False),
        section('Triples (a temporary is referenced by the number of the triple computing it)',
                format_triples(quads, c.icg.temps), open_=False),
        section('Indirect triples (execution order is a list of pointers)',
                format_indirect_triples(quads), open_=False),
    ]}

    before, after = c.cfg.instr_count(), c.opt_cfg.instr_count()
    if opt:
        o = c.optimizer
        P['opt'] = {'stat': f"{before} → {after} instrs", 'sections': [
            {'kind': 'cfg', 'title': 'Flow graph before and after', 'open': True,
             'note': f"{before} → {after} instructions, {len(c.cfg.blocks)} → {len(c.opt_cfg.blocks)} basic blocks",
             'graphs': [{'label': 'Before', 'blocks': cfg_blocks(c.cfg)},
                        {'label': 'After', 'blocks': cfg_blocks(c.opt_cfg)}]},
            section('Transformations applied', counts(o.stats) or '(none: the code was already optimal)'),
            section('Natural loops', '\n'.join(o.loops_report) or '(none)'),
            section('Optimization log', '\n'.join(o.log) or '(empty)', open_=False),
        ]}
    else:
        P['opt'] = {'stat': 'skipped', 'skipped': True, 'sections': [
            section('Optimization skipped',
                    'Optimize is off, so the code generator works from the unoptimized three-address code.')]}

    real = len([i for i in c.final_code if i.op != 'LABEL'])
    P['codegen'] = {'stat': f"{plural(real, 'instr')} · {regs} regs", 'sections': [
        section('Final target code (after peephole)', format_code(c.final_code)),
        section(f"Peephole optimization: {len(c.code)} → {len(c.final_code)} lines",
                counts(c.peephole_stats) or '(no changes)'),
        section('Storage organization', storage_report(c.symtab, real, c.codegen.spilled)),
        section('Target code before peephole (getReg with register and address descriptors)',
                format_code(c.code), open_=False),
        section('DAG of each basic block', format_dags(c.opt_cfg), open_=False),
    ]}

    # ---------------- Verification ----------------
    v = verify(c)
    ref = v.results[0]
    rows = [{'stage': stage, 'output': out, 'error': None if out is not None else fin,
             'match': agrees((stage, out, fin), ref)} for stage, out, fin in v.results]
    finals = [[k, str(val), type(val).__name__] for k, val in ref[2].items()] if ref[1] is not None else []
    P['verify'] = {'stat': 'all stages agree' if v.ok else 'mismatch', 'ok': v.ok, 'sections': [
        {'kind': 'verify', 'title': 'The program, run at every level', 'open': True, 'rows': rows,
         'finals': finals, 'machine': v.machine_stats}]}
    return view


def explain_view(source, parser):
    """Re-detect the syntax error on the server and pass it to the AI explainer."""
    try:
        with _stdout_lock, contextlib.redirect_stdout(io.StringIO()):
            compile_source(source, parser=parser, upto='parse')
    except CompileError as e:
        if e.phase == 'syntax':
            return {'text': ai_error_explainer.explain_syntax_error(e.detail.error_info, source)}
    return {'text': None}


def ai_status():
    return {'groq': bool(os.environ.get('GROQ_API_KEY')) and ai_error_explainer.Groq is not None,
            'gemini': bool(os.environ.get('GEMINI_API_KEY')) and ai_error_explainer.genai is not None}


def grammar_view():
    out = {}
    lexer = Lexer('x = 1;')
    lexer.tokenize()
    for key, fn in (('sets', grammar.print_sets_table), ('ll1', grammar.print_ll1_table),
                    ('slr', ParserBottomUp(lexer).print_parsing_table)):
        buf = io.StringIO()
        with _stdout_lock, contextlib.redirect_stdout(buf):
            fn()
        out[key] = buf.getvalue()
    return {'sections': [
        section('FIRST and FOLLOW sets (transformed grammar)', out['sets']),
        section('LL(1) predictive parsing table', out['ll1'], open_=False),
        section('SLR(1) ACTION / GOTO table', out['slr'], open_=False),
    ]}


def load_examples():
    files = sorted(f for f in os.listdir(EXAMPLES_DIR) if f.endswith('.src'))
    result = []
    for name in files:
        with open(os.path.join(EXAMPLES_DIR, name), encoding='utf-8') as f:
            result.append({'name': name, 'source': f.read()})
    return result


class Handler(BaseHTTPRequestHandler):
    def send_body(self, body, ctype, status=200):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj, status=200):
        self.send_body(json.dumps(obj).encode('utf-8'), 'application/json; charset=utf-8', status)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path in STATIC:
            name, ctype = STATIC[path]
            with open(os.path.join(UI_DIR, name), 'rb') as f:
                self.send_body(f.read(), ctype)
        elif path == '/api/examples':
            self.send_json(load_examples())
        elif path == '/api/status':
            self.send_json(ai_status())
        elif path == '/api/grammar':
            self.send_json(grammar_view())
        else:
            self.send_json({'error': 'not found'}, 404)

    def do_POST(self):
        path = self.path.split('?', 1)[0]
        if path not in ('/api/compile', '/api/explain'):
            return self.send_json({'error': 'not found'}, 404)
        try:
            length = int(self.headers.get('Content-Length', 0))
            try:
                body = json.loads(self.rfile.read(length) or b'{}')
            except json.JSONDecodeError:
                raise ValueError('request body must be JSON')
            if not isinstance(body, dict):
                raise ValueError('request body must be a JSON object')
            source = body.get('source', '')
            if not isinstance(source, str):
                raise ValueError('source must be a string')
            if len(source) > MAX_SOURCE:
                raise ValueError(f'source is longer than {MAX_SOURCE} characters')
            parser = 'slr' if body.get('parser') == 'slr' else 'll'
            regs = int(body.get('regs', 4))
            if not 2 <= regs <= MAX_REGS:
                raise ValueError(f'registers must be between 2 and {MAX_REGS}')
        except (ValueError, TypeError) as e:
            return self.send_json({'error': str(e)}, 400)
        try:
            if path == '/api/explain':
                return self.send_json(explain_view(source, parser))
            with _stdout_lock:
                view = compile_view(source, parser, regs, bool(body.get('opt', True)))
            self.send_json(view)
        except Exception as e:
            traceback.print_exc()
            self.send_json({'error': f"internal compiler error: {type(e).__name__}: {e}"}, 500)

    def log_message(self, fmt, *args):
        if not self.path.startswith('/api/status'):
            sys.stderr.write(f"  {self.command} {self.path.split('?', 1)[0]} -> {args[1] if len(args) > 1 else ''}\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description='Browser UI for the compiler.')
    ap.add_argument('--host', default='127.0.0.1', help='interface to listen on (default: this machine only)')
    ap.add_argument('--port', type=int, default=8000)
    args = ap.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    status = ai_status()
    ai = ' + '.join(name for name, ok in (('Groq', status['groq']), ('Gemini', status['gemini'])) if ok)
    print(f"Compiler Explorer running at http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}")
    print(f"AI error explainer: {ai or 'off (set GROQ_API_KEY or GEMINI_API_KEY to enable it)'}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
