"""
parser_bottom_up.py - SLR(1) shift-reduce parser for the ORIGINAL (left-recursive) grammar.

Builds the canonical LR(0) collection, the SLR(1) ACTION/GOTO tables, and then
parses with a state stack. Alongside the state stack it keeps a VALUE stack, and
every reduction runs a semantic action that builds the AST node for the
left-hand side from the values of the right-hand side - an S-attributed
syntax-directed definition (only synthesized attributes, evaluated bottom-up,
in exactly the order the parser reduces).
"""
from lexer import Token, Lexer
from parser_recursive_descent import SyntaxErrorInfo, SyntaxErrorExt, make_snippet
from grammar import ORIGINAL_GRAMMAR, is_terminal, compute_first, compute_follow
from ast_nodes import Num, Bool, Var, BinOp, UnaryOp, FuncCall, Assign, Print, Block, If, While


def closure(items, grammar):
    closure_set = set(items)
    work = list(items)
    while work:
        nt, rule_idx, dot_pos = work.pop()
        rule = grammar[nt][rule_idx]
        if dot_pos < len(rule):
            next_sym = rule[dot_pos]
            if not is_terminal(next_sym):
                for i in range(len(grammar[next_sym])):
                    new_item = (next_sym, i, 0)
                    if new_item not in closure_set:
                        closure_set.add(new_item)
                        work.append(new_item)
    return closure_set


def goto(items, symbol, grammar):
    next_items = set()
    for nt, rule_idx, dot_pos in items:
        rule = grammar[nt][rule_idx]
        if dot_pos < len(rule) and rule[dot_pos] == symbol:
            next_items.add((nt, rule_idx, dot_pos + 1))
    return closure(next_items, grammar)


def build_states(grammar, start_symbol):
    initial_state = frozenset(closure({(start_symbol, 0, 0)}, grammar))
    states = [initial_state]
    index = {initial_state: 0}
    transitions = {}

    symbols = set()
    for nt, rules in grammar.items():
        symbols.add(nt)
        for r in rules:
            symbols.update(r)
    symbols = sorted(symbols)  # deterministic state numbering

    unprocessed = [0]
    while unprocessed:
        state_idx = unprocessed.pop(0)
        for sym in symbols:
            next_state = frozenset(goto(states[state_idx], sym, grammar))
            if not next_state:
                continue
            if next_state not in index:
                index[next_state] = len(states)
                states.append(next_state)
                unprocessed.append(len(states) - 1)
            transitions[(state_idx, sym)] = index[next_state]
    return states, transitions


def build_parsing_table(states, transitions, grammar, follow_sets):
    """Returns (action, goto, conflicts). A non-empty conflict list means the grammar is not SLR(1)."""
    action_table, goto_table, conflicts = {}, {}, []

    def set_action(i, a, act):
        old = action_table[i].get(a)
        if old is not None and old != act:
            conflicts.append((i, a, old, act))
        action_table[i][a] = act

    for i, state in enumerate(states):
        action_table[i] = {}
        goto_table[i] = {}
        for nt, rule_idx, dot_pos in state:
            rule = grammar[nt][rule_idx]
            if dot_pos < len(rule):
                a = rule[dot_pos]
                if is_terminal(a):
                    set_action(i, a, ('s', transitions[(i, a)]))
            elif nt == "Program'":
                set_action(i, 'EOF', ('acc', None))
            else:
                for a in follow_sets[nt]:
                    set_action(i, a, ('r', nt, rule_idx))
        for sym in grammar:
            if (i, sym) in transitions:
                goto_table[i][sym] = transitions[(i, sym)]
    return action_table, goto_table, conflicts


def semantic_action(nt, rule_idx, vals):
    """
    S-attributed SDD: compute the synthesized attribute (an AST node / list / token)
    of the left-hand side `nt` from the attributes `vals` of the right-hand side.
    """
    rule = ORIGINAL_GRAMMAR[nt][rule_idx]
    if nt == "Program" and not rule:
        return []                             # Program -> EPSILON
    if nt in ("Program", "Stmt", "RelOp"):
        return vals[0]                        # copy rules  (Stmt -> X SEMI also takes X)
    if nt == "StmtList":
        return vals[0] + [vals[1]] if len(rule) == 2 else [vals[0]]
    if nt == "Assignment":
        return Assign(vals[0].value, vals[2], vals[0].line, vals[0].column)
    if nt == "PrintStmt":
        return Print(vals[2], vals[0].line, vals[0].column)
    if nt == "Block":
        return Block(vals[1] if len(rule) == 3 else [])
    if nt == "IfStmt":
        if rule_idx == 0:
            else_body = None
        elif rule_idx == 1:
            else_body = vals[6].stmts
        else:
            else_body = [vals[6]]
        return If(vals[2], vals[4].stmts, else_body, vals[0].line, vals[0].column)
    if nt == "WhileStmt":
        return While(vals[2], vals[4].stmts, vals[0].line, vals[0].column)
    if nt in ("Expr", "AndExpr", "RelExpr", "Arith", "Term", "Power"):
        if len(rule) == 3:                    # E -> E op T : E.node = new BinOp(E1.node, op, T.node)
            return BinOp(vals[0], vals[1], vals[2])
        return vals[0]                        # E -> T : E.node = T.node
    if nt == "Unary":
        return UnaryOp(vals[0], vals[1]) if len(rule) == 2 else vals[0]
    if nt == "Primary":
        tok = vals[0]
        if rule[0] == "IDENTIFIER":
            return Var(tok.value, tok.line, tok.column)
        if rule[0] == "INT":
            return Num(int(tok.value), tok.line, tok.column)
        if rule[0] == "FLOAT":
            return Num(float(tok.value), tok.line, tok.column)
        if rule[0] in ("TRUE", "FALSE"):
            return Bool(rule[0] == "TRUE", tok.line, tok.column)
        if rule[0] == "FUNC":
            return FuncCall(tok.value, vals[2], tok.line, tok.column)
        return vals[1]                        # ( Expr )
    raise ValueError(f"no semantic action for {nt}")


