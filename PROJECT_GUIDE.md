# Compiler_ISE: Project Guide

This guide explains the whole project: what it is, how the pieces fit together, how to run it, and what happens to a program on its way through the compiler. It ends with how the project checks its own output and how the web UI is built.

Three documents cover the project, each with a different job:

| Document | Read it for |
|---|---|
| `README.md` | A short summary, the grammar, and the commands |
| `PROJECT_GUIDE.md` (this file) | The big picture, a worked example through every phase, the AI explainer and the web UI |
| `explain.md` | The theory behind each phase, in depth, with likely viva questions |

---

## 1. The project in one minute

Compiler_ISE is a complete compiler for a small C-like language, written in pure Python. It covers all six modules of the Compiler Design syllabus. The compiler does not use parser generators or any other compiler libraries; every phase is hand-written.

- **Input:** a program with `int`, `float` and `bool` values, arithmetic, boolean logic, `if/else`, `while`, `print`, and the built-in functions `sin`, `cos`, `log` and `sqrt`.
- **Output:** assembly code for a simple register machine, plus a printout of every intermediate representation along the way.
- **Two parsers:** a top-down LL(1) recursive-descent parser and a bottom-up SLR(1) shift-reduce parser. Both build the same syntax tree.
- **Self-checking:** after compiling, the project *runs* the program at six levels (source, three-address code, SSA, optimized code, machine code, and machine code after peephole optimization) and confirms they all print the same results.
- **AI error explainer:** when the parser finds a syntax error, an LLM (Groq, with Gemini as the fallback) turns the parser's exact error into plain English. The AI never parses anything itself.
- **Two ways to use it:** a terminal driver (`main.py`) and a browser UI (`ui/server.py`). Both run the same compiler code.

Size: about 4,000 lines of Python for the compiler and terminal driver, about 1,370 lines for the web UI, and about 310 lines of tests.

---

## 2. Quick start

Requirements: Python 3 (developed and tested on 3.14). The compiler and the UI use only the standard library. The AI explainer optionally needs the `groq` or `google-generativeai` package.

```bash
# Terminal: compile a program and print every phase
python3 main.py                              # default example: examples/03_optimizations.src
python3 main.py examples/04_gcd_primes.src

# Browser UI
python3 ui/server.py                         # then open http://localhost:8000

# Tests
python3 -m unittest discover tests           # 15 unit and end-to-end tests
python3 tests/fuzz.py 200                    # 200 random programs through every phase
```

To turn on AI explanations, set at least one key in the terminal before running either the terminal driver or the UI server:

```bash
export GROQ_API_KEY="your-groq-api-key"
export GEMINI_API_KEY="your-gemini-api-key"  # used if Groq is not set up or fails
```

---

## 3. The language

```c
n = 10; i = 0; sum = 0;          // a variable is declared, and its type fixed, by its first assignment
while (i < n && !(i == 7)) {
    if (i % 2 == 0 || i > 8) { sum = sum + i * 2; } else { sum = sum - 1; }
    i = i + 1;
}
avg = sum / 2.5 + sqrt(n);       // int is converted to float automatically where needed
print(sum); print(avg);
```

- **Types:** `int`, `float`, `bool`. A variable's type is set by its first assignment and can't change afterwards. An `int` may be widened to `float`; a `float` can't be stored in an `int` variable.
- **Operators,** from lowest to highest precedence: `||`, `&&`, `< <= > >= == !=`, `+ -`, `* / %`, unary `- !`, and `^` (power, right-associative).
- **Statements:** assignment, `print(expr);`, `if/else if/else`, `while`, and `{ blocks }`. Braces are required, so the "dangling else" ambiguity can't occur.
- Integer `/` truncates toward zero and `%` takes the sign of the dividend, as in C.

The full grammar is in `README.md`.

---

## 4. Architecture

### 4.1 The pipeline

