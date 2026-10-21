# Compiler_ISE: A Six-Phase Compiler in Pure Python

A complete compiler for a small language with int, float and bool values, arithmetic, `if/else`, `while` and `print`. It covers all six modules of the Compiler Design syllabus, using only the Python standard library:

| Module | What is implemented | Files |
|---|---|---|
| 1 Lexical analysis | Regex scanner with keywords, longest-match operators, line/column tracking | `lexer.py` |
| 2 Syntax analysis | FIRST/FOLLOW, LL(1) table, recursive-descent LL(1) parser, SLR(1) parser (LR(0) items, ACTION/GOTO), AI error explainer | `grammar.py`, `parser_recursive_descent.py`, `parser_bottom_up.py`, `ai_error_explainer.py` |
| 3 SDT & run-time environments | S-attributed (SLR) and L-attributed (LL) AST construction, type checking with coercions, hash-table symbol table (hashpjw), static storage layout, activation records | `ast_nodes.py`, `semantic.py`, `runtime.py` |
| 4 Intermediate code | Three-address code with backpatching for booleans/if/while, quadruples, triples, indirect triples, basic blocks, flow graph, SSA form | `icg.py`, `cfg.py`, `ssa.py` |
| 5 Code optimization | Constant folding/propagation (local + global), copy propagation, CSE, algebraic simplification, strength reduction, dead-code and unreachable-code elimination, jump optimizations, natural loops, loop-invariant code motion | `optimizer.py`, `dag.py` |
| 6 Code generation | Register machine, getReg with register/address descriptors, DAGs, peephole optimization, machine simulator | `codegen.py`, `peephole.py`, `target.py` |

Every run ends with a **verification** step. The program is executed as an AST, as TAC, in SSA form, as optimized TAC, and as machine code before and after peephole optimization, and all of them must produce the same output and the same final variable values.

## The language

```c
n = 10; i = 0; sum = 0;               // variables are declared (and typed) by their first assignment
while (i < n && !(i == 7)) {
    if (i % 2 == 0 || i > 8) { sum = sum + i * 2; } else { sum = sum - 1; }
    i = i + 1;
}
avg = sum / 2.5 + sqrt(n);            // int is coerced to float where needed
ok = sum > 5 && avg != 0;
print(sum); print(avg); print(ok);
```

Operators from lowest to highest precedence: `||`, `&&`, `< <= > >= == !=`, `+ -`, `* / %`, unary `- !`, `^` (right-associative). The built-in functions are `sin`, `cos`, `log` and `sqrt`.

## Grammar

The original (left-recursive) grammar is used by the SLR(1) parser:

```bnf
Program    -> StmtList | ε
StmtList   -> StmtList Stmt | Stmt
Stmt       -> Assignment SEMI | Expr SEMI | PrintStmt SEMI | IfStmt | WhileStmt | Block
Assignment -> IDENTIFIER ASSIGN Expr
PrintStmt  -> PRINT LPAREN Expr RPAREN
Block      -> LBRACE StmtList RBRACE | LBRACE RBRACE
IfStmt     -> IF LPAREN Expr RPAREN Block
            | IF LPAREN Expr RPAREN Block ELSE Block
            | IF LPAREN Expr RPAREN Block ELSE IfStmt
WhileStmt  -> WHILE LPAREN Expr RPAREN Block
Expr       -> Expr OR AndExpr | AndExpr
AndExpr    -> AndExpr AND RelExpr | RelExpr
RelExpr    -> Arith RelOp Arith | Arith
Arith      -> Arith PLUS Term | Arith MINUS Term | Term
Term       -> Term STAR Unary | Term SLASH Unary | Term PERCENT Unary | Unary
Unary      -> MINUS Unary | NOT Unary | Power
Power      -> Primary CARET Power | Primary
Primary    -> IDENTIFIER | INT | FLOAT | TRUE | FALSE | FUNC LPAREN Expr RPAREN | LPAREN Expr RPAREN
```

The left-recursion-free, left-factored version used by the LL(1) parser is in the docstring of `grammar.py`. Both grammars are checked for conflicts automatically: the LL(1) table has none, and the SLR(1) table has 85 states and no conflicts. Simple statements end with `;`, so a trailing semicolon is valid for both parsers.

## Running

```bash
python3 main.py                              # all phases on examples/03_optimizations.src
python3 main.py examples/04_gcd_primes.src   # any source file
python3 main.py prog.src --parser slr        # use the SLR(1) parser and print its trace
python3 main.py prog.src --tables            # FIRST/FOLLOW sets, LL(1) table, SLR(1) table
python3 main.py prog.src --upto icg          # stop after: lex | parse | semantic | icg | opt | codegen
python3 main.py prog.src --regs 2            # number of registers (watch spilling)
python3 main.py prog.src --no-opt            # skip optimization
python3 main.py --frontend-demo              # original Module 1-2 demo (both parsers + AI explainer)
```

Example programs in `examples/`:

| File | Shows |
|---|---|
| `01_expressions.src` | Arithmetic and built-in functions |
| `02_control_flow.src` | Boolean operators, if/else, while |
| `03_optimizations.src` | Every optimization at work |
| `04_gcd_primes.src` | Nested loops |
| `05_semantic_errors.src` | Type errors |
| `06_syntax_error.src` | The AI error explainer |

To enable the AI error explainer, set at least one API key. Without them the raw parser error is shown instead.

```bash
export GROQ_API_KEY="your-groq-api-key"
export GEMINI_API_KEY="your-gemini-api-key"
export GROQ_MODEL="openai/gpt-oss-20b"       # optional: Groq model to use (this is the default)
```

## Web UI

```bash
python3 ui/server.py                         # then open http://localhost:8000
python3 ui/server.py --port 9000             # another port
python3 ui/server.py --host 0.0.0.0          # reachable from other devices, e.g. a projector laptop
```

The UI runs the same compiler modules as `main.py`, using only the Python standard library. It has an editor with the example programs, an LL(1)/SLR(1) switch, a register count and an optimization toggle. A rail across the top shows the six phases plus verification. Each phase shows a live count, and the phase that fails is marked in red. Select a phase to see its output: the token table, AST, symbol table, three-address code, flow graphs drawn before and after optimization, SSA, target code, peephole results and the stage-by-stage verification. Errors are marked on their lines in the editor. For a syntax error, the AI explainer's answer appears under the parser's own error and expected tokens. Set the API keys in the same terminal before starting the server; they stay on the server and are never sent to the browser.

## AI error explainer constraint

The AI does **not** parse or compile anything. The hand-written parser detects the error and computes the expected tokens from its FIRST/FOLLOW-based tables. The LLM only translates that exact `SyntaxErrorInfo` into beginner-friendly English with a one-line fix.

## Tests

```bash
python3 -m unittest discover tests     # unit + end-to-end tests
python3 tests/fuzz.py 500              # 500 random programs through every phase, both parsers, 2-4 registers
```

See `explain.md` for a detailed, viva-oriented explanation of every phase.
