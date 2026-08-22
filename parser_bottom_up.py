from lexer import Token, Lexer
from parser_recursive_descent import SyntaxErrorInfo, SyntaxErrorExt

ORIGINAL_GRAMMAR = {
    "Program'": [["Program"]],
    "Program": [["StmtList"]],
    "StmtList": [["StmtList", "SEMI", "Stmt"], ["Stmt"]],
    "Stmt": [["Assignment"], ["Expr"]],
    "Assignment": [["IDENTIFIER", "ASSIGN", "Expr"]],
    "Expr": [["Expr", "PLUS", "Term"], ["Expr", "MINUS", "Term"], ["Term"]],
    "Term": [["Term", "STAR", "Unary"], ["Term", "SLASH", "Unary"], ["Term", "PERCENT", "Unary"], ["Unary"]],
    "Unary": [["MINUS", "Unary"], ["Power"]],
    "Power": [["Primary", "CARET", "Power"], ["Primary"]],
    "Primary": [["IDENTIFIER"], ["INT"], ["FLOAT"], ["FUNC", "LPAREN", "Expr", "RPAREN"], ["LPAREN", "Expr", "RPAREN"]]
}

def is_terminal(symbol):
    return symbol.isupper() and symbol != 'EPSILON'

def compute_first(grammar):
    first = {nt: set() for nt in grammar}
    def get_first(symbol):
        if is_terminal(symbol): return {symbol}
        return first[symbol]
    changed = True
    while changed:
        changed = False
        for nt, rules in grammar.items():
            for rule in rules:
                for symbol in rule:
                    sym_first = get_first(symbol)
                    before_len = len(first[nt])
                    first[nt].update(sym_first - {'EPSILON'})
                    if len(first[nt]) > before_len: changed = True
                    if 'EPSILON' not in sym_first: break
                else:
                    if 'EPSILON' not in first[nt]:
                        first[nt].add('EPSILON')
                        changed = True
    return first

def compute_follow(grammar, first_sets, start_symbol):
    follow = {nt: set() for nt in grammar}
    follow[start_symbol].add('EOF')
    def get_first(symbol):
        if is_terminal(symbol): return {symbol}
        return first_sets[symbol]
    changed = True
    while changed:
        changed = False
        for nt, rules in grammar.items():
            for rule in rules:
                for i, symbol in enumerate(rule):
                    if not is_terminal(symbol):
                        before_len = len(follow[symbol])
                        rest_first = set()
                        all_epsilon = True
                        for r_sym in rule[i+1:]:
                            r_first = get_first(r_sym)
                            rest_first.update(r_first - {'EPSILON'})
                            if 'EPSILON' not in r_first:
                                all_epsilon = False
                                break
                        follow[symbol].update(rest_first)
                        if all_epsilon:
                            follow[symbol].update(follow[nt])
                        if len(follow[symbol]) > before_len:
                            changed = True
    return follow

def closure(items, grammar):
    closure_set = set(items)
    changed = True
    while changed:
        changed = False
        new_items = set()
        for nt, rule_idx, dot_pos in closure_set:
            rule = grammar[nt][rule_idx]
            if dot_pos < len(rule):
                next_sym = rule[dot_pos]
                if not is_terminal(next_sym):
                    for i in range(len(grammar[next_sym])):
                        new_item = (next_sym, i, 0)
                        if new_item not in closure_set:
                            new_items.add(new_item)
        if new_items:
            closure_set.update(new_items)
            changed = True
    return closure_set

def goto(items, symbol, grammar):
    next_items = set()
    for nt, rule_idx, dot_pos in items:
        rule = grammar[nt][rule_idx]
        if dot_pos < len(rule) and rule[dot_pos] == symbol:
            next_items.add((nt, rule_idx, dot_pos + 1))
    return closure(next_items, grammar)

def build_states(grammar, start_symbol):
    start_item = (start_symbol, 0, 0)
    initial_state = frozenset(closure({start_item}, grammar))
    states = [initial_state]
    transitions = {}
    
    symbols = set()
    for nt, rules in grammar.items():
        symbols.add(nt)
        for r in rules:
            symbols.update(r)
            
    unprocessed = [0]
    while unprocessed:
        state_idx = unprocessed.pop(0)
        state_items = states[state_idx]
        
        for sym in symbols:
            next_state = frozenset(goto(state_items, sym, grammar))
            if not next_state: continue
            
            if next_state not in states:
                states.append(next_state)
                unprocessed.append(len(states) - 1)
            
            next_idx = states.index(next_state)
            transitions[(state_idx, sym)] = next_idx
            
    return states, transitions