```
 source text
     │
     ▼
 ┌─────────────┐  tokens   ┌──────────────────┐   AST    ┌─────────────────────┐
 │ 1 Lexer     │──────────▶│ 2 Parser         │─────────▶│ 3 Semantic analysis │
 │  lexer.py   │           │  LL(1) or SLR(1) │          │  types, symbol table│
 └─────────────┘           └──────────────────┘          └─────────────────────┘
                                   │ syntax error                    │ annotated AST
                                   ▼                                 ▼
                          ┌──────────────────┐            ┌─────────────────────┐
                          │ AI explainer     │            │ 4 Intermediate code │
                          │ (plain English)  │            │  TAC, flow graph,   │
                          └──────────────────┘            │  SSA                │
                                                          └─────────────────────┘
                                                                     │ flow graph
                                                                     ▼
 ┌─────────────────────┐  machine code  ┌──────────────────┐  ┌─────────────────────┐
 │ Verification        │◀───────────────│ 6 Code generator │◀─│ 5 Optimizer         │
 │ run every level and │                │  getReg, DAGs,   │  │  local, global,     │
 │ compare the results │                │  peephole        │  │  loop optimizations │
 └─────────────────────┘                └──────────────────┘  └─────────────────────┘
```

It is a **multi-pass** compiler: each phase gets the complete output of the phase before it. The optimizer needs this, because it has to see the whole program at once.

`compiler.py` connects the phases. Its `compile_source()` function runs them in order and keeps every intermediate result in a single `Compilation` object. Both the terminal driver and the web UI read from that object, which is why they always agree.

### 4.2 File map

**Front end: from text to a checked syntax tree**

| File | Role |
|---|---|
| `lexer.py` | Regex scanner. Turns source text into tokens, tracking line and column, and recognizes keywords and the longest matching operator. |
| `grammar.py` | Both grammars. Computes FIRST/FOLLOW sets and the LL(1) table, and checks for conflicts. |
| `parser_recursive_descent.py` | LL(1) top-down parser. Builds the AST with an L-attributed definition. |
| `parser_bottom_up.py` | SLR(1) parser. Builds the LR(0) item sets and ACTION/GOTO tables, and builds the AST with an S-attributed definition. |
| `ast_nodes.py` | Syntax tree node classes and the tree printer. |
| `semantic.py` | Type checking and coercions, plus the symbol table: a hash table using hashpjw, with 211 buckets. |
| `ai_error_explainer.py` | Sends the parser's syntax error to Groq or Gemini and returns a plain-English explanation. |

**Middle: intermediate code and optimization**

| File | Role |
|---|---|
| `icg.py` | Three-address code with backpatching; quadruples, triples and indirect triples. |
| `cfg.py` | Basic blocks, the flow graph, dominators, natural loops and liveness analysis. |
| `ssa.py` | SSA form: dominance frontiers, φ-functions and variable renaming. Also includes an SSA interpreter. |
| `optimizer.py` | Constant folding and propagation, copy propagation, common-subexpression elimination (CSE), algebraic simplification, strength reduction, dead-code elimination, jump optimizations and loop-invariant code motion. |
| `dag.py` | The DAG representation of each basic block. |

**Back end: machine code**

| File | Role |
|---|---|
| `codegen.py` | Code generator. Uses getReg with register and address descriptors, and spills values to memory when it runs out of registers. |
| `peephole.py` | Peephole optimizer: removes redundant loads and stores, unused labels and jumps to jumps, and uses `INC`/`DEC`. |
| `target.py` | The target machine's instruction set, plus a simulator that runs it. |
| `runtime.py` | Storage layout report: static area, activation records and the stack. |

**Support, drivers and tests**

| File | Role |
|---|---|
| `ops.py` | The single definition of what every operator and built-in function *means* at run time. Every interpreter and the simulator share it. |
| `interpreter.py` | Runs the AST, the three-address code and the flow graph directly, for verification. |
| `compiler.py` | Runs the phases in order (`compile_source`) and checks the results (`verify`). |
| `main.py` | Terminal driver. Prints every phase, with options. |
| `ui/` | Web UI: `server.py` (backend), plus `index.html`, `app.js` and `style.css`. |
| `examples/` | Six sample programs. |
| `tests/test_compiler.py`, `tests/fuzz.py` | Unit tests, and a random program generator for differential testing. |

