"""
grammar.py

The language: assignments, expression statements, print, if/else, while and
blocks, over int / float / bool values.

1. Original Context-Free Grammar (BNF) - Left Recursive  (used by the SLR(1) parser)
-----------------------------------------------------------------------------------
Program    -> StmtList | EPSILON
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
RelExpr    -> Arith RelOp Arith | Arith            (relational ops do not chain)
RelOp      -> LT | LE | GT | GE | EQ | NE
Arith      -> Arith PLUS Term | Arith MINUS Term | Term
Term       -> Term STAR Unary | Term SLASH Unary | Term PERCENT Unary | Unary
Unary      -> MINUS Unary | NOT Unary | Power
Power      -> Primary CARET Power | Primary          (right-associative)
Primary    -> IDENTIFIER | INT | FLOAT | TRUE | FALSE
            | FUNC LPAREN Expr RPAREN | LPAREN Expr RPAREN

Precedence (low -> high): ||, &&, relational, + -, * / %, unary - !, ^

Because every simple statement now ENDS with SEMI (instead of SEMI only
separating statements), a trailing ';' is accepted by both parsers.
Braces are mandatory, so there is no dangling-else ambiguity: ELSE is never
in FOLLOW(IfStmt) and the SLR(1) table has no shift/reduce conflict.


2. Transformed CFG - Left Recursion Eliminated & Left-Factored  (used by the LL(1) parser)
-----------------------------------------------------------------------------------------
Program      -> StmtList
StmtList     -> Stmt StmtList | EPSILON
Stmt         -> IDENTIFIER IdTail SEMI | NonIdUnary ExprTail SEMI
              | PRINT LPAREN Expr RPAREN SEMI | IfStmt | WhileStmt | Block
IdTail       -> ASSIGN Expr | PowerPrime ExprTail
ExprTail     -> TermPrime ArithPrime RelTail AndPrime OrPrime
NonIdUnary   -> MINUS Unary | NOT Unary | NonIdPrimary PowerPrime
Block        -> LBRACE StmtList RBRACE
IfStmt       -> IF LPAREN Expr RPAREN Block ElsePart
ElsePart     -> ELSE ElseTail | EPSILON
ElseTail     -> Block | IfStmt
WhileStmt    -> WHILE LPAREN Expr RPAREN Block
Expr         -> AndExpr OrPrime
OrPrime      -> OR AndExpr OrPrime | EPSILON
AndExpr      -> RelExpr AndPrime
AndPrime     -> AND RelExpr AndPrime | EPSILON
RelExpr      -> Arith RelTail
RelTail      -> RelOp Arith | EPSILON
RelOp        -> LT | LE | GT | GE | EQ | NE
Arith        -> Term ArithPrime
ArithPrime   -> PLUS Term ArithPrime | MINUS Term ArithPrime | EPSILON
Term         -> Unary TermPrime
TermPrime    -> STAR Unary TermPrime | SLASH Unary TermPrime | PERCENT Unary TermPrime | EPSILON
Unary        -> MINUS Unary | NOT Unary | Power
Power        -> Primary PowerPrime
PowerPrime   -> CARET Power | EPSILON
Primary      -> IDENTIFIER | NonIdPrimary
NonIdPrimary -> INT | FLOAT | TRUE | FALSE | FUNC LPAREN Expr RPAREN | LPAREN Expr RPAREN

Left-factoring of statements: both an assignment (x = ...) and an expression
statement (x + 1;) start with IDENTIFIER, so Stmt consumes the IDENTIFIER first
and IdTail decides: ASSIGN means assignment, anything else continues the
expression with the identifier as its left-most operand (PowerPrime ExprTail).
"""


def is_terminal(symbol):
    return symbol.isupper() and symbol != 'EPSILON'