def build_parsing_table(states, transitions, grammar, follow_sets):
    action_table = {}
    goto_table = {}
    for i, state in enumerate(states):
        action_table[i] = {}
        goto_table[i] = {}
        for nt, rule_idx, dot_pos in state:
            rule = grammar[nt][rule_idx]
            if dot_pos < len(rule):
                a = rule[dot_pos]
                if is_terminal(a):
                    next_state = transitions.get((i, a))
                    if next_state is not None:
                        action_table[i][a] = ('s', next_state)
            else:
                if nt == "Program'":
                    action_table[i]['EOF'] = ('acc', None)
                else:
                    for a in follow_sets[nt]:
                        # SLR(1) conflict resolution (prefer shift over reduce generally, but in valid SLR(1) there should be no conflicts or we accept the overwrite. 
                        # This grammar has Shift/Reduce conflict due to dangling semi if not careful, but our grammar is well-formed.)
                        action_table[i][a] = ('r', nt, rule_idx)
                        
        for sym in grammar.keys():
            if not is_terminal(sym):
                next_state = transitions.get((i, sym))
                if next_state is not None:
                    goto_table[i][sym] = next_state
    return action_table, goto_table

class ParserBottomUp:
    def __init__(self, lexer: Lexer):
        self.lexer = lexer
        self.tokens = lexer.tokens
        
        self.first_sets = compute_first(ORIGINAL_GRAMMAR)
        self.follow_sets = compute_follow(ORIGINAL_GRAMMAR, self.first_sets, "Program'")
        self.states, self.transitions = build_states(ORIGINAL_GRAMMAR, "Program'")
        self.action, self.goto = build_parsing_table(self.states, self.transitions, ORIGINAL_GRAMMAR, self.follow_sets)

    def print_parsing_table(self):
        terminals = sorted({t for rules in ORIGINAL_GRAMMAR.values() for rule in rules for t in rule if is_terminal(t)} | {'EOF'})
        non_terminals = sorted([nt for nt in ORIGINAL_GRAMMAR.keys() if nt != "Program'"])
        
        print("SLR(1) Parsing Table:")
        header = f"{'State':<6} | " + " | ".join(f"{t:<6}" for t in terminals) + " || " + " | ".join(f"{nt:<10}" for nt in non_terminals)
        print("-" * len(header))
        print(header)
        print("-" * len(header))
        
        for i in range(len(self.states)):
            acts = []
            for t in terminals:
                a = self.action[i].get(t)
                if a is None: acts.append(f"{'':<6}")
                elif a[0] == 's': acts.append(f"s{a[1]:<5}")
                elif a[0] == 'r': acts.append(f"r({a[1]},{a[2]})".ljust(6))
                elif a[0] == 'acc': acts.append(f"{'acc':<6}")
                
            gotos = []
            for nt in non_terminals:
                g = self.goto[i].get(nt)
                if g is None: gotos.append(f"{'':<10}")
                else: gotos.append(f"{g:<10}")
                
            print(f"{i:<6} | " + " | ".join(acts) + " || " + " | ".join(gotos))

    def parse(self, trace=True):
        if trace:
            print(f"{'Stack':<40} | {'Input':<30} | {'Action'}")
            print("-" * 90)
            
        stack = [0]
        pos = 0
        while True:
            state = stack[-1]
            token = self.tokens[pos] if pos < len(self.tokens) else Token('EOF', '', self.tokens[-1].line, self.tokens[-1].column + 1)
            sym = token.type
            
            stack_str = " ".join(str(s) for s in stack)
            input_str = " ".join(t.type for t in self.tokens[pos:])
            if len(stack_str) > 38: stack_str = "..." + stack_str[-35:]
            if len(input_str) > 28: input_str = input_str[:25] + "..."
            
            action = self.action[state].get(sym)
            if action is None:
                if trace: print(f"{stack_str:<40} | {input_str:<30} | ERROR")
                
                expected = set(self.action[state].keys())
                lines = self.lexer.source_code.splitlines()
                line_str = lines[token.line - 1] if 0 <= token.line - 1 < len(lines) else ""
                snippet = f"{line_str}\n" + " " * (token.column - 1) + "^"
                msg = f"Syntax error at line {token.line}, col {token.column}. Unexpected token {token.type}. Expected: {', '.join(sorted(expected))}."
                raise SyntaxErrorExt(SyntaxErrorInfo(token, expected, snippet, msg))
                
            if action[0] == 's':
                if trace: print(f"{stack_str:<40} | {input_str:<30} | Shift {action[1]}")
                stack.append(sym)
                stack.append(action[1])
                pos += 1
            elif action[0] == 'r':
                nt, rule_idx = action[1], action[2]
                rule = ORIGINAL_GRAMMAR[nt][rule_idx]
                if trace: print(f"{stack_str:<40} | {input_str:<30} | Reduce {nt} -> {' '.join(rule)}")
                # Pop 2 * len(rule) items
                for _ in range(2 * len(rule)):
                    stack.pop()
                top_state = stack[-1]
                next_state = self.goto[top_state][nt]
                stack.append(nt)
                stack.append(next_state)
            elif action[0] == 'acc':
                if trace: print(f"{stack_str:<40} | {input_str:<30} | Accept!")
                return True

if __name__ == "__main__":
    test_code = "x = 5.5 + -3 * sin(y)"
    lexer = Lexer(test_code)
    lexer.tokenize()
    parser = ParserBottomUp(lexer)
    # parser.print_parsing_table() # Optional
    parser.parse(trace=True)