---

## 5. A worked example: one program through every phase

This program is short but uses a loop, so every phase has something to do. All the output below is real, produced by `python3 main.py` on this program (shortened in places).

```c
x = 4;
y = x * 2 + 0;
i = 0;
while (i < 3) {
    y = y + x * 3;
    i = i + 1;
}
print(y);
```

### Module 1: Lexical analysis

The lexer turns characters into tokens, and each token records where it was found:

```
IDENTIFIER(x) ASSIGN INT(4) SEMI IDENTIFIER(y) ASSIGN IDENTIFIER(x) STAR INT(2) PLUS INT(0) SEMI
IDENTIFIER(i) ASSIGN INT(0) SEMI WHILE LPAREN IDENTIFIER(i) LT INT(3) RPAREN LBRACE ... EOF
```

Comments and whitespace are dropped here. `while` becomes the keyword token `WHILE`, not an identifier.

### Module 2: Syntax analysis

The parser checks the token sequence against the grammar and builds an abstract syntax tree:

```
Assign y
  BinOp '+'
    BinOp '*'          ← * binds tighter than +, so it sits lower in the tree
      Var x
      Num 2
    Num 0
While
  cond:  BinOp '<' (Var i, Num 3)
  body:  Assign y ... ; Assign i ...
```

The LL(1) and SLR(1) parsers build *identical* trees, and a unit test checks this. Choose the SLR(1) parser (`--parser slr`, or the switch in the UI) to see its shift/reduce trace.

### Module 3: Semantic analysis

Each tree node gets a type, computed bottom-up from its children (this is called a synthesized attribute):

```
BinOp '+'  : int
  BinOp '*'  : int
    Var x  : int
    Num 2  : int
```

The symbol table records every name, along with its hash bucket and its place in memory:

```
Name  Kind      Type  Bucket  Offset  Width  Declared  Used at lines
x     variable  int   120     0       4      1         2, 5
y     variable  int   121     4       4      2         5, 8
i     variable  int   105     8       4      3         4, 6
Static data area size: 12 bytes
```

This is also where type errors are caught. For example, `w = flag + 1;` fails because `flag` is a `bool` and `+` needs numbers.

### Module 4: Intermediate code

The tree is flattened into three-address code (TAC): each instruction does at most one operation. Jumps are filled in by **backpatching**: a jump target that isn't known yet is left blank, then patched once the target is generated.

```
 0: x = 4                 7: t3 = x * 3
 1: t1 = x * 2            8: t4 = y + t3
 2: t2 = t1 + 0           9: y = t4
 3: y = t2               10: t5 = i + 1
 4: i = 0                11: i = t5
 5: if i < 3 goto 7      12: goto 5
 6: goto 13              13: print y
                         14: halt
```

The same code is also shown as quadruples, triples and indirect triples. Next it is split into **basic blocks**: straight-line runs of code that are always entered at the top. The blocks are connected into a **flow graph**:

```
B1 (setup) → B2 (if i < 3) → B4 (loop body) → back to B2
                           → B3 (goto) → B5 (print, halt)
```

The flow graph is then converted to **SSA form** (static single assignment), where every variable is assigned exactly once. Where two control paths meet, a φ-function picks the right version of each variable:

```
B2:
    y_2 = phi(B1: y_1, B4: y_3)     ← y comes from before the loop, or from the last iteration
    i_2 = phi(B1: i_1, B4: i_3)
```

### Module 5: Optimization

The optimizer rewrites the flow graph. Every change is logged:

```
[constant propagation]  t1 = x * 2  =>  t1 = 4 * 2       (x is known to be 4)
[constant folding]      t1 = 4 * 2  =>  t1 = 8
[constant folding]      t2 = 8 + 0  =>  t2 = 8
[copy coalescing]       t4 = y + 12 ; y = t4  =>  y = y + 12
[dead code elimination] t1 = 8  (t1 is never used)
[jumps over jumps]      if i < 3 goto B4 ; goto B5  =>  if i >= 3 goto B5
```