ORIGINAL_GRAMMAR = {
    "Program'": [["Program"]],
    "Program": [["StmtList"], []],              # [] = epsilon: the empty program
    "StmtList": [["StmtList", "Stmt"], ["Stmt"]],
    "Stmt": [["Assignment", "SEMI"], ["Expr", "SEMI"], ["PrintStmt", "SEMI"],
             ["IfStmt"], ["WhileStmt"], ["Block"]],
    "Assignment": [["IDENTIFIER", "ASSIGN", "Expr"]],
    "PrintStmt": [["PRINT", "LPAREN", "Expr", "RPAREN"]],
    "Block": [["LBRACE", "StmtList", "RBRACE"], ["LBRACE", "RBRACE"]],
    "IfStmt": [["IF", "LPAREN", "Expr", "RPAREN", "Block"],
               ["IF", "LPAREN", "Expr", "RPAREN", "Block", "ELSE", "Block"],
               ["IF", "LPAREN", "Expr", "RPAREN", "Block", "ELSE", "IfStmt"]],
    "WhileStmt": [["WHILE", "LPAREN", "Expr", "RPAREN", "Block"]],
    "Expr": [["Expr", "OR", "AndExpr"], ["AndExpr"]],
    "AndExpr": [["AndExpr", "AND", "RelExpr"], ["RelExpr"]],
    "RelExpr": [["Arith", "RelOp", "Arith"], ["Arith"]],
    "RelOp": [["LT"], ["LE"], ["GT"], ["GE"], ["EQ"], ["NE"]],
    "Arith": [["Arith", "PLUS", "Term"], ["Arith", "MINUS", "Term"], ["Term"]],
    "Term": [["Term", "STAR", "Unary"], ["Term", "SLASH", "Unary"], ["Term", "PERCENT", "Unary"], ["Unary"]],
    "Unary": [["MINUS", "Unary"], ["NOT", "Unary"], ["Power"]],
    "Power": [["Primary", "CARET", "Power"], ["Primary"]],
    "Primary": [["IDENTIFIER"], ["INT"], ["FLOAT"], ["TRUE"], ["FALSE"],
                ["FUNC", "LPAREN", "Expr", "RPAREN"], ["LPAREN", "Expr", "RPAREN"]],
}

# Data structure representing the Transformed CFG
TRANSFORMED_GRAMMAR = {
    'Program': [['StmtList']],
    'StmtList': [['Stmt', 'StmtList'], ['EPSILON']],
    'Stmt': [['IDENTIFIER', 'IdTail', 'SEMI'], ['NonIdUnary', 'ExprTail', 'SEMI'],
             ['PRINT', 'LPAREN', 'Expr', 'RPAREN', 'SEMI'], ['IfStmt'], ['WhileStmt'], ['Block']],
    'IdTail': [['ASSIGN', 'Expr'], ['PowerPrime', 'ExprTail']],
    'ExprTail': [['TermPrime', 'ArithPrime', 'RelTail', 'AndPrime', 'OrPrime']],
    'NonIdUnary': [['MINUS', 'Unary'], ['NOT', 'Unary'], ['NonIdPrimary', 'PowerPrime']],
    'Block': [['LBRACE', 'StmtList', 'RBRACE']],
    'IfStmt': [['IF', 'LPAREN', 'Expr', 'RPAREN', 'Block', 'ElsePart']],
    'ElsePart': [['ELSE', 'ElseTail'], ['EPSILON']],
    'ElseTail': [['Block'], ['IfStmt']],
    'WhileStmt': [['WHILE', 'LPAREN', 'Expr', 'RPAREN', 'Block']],
    'Expr': [['AndExpr', 'OrPrime']],
    'OrPrime': [['OR', 'AndExpr', 'OrPrime'], ['EPSILON']],
    'AndExpr': [['RelExpr', 'AndPrime']],
    'AndPrime': [['AND', 'RelExpr', 'AndPrime'], ['EPSILON']],
    'RelExpr': [['Arith', 'RelTail']],
    'RelTail': [['RelOp', 'Arith'], ['EPSILON']],
    'RelOp': [['LT'], ['LE'], ['GT'], ['GE'], ['EQ'], ['NE']],
    'Arith': [['Term', 'ArithPrime']],
    'ArithPrime': [['PLUS', 'Term', 'ArithPrime'], ['MINUS', 'Term', 'ArithPrime'], ['EPSILON']],
    'Term': [['Unary', 'TermPrime']],
    'TermPrime': [['STAR', 'Unary', 'TermPrime'], ['SLASH', 'Unary', 'TermPrime'],
                  ['PERCENT', 'Unary', 'TermPrime'], ['EPSILON']],
    'Unary': [['MINUS', 'Unary'], ['NOT', 'Unary'], ['Power']],
    'Power': [['Primary', 'PowerPrime']],
    'PowerPrime': [['CARET', 'Power'], ['EPSILON']],
    'Primary': [['IDENTIFIER'], ['NonIdPrimary']],
    'NonIdPrimary': [['INT'], ['FLOAT'], ['TRUE'], ['FALSE'],
                     ['FUNC', 'LPAREN', 'Expr', 'RPAREN'], ['LPAREN', 'Expr', 'RPAREN']],
}

