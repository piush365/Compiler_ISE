from dataclasses import dataclass
from typing import List, Set, Any
from lexer import Token, Lexer
from grammar import FIRST_SETS

@dataclass
class SyntaxErrorInfo:
    token: Token
    expected_tokens: Set[str]
    source_snippet: str
    message: str

class SyntaxErrorExt(Exception):
    def __init__(self, error_info: SyntaxErrorInfo):
        super().__init__(error_info.message)
        self.error_info = error_info

# --- AST Nodes ---
@dataclass
class ASTNode:
    pass

@dataclass
class BinOp(ASTNode):
    left: ASTNode
    op: Token
    right: ASTNode

@dataclass
class UnaryOp(ASTNode):
    op: Token
    expr: ASTNode

@dataclass
class Assign(ASTNode):
    var_name: str
    expr: ASTNode

@dataclass
class FuncCall(ASTNode):
    func_name: str
    arg: ASTNode

@dataclass
class Num(ASTNode):
    value: float

@dataclass
class Var(ASTNode):
    name: str

class ParserRecursiveDescent:
    """
    LL(1) Predictive Recursive Descent Parser.
    Uses the Transformed (Left-Factored, No Left-Recursion) Grammar.
    Builds the AST by passing 'left_node' (inherited attributes) into the Prime functions.
    """
    def __init__(self, lexer: Lexer):
        self.lexer = lexer
        self.tokens = lexer.tokens
        self.pos = 0
        self.current = self.tokens[self.pos] if self.tokens else Token('EOF', '', 1, 1)

    def advance(self):
        self.pos += 1
        if self.pos < len(self.tokens):
            self.current = self.tokens[self.pos]
        else:
            self.current = Token('EOF', '', self.current.line, self.current.column)

    def error(self, non_terminal: str):
        expected = FIRST_SETS.get(non_terminal, {non_terminal})
        if 'EPSILON' in expected:
            expected = expected - {'EPSILON'}
            
        lines = self.lexer.source_code.splitlines()
        if 0 <= self.current.line - 1 < len(lines):
            line_str = lines[self.current.line - 1]
        else:
            line_str = ""
            
        snippet = f"{line_str}\n" + " " * (self.current.column - 1) + "^"
        msg = f"Syntax error at line {self.current.line}, col {self.current.column}. Unexpected token {self.current.type}. Expected one of: {', '.join(sorted(expected))}."
        
        raise SyntaxErrorExt(SyntaxErrorInfo(
            token=self.current,
            expected_tokens=expected,
            source_snippet=snippet,
            message=msg
        ))

    def match(self, token_type: str):
        if self.current.type == token_type:
            self.advance()
        else:
            self.error(token_type)

    def parse(self) -> List[ASTNode]:
        return self.parse_program()

    # Program -> Stmt StmtListPrime
    def parse_program(self) -> List[ASTNode]:
        stmts = []
        if self.current.type == 'EOF':
            return stmts
        stmts.append(self.parse_stmt())
        stmts.extend(self.parse_stmt_list_prime())
        return stmts

    # StmtListPrime -> SEMI Stmt StmtListPrime | EPSILON
    def parse_stmt_list_prime(self) -> List[ASTNode]:
        stmts = []
        if self.current.type == 'SEMI':
            self.match('SEMI')
            if self.current.type != 'EOF':
                stmts.append(self.parse_stmt())
                stmts.extend(self.parse_stmt_list_prime())
        return stmts

    # Stmt -> IDENTIFIER IdTail | NonIdExpr
    def parse_stmt(self) -> ASTNode:
        if self.current.type == 'IDENTIFIER':
            var_name = self.current.value
            self.match('IDENTIFIER')
            return self.parse_id_tail(Var(var_name))
        elif self.current.type in FIRST_SETS['NonIdExpr']:
            return self.parse_non_id_expr()
        else:
            self.error('Stmt')

    # IdTail -> ASSIGN Expr | PowerPrime TermPrime ExprPrime
    def parse_id_tail(self, var_node: Var) -> ASTNode:
        if self.current.type == 'ASSIGN':
            self.match('ASSIGN')
            expr = self.parse_expr()
            return Assign(var_node.name, expr)
        else:
            node = self.parse_power_prime(var_node)
            node = self.parse_term_prime(node)
            node = self.parse_expr_prime(node)
            return node

    # NonIdExpr -> NonIdPrimary PowerPrime TermPrime ExprPrime | MINUS Unary TermPrime ExprPrime
    def parse_non_id_expr(self) -> ASTNode:
        if self.current.type == 'MINUS':
            op = self.current
            self.match('MINUS')
            expr = self.parse_unary()
            node = UnaryOp(op, expr)
            node = self.parse_term_prime(node)
            node = self.parse_expr_prime(node)
            return node
        elif self.current.type in FIRST_SETS['NonIdPrimary']:
            node = self.parse_non_id_primary()
            node = self.parse_power_prime(node)
            node = self.parse_term_prime(node)
            node = self.parse_expr_prime(node)
            return node
        else:
            self.error('NonIdExpr')

    # Expr -> IDENTIFIER PowerPrime TermPrime ExprPrime | NonIdExpr
    def parse_expr(self) -> ASTNode:
        if self.current.type == 'IDENTIFIER':
            var_name = self.current.value
            self.match('IDENTIFIER')
            node = Var(var_name)
            node = self.parse_power_prime(node)
            node = self.parse_term_prime(node)
            node = self.parse_expr_prime(node)
            return node
        elif self.current.type in FIRST_SETS['NonIdExpr']:
            return self.parse_non_id_expr()
        else:
            self.error('Expr')

    # ExprPrime -> PLUS Term ExprPrime | MINUS Term ExprPrime | EPSILON
    def parse_expr_prime(self, left_node: ASTNode) -> ASTNode:
        if self.current.type in ('PLUS', 'MINUS'):
            op = self.current
            self.match(op.type)
            right_term = self.parse_term()
            new_left = BinOp(left_node, op, right_term)
            return self.parse_expr_prime(new_left)
        else:
            return left_node

    # Term -> Unary TermPrime
    def parse_term(self) -> ASTNode:
        node = self.parse_unary()
        return self.parse_term_prime(node)

    # TermPrime -> STAR Unary TermPrime | SLASH Unary TermPrime | PERCENT Unary TermPrime | EPSILON
    def parse_term_prime(self, left_node: ASTNode) -> ASTNode:
        if self.current.type in ('STAR', 'SLASH', 'PERCENT'):
            op = self.current
            self.match(op.type)
            right_unary = self.parse_unary()
            new_left = BinOp(left_node, op, right_unary)
            return self.parse_term_prime(new_left)
        else:
            return left_node

    # Unary -> MINUS Unary | Power
    def parse_unary(self) -> ASTNode:
        if self.current.type == 'MINUS':
            op = self.current
            self.match('MINUS')
            node = self.parse_unary()
            return UnaryOp(op, node)
        elif self.current.type in FIRST_SETS['Power']:
            return self.parse_power()
        else:
            self.error('Unary')

    # Power -> Primary PowerPrime
    def parse_power(self) -> ASTNode:
        node = self.parse_primary()
        return self.parse_power_prime(node)

    # PowerPrime -> CARET Power | EPSILON
    def parse_power_prime(self, left_node: ASTNode) -> ASTNode:
        if self.current.type == 'CARET':
            op = self.current
            self.match('CARET')
            # CARET is right-associative, so we parse 'Power' instead of 'Primary' on the right
            right_power = self.parse_power()
            return BinOp(left_node, op, right_power)
        else:
            return left_node

    # Primary -> IDENTIFIER | NonIdPrimary
    def parse_primary(self) -> ASTNode:
        if self.current.type == 'IDENTIFIER':
            var_name = self.current.value
            self.match('IDENTIFIER')
            return Var(var_name)
        elif self.current.type in FIRST_SETS['NonIdPrimary']:
            return self.parse_non_id_primary()
        else:
            self.error('Primary')

    # NonIdPrimary -> INT | FLOAT | FUNC LPAREN Expr RPAREN | LPAREN Expr RPAREN
    def parse_non_id_primary(self) -> ASTNode:
        if self.current.type == 'INT':
            val = int(self.current.value)
            self.match('INT')
            return Num(val)
        elif self.current.type == 'FLOAT':
            val = float(self.current.value)
            self.match('FLOAT')
            return Num(val)
        elif self.current.type == 'FUNC':
            func_name = self.current.value
            self.match('FUNC')
            self.match('LPAREN')
            arg = self.parse_expr()
            self.match('RPAREN')
            return FuncCall(func_name, arg)
        elif self.current.type == 'LPAREN':
            self.match('LPAREN')
            node = self.parse_expr()
            self.match('RPAREN')
            return node
        else:
            self.error('NonIdPrimary')

if __name__ == "__main__":
    test_code = "x = 5.5 + -3 * sin(y); z = x ^ 2 ^ 3"
    lexer = Lexer(test_code)
    lexer.tokenize()
    parser = ParserRecursiveDescent(lexer)
    try:
        ast = parser.parse()
        import pprint
        pprint.pprint(ast)
    except SyntaxErrorExt as e:
        print(f"Error: {e.error_info.message}")
        print(e.error_info.source_snippet)