It also finds the loop: header `B2`, back edge `B4 → B2`, and induction variables `y` (+12 per iteration) and `i` (+1). Result: **15 → 9 instructions, 5 → 4 basic blocks.**

```
B1:  x = 4 ; y = 8 ; i = 0
B2:  if i >= 3 goto B5
B4:  y = y + 12 ; i = i + 1 ; goto B2
B5:  print y ; halt
```

### Module 6: Code generation

The code generator turns each block into machine instructions. Its getReg routine picks registers, using *register descriptors* (what each register holds) and *address descriptors* (where each variable's current value lives). The peephole pass then cleans up the result. Here it turned `ADD R1, R1, #1` into `INC R1` and removed two labels nothing jumps to:

```
    LD    R0, #4          B2:                     B5:
    LD    R1, #8              LD    R0, i             LD    R0, y
    LD    R2, #0              BGE   R0, #3, B5        PRINT R0
    ST    i, R2               LD    R0, y             HALT
    ST    x, R0               ADD   R0, R0, #12
    ST    y, R1               LD    R1, i
                              INC   R1
                              ST    i, R1
                              ST    y, R0
                              BR    B2
```

### Verification

Finally, the program is executed at every level and the results are compared:

```
source (AST interpreter)     output: [44]
three-address code           output: [44]
SSA form                     output: [44]
optimized TAC                output: [44]
target code                  output: [44]
target code after peephole   output: [44]
final variable values: x=4, y=44, i=3
RESULT: all stages agree
```

---

## 6. When the program has errors

Compilation stops at the first phase that finds a problem. Every error is reported with its line and column.

| Phase | Example | What you see |
|---|---|---|
| Lexical | `x = 3 @ 4;` | `Lexical error at line 1, column 7: Unexpected character '@'` |
| Syntax | `y = (4 + 5 * 2;` | The parser's error, the token it found, the tokens it expected, and an AI explanation |
| Semantic | `w = flag + 1;` | Every type error in the program, not just the first one |

A syntax error from the LL(1) parser looks like this:

```
Syntax error at line 3, col 15. Unexpected token SEMI. Expected one of: AND, CARET, EQ, GE, GT,
LE, LT, MINUS, NE, OR, PERCENT, PLUS, RPAREN, SLASH, STAR.
y = (4 + 5 * 2;
              ^
```

The expected-token list comes straight from the parser's tables: the FIRST and FOLLOW sets for LL(1), or the ACTION table for SLR(1). `RPAREN` is in the list, which is the real fix here.

In the web UI, error lines are highlighted in the editor. The failing phase turns red in the phase rail, and the details appear under the editor; for semantic errors you can click each one to jump to its line.

---

## 7. The AI error explainer

The parser finds every syntax error by itself. The explainer's only job is to make that error easy to understand.

1. The parser fails and builds a `SyntaxErrorInfo`: the token it found, its line and column, the set of expected tokens, and a snippet of the source.
2. `explain_syntax_error()` puts exactly those facts into a prompt. The prompt tells the model to trust the parser's expected tokens and not to re-parse the code.
3. It asks **Groq** first, using the model `openai/gpt-oss-20b` (the `GROQ_MODEL` variable overrides this). If Groq has no key or fails, it asks **Gemini** (`gemini-2.5-flash`).
4. If neither is available, it returns the raw parser error together with the reason, e.g. `GROQ_API_KEY missing`, or the exact Groq error message.

So the AI is a translator, not a parser. The compiler stays deterministic and testable, and the answer is grounded in what the parser actually computed.

**About the Groq model:** Groq retires models over time. The original `llama3-8b-8192` was shut down on 2025-08-30, and its replacement, `llama-3.1-8b-instant`, on 2026-08-16. If `openai/gpt-oss-20b` is retired too, set `GROQ_MODEL` to Groq's current recommendation; no code change is needed. `gpt-oss` is a reasoning model, so the request sets `reasoning_effort="low"` and a 1,024-token limit, which leaves room for the actual answer.

---

## 8. How correctness is checked

There are three layers of checking:

1. **Verification on every run.** `verify()` in `compiler.py` executes the program as an AST, as TAC, in SSA form, as optimized TAC, and on the machine simulator before and after peephole optimization. The printed output *and* the final value and type of every variable must match. Every interpreter and the simulator use the same operator definitions from `ops.py`, so this compares the *translation*, not different arithmetic.
2. **Unit tests** (`tests/test_compiler.py`, 15 tests): lexer keywords, conflict-free grammars, identical trees from both parsers, precedence and associativity, error detection, type coercion, symbol-table offsets, backpatching of `||`, loop jumps, every example agreeing at every level, optimizations actually firing, and the `INC` peephole idiom.
3. **Differential fuzzing** (`tests/fuzz.py`): generates random, well-typed programs with nested ifs, bounded loops, mixed types and built-in calls. It runs each one through both parsers, with and without optimization, and with 2, 3 and 4 registers. All stages must agree. The fuzzer has found and fixed real bugs, such as a missing φ-function for variables that are only read at the end of the program.

---

## 9. The web UI

### 9.1 How it is built

```
 Browser (index.html, app.js, style.css)          ui/server.py (Python standard library)
 ┌────────────────────────────────────┐   JSON    ┌──────────────────────────────────────────┐
 │ editor, phase rail, listing views, │ ────────▶ │ POST /api/compile → compile_view()       │
 │ flow-graph drawings, error panel   │ ◀──────── │   lexer, parsers, compile_source,        │
 └────────────────────────────────────┘           │   verify, and the existing format_*()    │
                                                  │ POST /api/explain → explain_syntax_error │
                                                  │ GET  /api/examples, /api/status,         │
                                                  │      /api/grammar                        │
                                                  └──────────────────────────────────────────┘
```

- **It's the real compiler.** The server imports the same modules as `main.py` and uses the same formatting functions, so the UI can't drift away from the terminal output.
- **Partial results.** The server runs the phases one at a time and keeps every phase that finished. So if a program has a type error, you still see its tokens and its syntax tree.
- **API keys stay on the server.** The browser only asks "explain this source". The server finds the syntax error again itself and calls the explainer. Keys are never sent to the page, and by default the server only listens on `127.0.0.1`.
- **Thread safety.** The SLR(1) parser prints its trace to standard output. The server captures it under a lock, so two requests at the same time can't mix their traces.
- **Input limits:** source code up to 20,000 characters and 2 to 16 registers. Programs with infinite loops are stopped by the interpreters' step limits.

### 9.2 What you see

- **Controls:** example picker, LL(1)/SLR(1) switch, register count, Optimize toggle, and a Compile button (Ctrl+Enter).
- **Phase rail:** six numbered modules plus a final ✓ check. Each shows a live count, such as "38 quads · 7 blocks" or "38 → 25 instrs". The failing phase turns red and later phases show "not reached". Click a phase to see its output.
- **Listing views:** the token table, the AST (with the SLR trace), the annotated tree and symbol table, TAC/SSA/quadruples/triples, the optimizer's log, final and unoptimized machine code, DAGs, the storage layout, and the verification table. A "Grammar tables" button shows FIRST/FOLLOW, the LL(1) table and the SLR(1) table.
- **Flow graph drawings:** basic blocks are drawn as boxes, with fall-through edges, forward jumps and dashed loop back-edges. The Optimize view shows the before and after graphs side by side.
- **Look:** the output pane looks like the green-bar printer paper compiler listings used to be printed on. It supports dark mode and phone screens.

### 9.3 Running it

```bash
python3 ui/server.py                  # http://localhost:8000
python3 ui/server.py --port 9000      # another port
python3 ui/server.py --host 0.0.0.0   # reachable from other devices on the network, e.g. for a projector
```

The terminal driver and the UI are independent, so you can use both at the same time.

---

## 10. Command reference

**`main.py`**

| Command | Effect |
|---|---|
| `python3 main.py [file]` | All phases (default file: `examples/03_optimizations.src`) |
| `--parser ll` / `--parser slr` | Choose the parser. `slr` also prints the shift/reduce trace |
| `--upto lex\|parse\|semantic\|icg\|opt\|codegen` | Stop after a phase |
| `--regs N` | Number of machine registers (at least 2; try 2 to see spilling) |
| `--no-opt` | Skip optimization |
| `--tables` | Also print FIRST/FOLLOW, the LL(1) table and the SLR(1) table |
| `--frontend-demo` | The original Module 1–2 demo: both parsers plus the AI explainer |

**Examples**

| File | Shows |
|---|---|
| `01_expressions.src` | Arithmetic and built-in functions |
| `02_control_flow.src` | Boolean operators, if/else, while |
| `03_optimizations.src` | Every optimization at work |
| `04_gcd_primes.src` | Nested loops |
| `05_semantic_errors.src` | Type errors |
| `06_syntax_error.src` | The AI error explainer |

**Environment variables:** `GROQ_API_KEY`, `GEMINI_API_KEY` and `GROQ_MODEL` (optional).

---

## 11. Where to change things

| To… | Edit |
|---|---|
| Add a built-in function | The `FUNC` pattern in `lexer.py`, `BUILTIN_FUNCS` in `semantic.py` and `BUILTINS` in `ops.py` |
| Change what an operator computes | `binop` / `unop` in `ops.py`. All interpreters and the simulator pick it up |
| Add an optimization | A new pass in `optimizer.py`, called from `Optimizer._fixpoint()`. Log each change with `self.note(kind, msg)` |
| Add a machine instruction | `target.py` (instruction set and simulator) and `codegen.py` (when to emit it) |
| Add a peephole pattern | `peephole.py` |
| Change the AI prompt or provider | `ai_error_explainer.py` |
| Add a view to the UI | `compile_view()` in `ui/server.py` (data) and `renderSection()` in `ui/app.js` (drawing) |

After any change, run the tests and the fuzzer. If all stages still agree on hundreds of random programs, the change is very likely correct.

---

## 12. Project history

| Commit | What it added |
|---|---|
| `d440f36` ISE | Modules 1–2: lexer, both parsers, FIRST/FOLLOW and the AI error explainer |
| `128cc4f` | Modules 3–6: semantics, intermediate code, optimization, code generation, verification, tests and fuzzer |
| `fb76f02` | Browser UI, and the Groq model update |

---

## 13. Glossary

- **Token:** the smallest meaningful unit of the program, such as a name, a number or `<=`.
- **AST (abstract syntax tree):** the program's structure as a tree, without punctuation like parentheses and semicolons.
- **FIRST / FOLLOW sets:** the tokens that can start a grammar rule, and the tokens that can come right after it. The LL(1) table is built from these.
- **LL(1) / SLR(1):** top-down parsing with one token of lookahead, and bottom-up shift-reduce parsing with tables built from LR(0) items and FOLLOW sets.
- **S-attributed / L-attributed:** two ways of computing values on the tree. S-attributed uses only values from a node's children; L-attributed may also use values passed down from the parent or from siblings to the left.
- **TAC (three-address code):** instructions with at most one operator, such as `t1 = a * b`.
- **Backpatching:** leaving a jump target blank and filling it in once the target is known.
- **Basic block:** straight-line code with one entry point at the top and one exit point at the bottom.
- **Flow graph:** basic blocks connected by the jumps between them.
- **SSA (static single assignment):** a form where each variable is assigned exactly once. φ-functions merge values where control paths meet.
- **Dominator:** block A dominates block B if every path from the start of the program to B passes through A. Used to find loops and to place φ-functions.
- **Natural loop:** the loop defined by a back edge whose target dominates its source.
- **getReg:** the routine that chooses a register for each value, and spills to memory when none is free.
- **Peephole optimization:** small pattern-based cleanups over a short window of machine instructions.