# The tables depend only on the grammar, so build them once and share them.
_FIRST = compute_first(ORIGINAL_GRAMMAR)
_FOLLOW = compute_follow(ORIGINAL_GRAMMAR, _FIRST, "Program'")
_STATES, _TRANSITIONS = build_states(ORIGINAL_GRAMMAR, "Program'")
_ACTION, _GOTO, SLR_CONFLICTS = build_parsing_table(_STATES, _TRANSITIONS, ORIGINAL_GRAMMAR, _FOLLOW)


class ParserBottomUp:
    def __init__(self, lexer: Lexer):
        self.lexer = lexer
        self.tokens = lexer.tokens
        self.first_sets = _FIRST
        self.follow_sets = _FOLLOW
        self.states, self.transitions = _STATES, _TRANSITIONS
        self.action, self.goto = _ACTION, _GOTO
        self.conflicts = SLR_CONFLICTS

    def print_parsing_table(self):
        terminals = sorted({t for rules in ORIGINAL_GRAMMAR.values() for rule in rules for t in rule if is_terminal(t)} | {'EOF'})
        non_terminals = sorted([nt for nt in ORIGINAL_GRAMMAR.keys() if nt != "Program'"])
        print(f"SLR(1) Parsing Table: {len(self.states)} states, "
              f"{'no conflicts' if not self.conflicts else str(len(self.conflicts)) + ' CONFLICTS'}")
        for i in range(len(self.states)):
            acts = []
            for t in terminals:
                a = self.action[i].get(t)
                if a is None:
                    continue
                if a[0] == 's':
                    acts.append(f"{t}:s{a[1]}")
                elif a[0] == 'r':
                    acts.append(f"{t}:r({a[1]}->{' '.join(ORIGINAL_GRAMMAR[a[1]][a[2]])})")
                else:
                    acts.append(f"{t}:acc")
            gotos = [f"{nt}:{self.goto[i][nt]}" for nt in non_terminals if nt in self.goto[i]]
            print(f"  I{i:<3} ACTION {'  '.join(acts)}")
            if gotos:
                print(f"       GOTO   {'  '.join(gotos)}")

    def parse(self, trace=True):
        """Parse the token stream. Returns the AST (list of statements)."""
        if trace:
            print(f"{'Stack':<40} | {'Input':<30} | {'Action'}")
            print("-" * 90)

        stack = [0]          # alternating: state, symbol, state, symbol, state ...
        values = []          # semantic value of each grammar symbol on the stack
        pos = 0
        while True:
            state = stack[-1]
            token = self.tokens[pos] if pos < len(self.tokens) else Token('EOF', '', self.tokens[-1].line, self.tokens[-1].column + 1)
            sym = token.type

            if trace:
                stack_str = " ".join(str(s) for s in stack)
                input_str = " ".join(t.type for t in self.tokens[pos:])
                if len(stack_str) > 38: stack_str = "..." + stack_str[-35:]
                if len(input_str) > 28: input_str = input_str[:25] + "..."

            action = self.action[state].get(sym)
            if action is None:
                if trace: print(f"{stack_str:<40} | {input_str:<30} | ERROR")
                expected = set(self.action[state].keys())
                msg = (f"Syntax error at line {token.line}, col {token.column}. "
                       f"Unexpected token {token.type}. Expected: {', '.join(sorted(expected))}.")
                raise SyntaxErrorExt(SyntaxErrorInfo(token, expected, make_snippet(self.lexer.source_code, token), msg))

            if action[0] == 's':
                if trace: print(f"{stack_str:<40} | {input_str:<30} | Shift {action[1]}")
                stack.append(sym)
                stack.append(action[1])
                values.append(token)
                pos += 1
            elif action[0] == 'r':
                nt, rule_idx = action[1], action[2]
                rule = ORIGINAL_GRAMMAR[nt][rule_idx]
                if trace: print(f"{stack_str:<40} | {input_str:<30} | Reduce {nt} -> {' '.join(rule)}")
                for _ in range(2 * len(rule)):
                    stack.pop()
                rhs_vals = values[len(values) - len(rule):]
                del values[len(values) - len(rule):]
                values.append(semantic_action(nt, rule_idx, rhs_vals))
                stack.append(nt)
                stack.append(self.goto[stack[-2]][nt])
            else:
                if trace: print(f"{stack_str:<40} | {input_str:<30} | Accept!")
                return values[-1]


if __name__ == "__main__":
    from ast_nodes import format_tree
    test_code = "x = 5.5 + -3 * sin(y);"
    lexer = Lexer(test_code)
    lexer.tokenize()
    parser = ParserBottomUp(lexer)
    print(format_tree(parser.parse(trace=True)))
