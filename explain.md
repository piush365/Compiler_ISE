# Compiler for a Small Language: In-Depth Explanation

This document explains the whole compiler, all six phases, module by module, with the concepts behind each piece of code. It is written to prepare you for a viva: every section says **what** the phase does, **how** the code does it, and **why** it is designed that way.

## 1. Project Overview

The project is a complete compiler, written in pure Python with no compiler-construction libraries, for a small language with integers, floats, booleans, arithmetic, `if/else`, `while` and `print`.

| Syllabus module | Phase | Files |
|---|---|---|
| 1 Fundamentals, lexical analysis | Scanner | `lexer.py` |
| 2 Syntax analysis | LL(1) and SLR(1) parsers | `grammar.py`, `parser_recursive_descent.py`, `parser_bottom_up.py`, `ai_error_explainer.py` |
| 3 Syntax-directed translation & run-time environments | Type checking, symbol table, storage | `ast_nodes.py`, `semantic.py`, `runtime.py` |
| 4 Intermediate code generation | Three-address code, backpatching, quadruples/triples, flow graphs, SSA | `icg.py`, `cfg.py`, `ssa.py` |
| 5 Code optimization | Local, global and loop optimization | `optimizer.py`, `dag.py` |
| 6 Code generation | getReg code generator, peephole, target machine | `codegen.py`, `peephole.py`, `target.py` |
| Verification | Executes every stage and compares | `interpreter.py`, `ops.py`, `compiler.py`, `tests/` |

The compiler is a **multi-pass** compiler: each phase reads the complete output of the previous one (tokens → AST → TAC → flow graph → target code). A one-pass compiler would generate code while parsing; that is faster but makes optimization impossible, because the optimizer needs to see the whole program.

## 2. The Language

```c
// comments start with //
n = 10;                       // variables are declared by their first assignment
avg = 0.0;                    // the first assignment also fixes the type: int, float or bool
i = 0;
while (i < n && !(i == 7)) {  // && || !  and  < <= > >= == !=
    if (i % 2 == 0) { print(i); } else if (i > 8) { avg = avg + 1; } else { }
    i = i + 1;
}
x = 2 ^ 3 ^ 2;                // ^ is power, right-associative: 2 ^ 9 = 512
y = sqrt(2) + sin(x);         // built-ins: sin cos log sqrt  (they return float)
```

Precedence from low to high: `||`, `&&`, relational, `+ -`, `* / %`, unary `- !`, `^`. Integer `/` truncates toward zero and `%` takes the sign of the dividend, as in C. Braces are compulsory, so there is no dangling-else problem.

## 3. How to Run It

```bash
python3 main.py                              # all phases on examples/03_optimizations.src
python3 main.py examples/04_gcd_primes.src   # any program
python3 main.py prog.src --parser slr        # SLR(1) parser with shift/reduce trace
python3 main.py prog.src --tables            # FIRST/FOLLOW, LL(1) table, SLR(1) table
python3 main.py prog.src --upto icg          # stop after a phase (lex, parse, semantic, icg, opt, codegen)
python3 main.py prog.src --regs 2            # fewer registers -> watch spilling
python3 main.py prog.src --no-opt            # code generation straight from unoptimized TAC
python3 main.py --frontend-demo              # the original Module 1-2 demo
python3 -m unittest discover tests           # the test suite
python3 tests/fuzz.py 500                    # 500 random programs through every phase
```

The AI error explainer needs `GROQ_API_KEY` or `GEMINI_API_KEY`; without them it prints the raw error instead.

---

## 4. Module 1: Lexical Analysis (`lexer.py`)

The lexer turns characters into **tokens**. Each token type is a regular expression; all of them are joined into one big alternation with named groups, and `finditer` walks the input. Each token records its type, text, line and column.

Two ordering rules matter, because the regex engine takes the **first** alternative that matches:

* Keywords (`if`, `while`, …) come before `IDENTIFIER`. The keyword patterns use `\b`, so `iffy` is not split into `if` + `fy`: `\bif\b` fails and `IDENTIFIER` matches the whole word.
* Two-character operators (`==`, `<=`, `!=`, `&&`, `||`) come before their one-character prefixes (`=`, `<`, `!`). This is the **longest match** rule.

