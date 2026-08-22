"""
grammar.py

1. Original Context-Free Grammar (BNF) - Left Recursive
-------------------------------------------------------
Program -> StmtList
StmtList -> StmtList SEMI Stmt | Stmt
Stmt -> Assignment | Expr
Assignment -> IDENTIFIER ASSIGN Expr
Expr -> Expr PLUS Term | Expr MINUS Term | Term
Term -> Term STAR Unary | Term SLASH Unary | Term PERCENT Unary | Unary
Unary -> MINUS Unary | Power
Power -> Primary CARET Power | Primary
Primary -> IDENTIFIER | INT | FLOAT | FUNC LPAREN Expr RPAREN | LPAREN Expr RPAREN


2. Transformed CFG - Left Recursion Eliminated & Left-Factored
--------------------------------------------------------------
Program -> Stmt StmtListPrime
StmtListPrime -> SEMI Stmt StmtListPrime | EPSILON

Stmt -> IDENTIFIER IdTail | NonIdExpr
IdTail -> ASSIGN Expr | PowerPrime TermPrime ExprPrime

NonIdExpr -> NonIdPrimary PowerPrime TermPrime ExprPrime | MINUS Unary TermPrime ExprPrime
NonIdPrimary -> INT | FLOAT | FUNC LPAREN Expr RPAREN | LPAREN Expr RPAREN

Expr -> IDENTIFIER PowerPrime TermPrime ExprPrime | NonIdExpr

ExprPrime -> PLUS Term ExprPrime | MINUS Term ExprPrime | EPSILON
Term -> Unary TermPrime
TermPrime -> STAR Unary TermPrime | SLASH Unary TermPrime | PERCENT Unary TermPrime | EPSILON
Unary -> MINUS Unary | Power
Power -> Primary PowerPrime
PowerPrime -> CARET Power | EPSILON
Primary -> IDENTIFIER | NonIdPrimary
"""

def is_terminal(symbol):
    return symbol.isupper() and symbol != 'EPSILON'

# Data structure representing the Transformed CFG
TRANSFORMED_GRAMMAR = {
    'Program': [['Stmt', 'StmtListPrime']],
    'StmtListPrime': [['SEMI', 'Stmt', 'StmtListPrime'], ['EPSILON']],
    'Stmt': [['IDENTIFIER', 'IdTail'], ['NonIdExpr']],
    'IdTail': [['ASSIGN', 'Expr'], ['PowerPrime', 'TermPrime', 'ExprPrime']],
    'NonIdExpr': [['NonIdPrimary', 'PowerPrime', 'TermPrime', 'ExprPrime'], ['MINUS', 'Unary', 'TermPrime', 'ExprPrime']],
    'NonIdPrimary': [['INT'], ['FLOAT'], ['FUNC', 'LPAREN', 'Expr', 'RPAREN'], ['LPAREN', 'Expr', 'RPAREN']],
    'Expr': [['IDENTIFIER', 'PowerPrime', 'TermPrime', 'ExprPrime'], ['NonIdExpr']],
    'ExprPrime': [['PLUS', 'Term', 'ExprPrime'], ['MINUS', 'Term', 'ExprPrime'], ['EPSILON']],
    'Term': [['Unary', 'TermPrime']],
    'TermPrime': [['STAR', 'Unary', 'TermPrime'], ['SLASH', 'Unary', 'TermPrime'], ['PERCENT', 'Unary', 'TermPrime'], ['EPSILON']],
    'Unary': [['MINUS', 'Unary'], ['Power']],
    'Power': [['Primary', 'PowerPrime']],
    'PowerPrime': [['CARET', 'Power'], ['EPSILON']],
    'Primary': [['IDENTIFIER'], ['NonIdPrimary']]
}

def compute_first(grammar):
    first = {nonterm: set() for nonterm in grammar}
    
    def get_first(symbol):
        if is_terminal(symbol):
            return {symbol}
        if symbol == 'EPSILON':
            return {'EPSILON'}
        return first[symbol]
        
    changed = True
    while changed:
        changed = False
        for nonterm, rules in grammar.items():
            for rule in rules:
                for symbol in rule:
                    sym_first = get_first(symbol)
                    before_len = len(first[nonterm])
                    first[nonterm].update(sym_first - {'EPSILON'})
                    if len(first[nonterm]) > before_len:
                        changed = True
                    if 'EPSILON' not in sym_first:
                        break
                else:
                    # If all symbols in rule can derive EPSILON
                    if 'EPSILON' not in first[nonterm]:
                        first[nonterm].add('EPSILON')
                        changed = True
    return first

def compute_follow(grammar, first_sets, start_symbol):
    follow = {nonterm: set() for nonterm in grammar}
    follow[start_symbol].add('EOF')
    
    def get_first(symbol):
        if is_terminal(symbol):
            return {symbol}
        if symbol == 'EPSILON':
            return {'EPSILON'}
        return first_sets[symbol]

    changed = True
    while changed:
        changed = False
        for nonterm, rules in grammar.items():
            for rule in rules:
                for i, symbol in enumerate(rule):
                    if not is_terminal(symbol) and symbol != 'EPSILON':
                        before_len = len(follow[symbol])
                        
                        # Calculate FIRST of the rest of the rule
                        rest = rule[i+1:]
                        rest_first = set()
                        all_epsilon = True
                        for r_sym in rest:
                            r_first = get_first(r_sym)
                            rest_first.update(r_first - {'EPSILON'})
                            if 'EPSILON' not in r_first:
                                all_epsilon = False
                                break
                        
                        follow[symbol].update(rest_first)
                        
                        if all_epsilon:
                            follow[symbol].update(follow[nonterm])
                            
                        if len(follow[symbol]) > before_len:
                            changed = True
    return follow

# Compute globally to be imported by parser
FIRST_SETS = compute_first(TRANSFORMED_GRAMMAR)
FOLLOW_SETS = compute_follow(TRANSFORMED_GRAMMAR, FIRST_SETS, 'Program')

def print_sets_table():
    print(f"{'Non-Terminal':<18} | {'FIRST Set':<50} | {'FOLLOW Set'}")
    print("-" * 110)
    for nt in TRANSFORMED_GRAMMAR:
        f_str = ", ".join(sorted(FIRST_SETS[nt]))
        fol_str = ", ".join(sorted(FOLLOW_SETS[nt]))
        print(f"{nt:<18} | {f_str:<50} | {fol_str}")

if __name__ == "__main__":
    print("Grammar Sets (Left-Factored, No Left-Recursion):")
    print_sets_table()
