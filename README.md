# Custom Arithmetic Expression Compiler Front-End

This project implements a compiler front-end (Lexical Analysis and Syntax Analysis) for a custom arithmetic expression language in pure Python. It covers Compiler Design Modules 1 & 2 (no semantic analysis, IR generation, optimization, or code generation).

## Project Structure

*   `lexer.py`: Regex-based lexical analyzer. Tracks line/column info and generates standard tokens.
*   `grammar.py`: Defines the CFG, computes FIRST and FOLLOW sets, and documents both the original left-recursive grammar and the transformed grammar.
*   `parser_recursive_descent.py`: A predictive LL(1) top-down parser returning an AST.
*   `parser_bottom_up.py`: A full SLR(1) bottom-up parser building LR(0) state machines and tables from the original CFG, printing step-by-step trace information.
*   `ai_error_explainer.py`: A Groq API integration (with Gemini fallback) translating rigid parser errors into human-readable explanations.
*   `main.py`: The main CLI driving testing across both parsers.

## Grammar Design

The original Context-Free Grammar (CFG) supports standard operator precedence, unary minus, and right-associative exponentiation:

```bnf
Program -> StmtList
StmtList -> StmtList SEMI Stmt | Stmt
Stmt -> Assignment | Expr
Assignment -> IDENTIFIER ASSIGN Expr
Expr -> Expr PLUS Term | Expr MINUS Term | Term
Term -> Term STAR Unary | Term SLASH Unary | Term PERCENT Unary | Unary
Unary -> MINUS Unary | Power
Power -> Primary CARET Power | Primary
Primary -> IDENTIFIER | INT | FLOAT | FUNC LPAREN Expr RPAREN | LPAREN Expr RPAREN
```

## Left-Recursion Elimination & Left-Factoring

To support the LL(1) recursive descent parser, the grammar was transformed to remove left recursion (e.g., in `Expr` and `Term`) and left-factored (e.g., separating an `IDENTIFIER` starting an assignment from an `IDENTIFIER` in a math expression). 
*The precise transformed CFG can be found in the docstring of `grammar.py`.*

## AI Error Explainer Constraint

The compiler integrates with the Groq API (fallback to Gemini API) to explain syntax errors. 

**Why the AI feature doesn't replace the compiler:** The AI strictly acts as a translation layer. It *does not parse or compile* the code. It relies 100% on the hand-written parser detecting the invalid state, and takes the `SyntaxErrorInfo` (containing the exact offending token and the expected valid tokens computed from the FIRST/FOLLOW sets) and translates it into beginner-friendly English with a 1-line fix. 

## Running the Compiler

Run the main CLI demonstration to see the lexer, parsers, and error explainer in action.

```bash
export GROQ_API_KEY="your-groq-api-key"
export GEMINI_API_KEY="your-gemini-api-key"
python3 main.py
```