Whitespace and comments are matched and thrown away. Any other character is a lexical error, reported with its position.

## 5. Module 2: Syntax Analysis

### 5.1 Grammars (`grammar.py`)

`grammar.py` contains **two** grammars for the same language.

1. **The original grammar** is left-recursive (`Arith -> Arith PLUS Term`). Left recursion naturally expresses left associativity, and precedence comes from the chain of non-terminals `Expr → AndExpr → RelExpr → Arith → Term → Unary → Power → Primary`. This grammar is used by the SLR(1) parser.
2. **The transformed grammar** has left recursion eliminated (`Arith -> Term ArithPrime`, `ArithPrime -> PLUS Term ArithPrime | ε`) and is left-factored. An assignment `x = …` and an expression statement `x + 1;` both start with `IDENTIFIER`, so `Stmt -> IDENTIFIER IdTail SEMI` reads the identifier first and `IdTail` decides. This grammar is used by the LL(1) parser.

The file computes **FIRST** and **FOLLOW** sets by fixed-point iteration and then builds the **LL(1) predictive parsing table**. For each production `A → α`, the production is entered in `M[A, a]` for every `a` in FIRST(α), and also for every `a` in FOLLOW(A) if α can derive ε. If any cell receives two productions, the grammar is not LL(1). The code checks this and finds no conflicts (`python3 grammar.py` prints the table).

Every simple statement now **ends** in `;`. The first version used `;` only as a separator, which made the SLR(1) parser reject a trailing semicolon (`x = 1;` failed with "Unexpected token EOF"). That bug is fixed and covered by a test.

### 5.2 LL(1) recursive descent parser (`parser_recursive_descent.py`)

There is one function per non-terminal. Each function looks at the current token (one token of lookahead) and uses the FIRST sets to choose a production without backtracking. On error it raises `SyntaxErrorExt`, which records the unexpected token and the set of tokens that would have been valid.

### 5.3 SLR(1) shift-reduce parser (`parser_bottom_up.py`)

The parser builds the canonical collection of **LR(0) items** with `closure` and `goto`. From it, it builds the **ACTION/GOTO** tables: shift on terminals after the dot, reduce `A → α` on FOLLOW(A), and accept on EOF. A cell with two different entries is a conflict. The grammar gives 85 states and no conflicts.

The parser runs a stack of states. It now also keeps a **value stack**, so it builds the same AST as the LL(1) parser (see Module 3). The tests check that both parsers produce identical trees.

### 5.4 AI error explainer (`ai_error_explainer.py`)

The AI does **not** parse. The hand-written parser detects the error and computes the expected tokens from its tables. The LLM (Groq, with Gemini as a fallback) only turns that exact information into plain English and a one-line fix. The compiler therefore stays deterministic, and the AI is purely a presentation layer.

---

## 6. Module 3: Syntax-Directed Translation and Run-Time Environments

### 6.1 Syntax-directed definitions: S-attributed vs L-attributed

An SDD attaches **attributes** to grammar symbols and **semantic rules** to productions.

* A **synthesized** attribute of a node is computed from its children. An SDD that uses only synthesized attributes is **S-attributed**. It can be evaluated bottom-up, in exactly the order an LR parser reduces.
* An **inherited** attribute of a node comes from its parent or its left siblings. An SDD is **L-attributed** if inherited attributes depend only on the parent and on siblings to the left. It can be evaluated in one left-to-right depth-first pass, which is exactly what a recursive descent parser does.

This project uses **both**, to build the same syntax tree:

* **SLR(1) parser: S-attributed.** `semantic_action()` runs at every reduction. For `Arith → Arith PLUS Term` the rule is `Arith.node = new BinOp(Arith1.node, '+', Term.node)`, computed from the values popped off the value stack.
* **LL(1) parser: L-attributed.** In `ArithPrime → PLUS Term ArithPrime1`, the tree built so far (`left_node`) is passed **down** into `parse_arith_prime(left_node)`; that is the inherited attribute `ArithPrime.inh`. The function builds `BinOp(left_node, '+', term)` and passes it down again, and the finished tree comes back up as the synthesized attribute. This is the standard trick for building a left-associative tree from a grammar without left recursion.

