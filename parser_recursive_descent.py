from dataclasses import dataclass
from typing import List, Set
from lexer import Token, Lexer
from grammar import FIRST_SETS, RELOP_TOKENS
# AST nodes live in ast_nodes.py; re-exported here so old imports keep working.
from ast_nodes import (ASTNode, BinOp, UnaryOp, Assign, FuncCall, Num, Bool, Var,
                       Print, Block, If, While)


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


def make_snippet(source_code: str, token: Token) -> str:
    lines = source_code.splitlines()
    line_str = lines[token.line - 1] if 0 <= token.line - 1 < len(lines) else ""
    return f"{line_str}\n" + " " * (max(token.column, 1) - 1) + "^"


# Tokens that may continue an expression (used to make "expected ..." messages
# accurate when an expression is followed by something unexpected).
EXPR_CONTINUATION = FIRST_SETS['ExprTail'] | FIRST_SETS['PowerPrime']


class ParserRecursiveDescent:
    """
    LL(1) Predictive Recursive Descent Parser.
    Uses the Transformed (Left-Factored, No Left-Recursion) Grammar.
    Builds the AST with an L-attributed SDD: the tree built so far ('left_node')
    is passed DOWN into the *Prime functions as an inherited attribute, and the
    finished subtree comes back UP as the synthesized result.
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

    def error(self, non_terminal: str, extra: Set[str] = frozenset()):
        expected = set(FIRST_SETS.get(non_terminal, {non_terminal})) | set(extra)
        expected.discard('EPSILON')
        msg = (f"Syntax error at line {self.current.line}, col {self.current.column}. "
               f"Unexpected token {self.current.type}. Expected one of: {', '.join(sorted(expected))}.")
        raise SyntaxErrorExt(SyntaxErrorInfo(
            token=self.current,
            expected_tokens=expected,
            source_snippet=make_snippet(self.lexer.source_code, self.current),
            message=msg
        ))

    def match(self, token_type: str, extra: Set[str] = frozenset()):
        if self.current.type == token_type:
            tok = self.current
            self.advance()
            return tok
        self.error(token_type, extra)

    def parse(self) -> List[ASTNode]:
        return self.parse_program()

    # Program -> StmtList   (must be followed by EOF)
    def parse_program(self) -> List[ASTNode]:
        stmts = self.parse_stmt_list()
        if self.current.type != 'EOF':
            self.error('Stmt', {'EOF'})
        return stmts

    # StmtList -> Stmt StmtList | EPSILON
    def parse_stmt_list(self) -> List[ASTNode]:
        stmts = []
        while self.current.type in FIRST_SETS['Stmt']:
            stmts.append(self.parse_stmt())
        return stmts

    # Stmt -> IDENTIFIER IdTail SEMI | NonIdUnary ExprTail SEMI
    #       | PRINT LPAREN Expr RPAREN SEMI | IfStmt | WhileStmt | Block
    def parse_stmt(self) -> ASTNode:
        t = self.current.type
        if t == 'IDENTIFIER':
            tok = self.match('IDENTIFIER')
            node = self.parse_id_tail(Var(tok.value, tok.line, tok.column), tok)
            self.match('SEMI', EXPR_CONTINUATION)
            return node
        if t in FIRST_SETS['NonIdUnary']:
            node = self.parse_non_id_unary()
            node = self.parse_expr_tail(node)
            self.match('SEMI', EXPR_CONTINUATION)
            return node
        if t == 'PRINT':
            tok = self.match('PRINT')
            self.match('LPAREN')
            expr = self.parse_expr()
            self.match('RPAREN', EXPR_CONTINUATION)
            self.match('SEMI')
            return Print(expr, tok.line, tok.column)
        if t == 'IF':
            return self.parse_if()
        if t == 'WHILE':
            return self.parse_while()
        if t == 'LBRACE':
            return self.parse_block()
        self.error('Stmt')

    # IdTail -> ASSIGN Expr | PowerPrime ExprTail
    def parse_id_tail(self, var_node: Var, id_tok: Token) -> ASTNode:
        if self.current.type == 'ASSIGN':
            self.match('ASSIGN')
            expr = self.parse_expr()
            return Assign(var_node.name, expr, id_tok.line, id_tok.column)
        node = self.parse_power_prime(var_node)
        return self.parse_expr_tail(node)

    # ExprTail -> TermPrime ArithPrime RelTail AndPrime OrPrime
    def parse_expr_tail(self, left_node: ASTNode) -> ASTNode:
        node = self.parse_term_prime(left_node)
        node = self.parse_arith_prime(node)
        node = self.parse_rel_tail(node)
        node = self.parse_and_prime(node)
        return self.parse_or_prime(node)

    # NonIdUnary -> MINUS Unary | NOT Unary | NonIdPrimary PowerPrime
    def parse_non_id_unary(self) -> ASTNode:
        if self.current.type in ('MINUS', 'NOT'):
            op = self.match(self.current.type)
            return UnaryOp(op, self.parse_unary())
        if self.current.type in FIRST_SETS['NonIdPrimary']:
            node = self.parse_non_id_primary()
            return self.parse_power_prime(node)
        self.error('NonIdUnary')

    # Block -> LBRACE StmtList RBRACE
    def parse_block(self) -> Block:
        self.match('LBRACE')
        stmts = self.parse_stmt_list()
        self.match('RBRACE', FIRST_SETS['Stmt'])
        return Block(stmts)

    # IfStmt -> IF LPAREN Expr RPAREN Block ElsePart
    # ElsePart -> ELSE ElseTail | EPSILON ;  ElseTail -> Block | IfStmt
    def parse_if(self) -> If:
        tok = self.match('IF')
        self.match('LPAREN')
        cond = self.parse_expr()
        self.match('RPAREN', EXPR_CONTINUATION)
        then_block = self.parse_block()
        else_body = None
        if self.current.type == 'ELSE':
            self.match('ELSE')
            if self.current.type == 'LBRACE':
                else_body = self.parse_block().stmts
            elif self.current.type == 'IF':
                else_body = [self.parse_if()]
            else:
                self.error('ElseTail')
        return If(cond, then_block.stmts, else_body, tok.line, tok.column)

    # WhileStmt -> WHILE LPAREN Expr RPAREN Block
    def parse_while(self) -> While:
        tok = self.match('WHILE')
        self.match('LPAREN')
        cond = self.parse_expr()
        self.match('RPAREN', EXPR_CONTINUATION)
        body = self.parse_block()
        return While(cond, body.stmts, tok.line, tok.column)

    # Expr -> AndExpr OrPrime
    def parse_expr(self) -> ASTNode:
        if self.current.type not in FIRST_SETS['Expr']:
            self.error('Expr')
        return self.parse_or_prime(self.parse_and_expr())

    # OrPrime -> OR AndExpr OrPrime | EPSILON
    def parse_or_prime(self, left_node: ASTNode) -> ASTNode:
        if self.current.type == 'OR':
            op = self.match('OR')
            return self.parse_or_prime(BinOp(left_node, op, self.parse_and_expr()))
        return left_node

    # AndExpr -> RelExpr AndPrime
    def parse_and_expr(self) -> ASTNode:
        return self.parse_and_prime(self.parse_rel_expr())

    # AndPrime -> AND RelExpr AndPrime | EPSILON
    def parse_and_prime(self, left_node: ASTNode) -> ASTNode:
        if self.current.type == 'AND':
            op = self.match('AND')
            return self.parse_and_prime(BinOp(left_node, op, self.parse_rel_expr()))
        return left_node

    # RelExpr -> Arith RelTail
    def parse_rel_expr(self) -> ASTNode:
        return self.parse_rel_tail(self.parse_arith())

    # RelTail -> RelOp Arith | EPSILON
    def parse_rel_tail(self, left_node: ASTNode) -> ASTNode:
        if self.current.type in RELOP_TOKENS:
            op = self.match(self.current.type)
            return BinOp(left_node, op, self.parse_arith())
        return left_node

    # Arith -> Term ArithPrime
    def parse_arith(self) -> ASTNode:
        return self.parse_arith_prime(self.parse_term())

    # ArithPrime -> PLUS Term ArithPrime | MINUS Term ArithPrime | EPSILON
    def parse_arith_prime(self, left_node: ASTNode) -> ASTNode:
        if self.current.type in ('PLUS', 'MINUS'):
            op = self.match(self.current.type)
            return self.parse_arith_prime(BinOp(left_node, op, self.parse_term()))
        return left_node

    # Term -> Unary TermPrime
    def parse_term(self) -> ASTNode:
        return self.parse_term_prime(self.parse_unary())

    # TermPrime -> STAR Unary TermPrime | SLASH Unary TermPrime | PERCENT Unary TermPrime | EPSILON
    def parse_term_prime(self, left_node: ASTNode) -> ASTNode:
        if self.current.type in ('STAR', 'SLASH', 'PERCENT'):
            op = self.match(self.current.type)
            return self.parse_term_prime(BinOp(left_node, op, self.parse_unary()))
        return left_node

    # Unary -> MINUS Unary | NOT Unary | Power
    def parse_unary(self) -> ASTNode:
        if self.current.type in ('MINUS', 'NOT'):
            op = self.match(self.current.type)
            return UnaryOp(op, self.parse_unary())
        if self.current.type in FIRST_SETS['Power']:
            return self.parse_power()
        self.error('Unary')

    # Power -> Primary PowerPrime
    def parse_power(self) -> ASTNode:
        return self.parse_power_prime(self.parse_primary())

    # PowerPrime -> CARET Power | EPSILON
    def parse_power_prime(self, left_node: ASTNode) -> ASTNode:
        if self.current.type == 'CARET':
            op = self.match('CARET')
            # CARET is right-associative, so we parse 'Power' instead of 'Primary' on the right
            return BinOp(left_node, op, self.parse_power())
        return left_node

    # Primary -> IDENTIFIER | NonIdPrimary
    def parse_primary(self) -> ASTNode:
        if self.current.type == 'IDENTIFIER':
            tok = self.match('IDENTIFIER')
            return Var(tok.value, tok.line, tok.column)
        if self.current.type in FIRST_SETS['NonIdPrimary']:
            return self.parse_non_id_primary()
        self.error('Primary')

    # NonIdPrimary -> INT | FLOAT | TRUE | FALSE | FUNC LPAREN Expr RPAREN | LPAREN Expr RPAREN
    def parse_non_id_primary(self) -> ASTNode:
        tok = self.current
        if tok.type == 'INT':
            self.match('INT')
            return Num(int(tok.value), tok.line, tok.column)
        if tok.type == 'FLOAT':
            self.match('FLOAT')
            return Num(float(tok.value), tok.line, tok.column)
        if tok.type in ('TRUE', 'FALSE'):
            self.match(tok.type)
            return Bool(tok.type == 'TRUE', tok.line, tok.column)
        if tok.type == 'FUNC':
            self.match('FUNC')
            self.match('LPAREN')
            arg = self.parse_expr()
            self.match('RPAREN', EXPR_CONTINUATION)
            return FuncCall(tok.value, arg, tok.line, tok.column)
        if tok.type == 'LPAREN':
            self.match('LPAREN')
            node = self.parse_expr()
            self.match('RPAREN', EXPR_CONTINUATION)
            return node
        self.error('NonIdPrimary')


if __name__ == "__main__":
    from ast_nodes import format_tree
    test_code = "x = 5.5 + -3 * sin(y); z = x ^ 2 ^ 3; if (z > 1 && !(x == 2)) { print(z); }"
    lexer = Lexer(test_code)
    lexer.tokenize()
    parser = ParserRecursiveDescent(lexer)
    try:
        print(format_tree(parser.parse()))
    except SyntaxErrorExt as e:
        print(f"Error: {e.error_info.message}")
        print(e.error_info.source_snippet)