RELOP_TOKENS = ('LT', 'LE', 'GT', 'GE', 'EQ', 'NE')


def _first_of_symbol(symbol, first):
    if symbol == 'EPSILON':
        return {'EPSILON'}
    if is_terminal(symbol):
        return {symbol}
    return first[symbol]


def first_of_sequence(seq, first):
    """FIRST of a string of grammar symbols (contains EPSILON if all can vanish)."""
    result = set()
    for sym in seq:
        f = _first_of_symbol(sym, first)
        result |= f - {'EPSILON'}
        if 'EPSILON' not in f:
            return result
    result.add('EPSILON')
    return result


def compute_first(grammar):
    first = {nonterm: set() for nonterm in grammar}
    changed = True
    while changed:
        changed = False
        for nonterm, rules in grammar.items():
            for rule in rules:
                f = first_of_sequence(rule, first)
                if not f <= first[nonterm]:
                    first[nonterm] |= f
                    changed = True
    return first


def compute_follow(grammar, first_sets, start_symbol):
    follow = {nonterm: set() for nonterm in grammar}
    follow[start_symbol].add('EOF')
    changed = True
    while changed:
        changed = False
        for nonterm, rules in grammar.items():
            for rule in rules:
                for i, symbol in enumerate(rule):
                    if is_terminal(symbol) or symbol == 'EPSILON':
                        continue
                    rest = first_of_sequence(rule[i + 1:], first_sets)
                    new = rest - {'EPSILON'}
                    if 'EPSILON' in rest:
                        new |= follow[nonterm]
                    if not new <= follow[symbol]:
                        follow[symbol] |= new
                        changed = True
    return follow


def build_ll1_table(grammar, first_sets, follow_sets):
    """
    Predictive parsing table M[A, a].
    For A -> alpha: add it to M[A, a] for a in FIRST(alpha); if alpha =>* EPSILON,
    also for every a in FOLLOW(A). Returns (table, conflicts).
    """
    table = {nt: {} for nt in grammar}
    conflicts = []
    for nt, rules in grammar.items():
        for rule in rules:
            f = first_of_sequence(rule, first_sets)
            lookaheads = f - {'EPSILON'}
            if 'EPSILON' in f:
                lookaheads |= follow_sets[nt]
            for a in lookaheads:
                if a in table[nt] and table[nt][a] != rule:
                    conflicts.append((nt, a, table[nt][a], rule))
                table[nt][a] = rule
    return table, conflicts


# Compute globally to be imported by parser
FIRST_SETS = compute_first(TRANSFORMED_GRAMMAR)
FOLLOW_SETS = compute_follow(TRANSFORMED_GRAMMAR, FIRST_SETS, 'Program')
LL1_TABLE, LL1_CONFLICTS = build_ll1_table(TRANSFORMED_GRAMMAR, FIRST_SETS, FOLLOW_SETS)


def print_sets_table():
    print(f"{'Non-Terminal':<14} | {'FIRST Set':<60} | {'FOLLOW Set'}")
    print("-" * 140)
    for nt in TRANSFORMED_GRAMMAR:
        f_str = ", ".join(sorted(FIRST_SETS[nt]))
        fol_str = ", ".join(sorted(FOLLOW_SETS[nt]))
        print(f"{nt:<14} | {f_str:<60} | {fol_str}")


def print_ll1_table():
    print("LL(1) predictive parsing table  M[NonTerminal, lookahead] = production")
    for nt in TRANSFORMED_GRAMMAR:
        for a in sorted(LL1_TABLE[nt]):
            print(f"  M[{nt}, {a}] = {nt} -> {' '.join(LL1_TABLE[nt][a])}")
    if LL1_CONFLICTS:
        print("CONFLICTS (grammar is NOT LL(1)):")
        for c in LL1_CONFLICTS:
            print("  ", c)
    else:
        print("No conflicts: the transformed grammar is LL(1).")


if __name__ == "__main__":
    print("Grammar Sets (Left-Factored, No Left-Recursion):")
    print_sets_table()
    print()
    print_ll1_table()