### 6.2 Construction of the syntax tree (`ast_nodes.py`)

The tree nodes are `Num`, `Bool`, `Var`, `BinOp`, `UnaryOp`, `FuncCall`, `Assign`, `Print`, `Block`, `If` and `While`. The tree omits everything that only guides parsing (parentheses, semicolons, the chain of non-terminals), which makes it much smaller than a parse tree.

### 6.3 Type checking (`semantic.py`)

The analyzer walks the tree in **post-order**, so children are evaluated before parents, and attaches a synthesized attribute `ty` to every expression. The rules are listed at the top of `semantic.py`; for example, `E1 + E2` is `float` if either operand is float, otherwise `int`. `main.py` prints the evaluation order as the "attribute evaluation order" trace.

An **inherited** attribute also appears: in `x = E` with `x` already a float, the declared type of `x` flows down to `E`. If `E` is int, an int→float **coercion** is inserted later, in the TAC.

The analyzer reports these errors, all collected rather than stopping at the first:

* a variable used before any assignment;
* arithmetic on bools, or `&&`/`||`/`!` on numbers;
* `%` with float operands;
* an `if`/`while` condition that is not bool;
* assigning a float to an int variable (possible loss of precision) or mixing bool and numeric types.

### 6.4 Symbol table organization

The symbol table is a **hash table with separate chaining**:

* The table has 211 buckets, a prime, as the Dragon book recommends.
* The hash function is **hashpjw** (P. J. Weinberger's), from the Dragon book: shift left 4, add the character, and fold the top 4 bits back in.
* Each bucket is a list (a chain), and new symbols are inserted at the head. When two names hash to the same bucket, the printout shows the collision chain (for example `bucket 98: unused -> b`).
* Each entry records the name, kind (variable or function), type, declaration line, the lines where it is used, the storage offset and the width.
* Built-in functions are pre-loaded as `function` entries of type `float -> float`.

Alternatives you can mention: a linear list gives O(n) lookup; a search tree gives O(log n); a hash table gives O(1) on average. A language with nested scopes would use a stack of tables, one per scope; this language has a single global scope.

### 6.5 Storage organization and allocation (`runtime.py`)

```
Code | Static data | Temporaries | Heap → ... ← Stack
```

* **Static allocation**: every variable gets a fixed offset when it is entered in the symbol table. Widths are int 4, float 8 and bool 1, and each offset is aligned to the variable's own width (`a = true; b = 1.5;` puts `b` at offset 8, not 1).
* **Stack allocation**: each call of a built-in function pushes an **activation record** with these fields: actual parameter | returned value | control link | return address. The target-machine simulator really builds and pops these records, and reports the number of calls and the maximum stack depth.
* **Parameter passing** is **call by value**: `PUSH` copies the value. You can contrast it with call by reference (pass the address), call by value-result (copy in, copy out) and call by name.
* **Dynamic storage (heap)** is not needed, because the language has no pointers, arrays or objects.

---

## 7. Module 4: Intermediate Code Generation (`icg.py`, `cfg.py`, `ssa.py`)

### 7.1 Three-address code

Each instruction has at most one operator on the right-hand side: `x = y op z`, `x = op y`, `x = y`, `if x relop y goto L`, `if x goto L`, `goto L`, `param x`, `x = call f, n`, `print x` and `halt`. Temporaries `t1, t2, …` hold intermediate values. Mixed int/float arithmetic gets an explicit `t = inttofloat x`.

### 7.2 Boolean expressions and flow of control with backpatching

Boolean expressions are translated as **jumping code**: `a < b || c` does not compute a true/false value, it jumps to the "true" or "false" place, and this gives short-circuit evaluation for free. The problem is that while generating `if a < b goto _`, the target is not known yet. **Backpatching** solves it: the jump is emitted with an empty target, and its index is put on a list (`truelist`, `falselist`, `nextlist`). When the target becomes known, `backpatch(list, target)` fills in every jump on the list. The exact rules are in the docstring of `icg.py`. Example:

```
if (a < b || c) { x = 1; }          3: if a < b goto 7     B1.truelist  = [3]
                                    4: goto 5              B1.falselist = [4] → patched to 5
                                    5: if c goto 7         B2.truelist  = [5]
                                    6: goto 8              B2.falselist = [6] = S.nextlist
                                    7: x = 1               truelist [3, 5] patched to 7
                                    8: halt
```

When a boolean is needed as a **value** (`ok = a < b;`), the jumping code is followed by `t = true; goto next; t = false`.

### 7.3 Quadruples, triples and indirect triples

* **Quadruples** `(op, arg1, arg2, result)` are what the compiler stores and uses.
* **Triples** `(op, arg1, arg2)` have no result field: a temporary is referred to by the number of the triple that computes it, `(k)`. They save space, but moving an instruction changes the numbers of every reference to it.
* **Indirect triples** add a separate list of pointers that gives the execution order. An optimizer can then reorder statements by reordering the pointer list, without renumbering the triples.

`main.py` prints all three, plus the plain TAC listing.

### 7.4 Basic blocks and flow graphs (`cfg.py`)

**Leaders** are the first instruction, every jump target, and every instruction that follows a jump. A **basic block** runs from a leader up to the next leader; control enters only at the top and leaves only at the bottom. The **flow graph** has an edge B → C if C can execute right after B. Jump targets become block labels (`B3`). The file also contains **dominators** (iterative data flow), **natural loops** (from back edges n → h, where h dominates n) and **liveness analysis**.

### 7.5 SSA form (`ssa.py`)

In Static Single Assignment form every name is assigned exactly once (`i_1`, `i_2`, …). Where paths join, a φ-function selects the version from the predecessor that actually ran: `i_2 = phi(B1: i_1, B12: i_3)`. The construction follows Cytron et al.:

1. Compute the dominator tree.
2. Compute dominance frontiers.
3. Place φ-functions at the iterated dominance frontier of the blocks that define a variable. This is "semi-pruned" SSA: only names that live across blocks get φs.
4. Rename the variables while walking the dominator tree.

SSA makes every use point to exactly one definition, which makes constant propagation, dead-code elimination and value numbering much simpler. The SSA code is also **executed** (`run_ssa`) to prove it is equivalent.

---

## 8. Module 5: Code Optimization (`optimizer.py`)

All optimizations are **machine-independent** and work on the flow graph. They repeat until nothing changes, because one optimization often creates work for another: folding a constant can make a branch constant, which makes a block unreachable.

### 8.1 Optimization of basic blocks (local)

The local pass walks each block once, keeping maps of known constants, copies and available expressions:

| Transformation | Before | After |
|---|---|---|
| Constant folding | `t = 4 * 2` | `t = 8` |
| Constant propagation | `a = 4; t = a * 2` | `t = 4 * 2` |
| Copy propagation | `k = t8; x = k + 1` | `x = t8 + 1` |
| Algebraic simplification | `x + 0`, `x * 1`, `x / 1`, `x ^ 1` | `x` |
| Strength reduction | `x * 2`, `x ^ 2` (int) | `x + x`, `x * x` |
| Common sub-expression elimination | `t9 = i * c; t10 = i * c` | `t10 = t9` |
| Copy coalescing | `t = a + b; x = t` | `x = a + b` |

CSE is done by **local value numbering**, which is the hashing form of building the block's **DAG** (`dag.py` prints the DAGs, and a node shared by two parents is a common sub-expression). A redefinition of a variable kills every fact that mentions it.

Two safety rules: `x + 0 → x` is applied only to ints, because for a float `-0.0 + 0` is `0.0`, not `-0.0`; and `!(a < b) → a >= b` is applied only to ints, because a NaN is neither less than nor greater-or-equal.

### 8.2 Global optimization (data-flow analysis)

* **Global constant propagation**: a forward analysis. in[B] is the meet of out[P] over all predecessors P (a variable stays a constant only if every predecessor agrees), and out[B] = transfer(B, in[B]). It iterates to a fixed point.
* **Dead-code elimination**: a backward **live-variable analysis**, with out[B] = ∪ in[S] and in[B] = use[B] ∪ (out[B] − def[B]). An assignment to a name that is not live afterwards is removed. Every user variable is treated as live at the end of the program, because its final value is observable.
* **Unreachable-code elimination**: blocks that cannot be reached from the entry are removed (for example the body of `if (false)`).
* **Flow-of-control optimizations**: removing a jump to the next block, **jump threading** (a jump to a block that only says `goto L` jumps straight to L), **jumps over jumps** (`if c goto L1; goto L2; L1:` becomes `if !c goto L2`), and merging straight-line blocks.

### 8.3 Loops in flow graphs and loop optimization

1. Compute dominators. A **back edge** is n → h where h dominates n, and h is the loop **header**.
2. The **natural loop** of the back edge is h plus every block that can reach n without passing through h.
3. **Loop-invariant code motion**: an instruction `t = a op b` is invariant if every operand is a constant, is not assigned inside the loop, or is itself invariant. Such instructions move into a new **pre-header** block placed before the header, so they run once instead of once per iteration. Every jump into the header from outside the loop is redirected to the pre-header.
4. **Safety**: an operation that can fail at run time (`/` or `%` by a non-constant, `^`) is moved only if its block dominates every loop exit, so it would have run anyway. A loop that runs zero times must not start dividing by zero.
5. **Basic induction variables** (`i = i + c`, assigned once per iteration) are detected and reported. They are the starting point for induction-variable strength reduction.

Example from `examples/03_optimizations.src`: `k = (x * 3.0 + 1.5) / 2.0` inside the loop becomes three instructions in the pre-header, because `x` never changes in the loop.

---

## 9. Module 6: Code Generation (`codegen.py`, `peephole.py`, `target.py`)

### 9.1 Target machine

`target.py` defines a load/store register machine in Dragon-book style: `LD`, `ST`, `MOV`, `ADD/SUB/MUL/DIV/MOD/POW` (the second source may be an immediate `#c`), `NEG`, `NOT`, `ITOF`, `INC/DEC`, branches `BR`, `BLT`…`BNE`, `BNZ`/`BZ`, `PUSH`/`CALL`, `PRINT` and `HALT`. `run_machine()` is a simulator for this machine.

### 9.2 Issues in the design of a code generator

These are the classic issues, and how this compiler handles each:

* **Input**: optimized TAC organized as a flow graph.
* **Target program**: assembly-like code for a register machine.
* **Instruction selection**: a constant second operand becomes an immediate, so `i = i + 1` becomes `ADD R1, R1, #1` with no extra load. The peephole pass then picks the machine idiom `INC R1`.
* **Register allocation and assignment**: getReg, described below.
* **Evaluation order**: the TAC order is kept. The DAG shows which reorderings would be legal.

### 9.3 Simple code generator with register and address descriptors

Code is generated one basic block at a time:

* The **register descriptor** records which names each register currently holds.
* The **address descriptor** records, for each name, where its current value is: memory and/or registers.
* **Next-use information** comes from global liveness, and tells the generator which values will be needed after each instruction.

For `x = y op z`:

1. `getReg` finds a register for `y`. Preference order: a register already holding `y`, then an empty register, then a register whose values are all *safe* to lose (stored elsewhere, or dead, or the name being overwritten), and finally the register needing the fewest **spill stores** (`ST`).
2. If `z` is a constant it becomes an immediate; otherwise it goes in a second register.
3. If `y` dies here, its register is reused for `x`; otherwise getReg chooses one.
4. The generator emits `OP Rx, Ry, Rz` and updates both descriptors: Rx holds only x, and x is only in Rx.

A copy `x = y` generates **no instruction at all**: x is simply added to the register descriptor of the register holding y.

At the end of every block, each live name whose value exists only in a register is stored. This is why every block can start with "everything is in memory". The `--regs` option lets you watch spilling happen with only 2 registers.

### 9.4 DAG representation (`dag.py`)

For each block, `x = y op z` attaches `x` to the node `op(node(y), node(z))`, reusing an existing node if one is found (a common sub-expression). Leaves such as `i_0` are the values names have on entry to the block, and the identifiers attached to a node are the names holding that value at the end of the block.

### 9.5 Peephole optimization (`peephole.py`)

A small window slides over the target code and applies these patterns:

* redundant load after store (`ST x, R0; LD R0, x`) and redundant store after load;
* `MOV R, R`;
* algebraic identities (`MUL R, R, #1`);
* machine idioms (`ADD R, R, #1` → `INC R`);
* a jump to the next instruction;
* **jump chaining** (`BR L1` where `L1: BR L2` becomes `BR L2`);
* unreachable code after `BR`/`HALT`;
* unused labels.

The pass repeats until no pattern matches.

### 9.6 Syllabus topics covered in theory only

* **Parallel compilation**: compiling independent units (files, functions) on several cores, and running pipeline phases concurrently.
* **JIT compilation**: compiling at run time, often only the "hot" code, as in the JVM HotSpot or V8. Our simulator is the opposite approach: an ahead-of-time compiler followed by an interpreter of the machine code.
* **Compiler construction tools**: scanner generators (Lex/Flex), parser generators (Yacc/Bison, ANTLR), syntax-directed translation engines, data-flow analysis engines and code-generator generators. This project builds all of these by hand on purpose.

---

## 10. How Correctness Is Verified

`ops.py` defines what every operator means, in exactly one place. Using those definitions, the program is **executed at every level**: the AST interpreter, the TAC interpreter, the SSA interpreter (with φ-functions), the optimized flow graph, and the target-machine simulator before and after peephole optimization. Their printed output and final variable values must be identical, and `main.py` ends every run with this check.

`tests/fuzz.py` generates random well-typed programs (nested ifs, loops, mixed types, function calls) and runs each one through both parsers, with and without optimization, and with 2, 3 and 4 registers. More than 2,500 random programs have passed. The fuzzer found and fixed two real bugs during development: φ-functions missing for variables that are only read at program exit, and uninitialized float variables starting as integer 0.

---

## 11. Summary for the Viva

1. **Scope**: a complete six-phase compiler in pure Python: lexer, two parsers, type checker with symbol table, three-address code with backpatching, optimizer, and register-allocating code generator for a simulated machine.
2. **Theory made concrete**: FIRST/FOLLOW, an LL(1) table, SLR(1) item sets, S- and L-attributed SDDs, hashpjw, activation records, backpatching, triples, SSA with dominance frontiers, data-flow analysis, natural loops, getReg with descriptors, DAGs and peephole patterns.
3. **Correctness**: every phase is checked by actually running its output; the grammar and parser tables are checked for conflicts; and random testing compares all stages.
4. **AI integration**: the LLM only translates the parser's exact error state into plain English and never parses.

### Likely viva questions

* *Why two parsers?* To show top-down vs bottom-up parsing. LL(1) needs a grammar without left recursion; SLR(1) handles the natural left-recursive grammar. Both build the same AST, one with an L-attributed SDD and one with an S-attributed SDD.
* *What is backpatching and why is it needed?* It fills in jump targets that are unknown when the jump is emitted, so the code can be generated in a single pass.
* *Difference between quadruples and triples?* Triples have no result field and refer to results by position, so they are smaller but hard to reorder. Indirect triples fix the reordering problem.
* *When is an expression loop-invariant, and when is moving it unsafe?* It is invariant when all its operands are constants, defined outside the loop, or themselves invariant. Moving it is unsafe if it can fault and might not have executed in the original program.
* *What does getReg do when no register is free?* It picks the register whose values can be lost most cheaply and stores (spills) the live values that exist only there.
* *Why store live variables at the end of each block?* So that every block can assume all values start in memory, which keeps per-block register allocation correct whichever path reached the block.
* *Why is `x + 0 → x` not applied to floats?* Because `-0.0 + 0` is `+0.0`, so the result would differ.
