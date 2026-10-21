"""
ast_nodes.py - Abstract Syntax Tree node classes.

Both parsers build exactly these nodes:
  * the LL(1) parser through an L-attributed SDD (the left operand is passed
    DOWN into the *Prime functions as an inherited attribute), and
  * the SLR(1) parser through an S-attributed SDD (each reduction builds its
    node from the values of the symbols it pops - synthesized attributes).

Semantic analysis later decorates every expression node with a synthesized
attribute `ty` ('int', 'float' or 'bool'). It is set as a plain attribute, not a
dataclass field, so it does not affect equality between the two parsers' trees.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Union
from lexer import Token


@dataclass
class ASTNode:
    pass


# ---------- Expressions ----------
@dataclass
class Num(ASTNode):
    value: Union[int, float]
    line: int = 0
    col: int = 0


@dataclass
class Bool(ASTNode):
    value: bool
    line: int = 0
    col: int = 0


@dataclass
class Var(ASTNode):
    name: str
    line: int = 0
    col: int = 0


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
class FuncCall(ASTNode):
    func_name: str
    arg: ASTNode
    line: int = 0
    col: int = 0


# ---------- Statements ----------
@dataclass
class Assign(ASTNode):
    var_name: str
    expr: ASTNode
    line: int = 0
    col: int = 0


@dataclass
class Print(ASTNode):
    expr: ASTNode
    line: int = 0
    col: int = 0


@dataclass
class Block(ASTNode):
    stmts: List[ASTNode] = field(default_factory=list)


@dataclass
class If(ASTNode):
    cond: ASTNode
    then_body: List[ASTNode]
    else_body: Optional[List[ASTNode]] = None
    line: int = 0
    col: int = 0


@dataclass
class While(ASTNode):
    cond: ASTNode
    body: List[ASTNode]
    line: int = 0
    col: int = 0


def node_pos(node):
    """Best-effort (line, col) of a node, used in semantic error messages."""
    if isinstance(node, BinOp):
        return node.op.line, node.op.column
    if isinstance(node, UnaryOp):
        return node.op.line, node.op.column
    return getattr(node, 'line', 0), getattr(node, 'col', 0)


def format_tree(node, indent=0, show_types=False):
    """Pretty-print an AST (optionally annotated with the `ty` attribute)."""
    pad = '  ' * indent
    ty = f"  : {node.ty}" if show_types and getattr(node, 'ty', None) else ''
    if isinstance(node, list):
        return '\n'.join(format_tree(s, indent, show_types) for s in node)
    if isinstance(node, Num):
        return f"{pad}Num {node.value}{ty}"
    if isinstance(node, Bool):
        return f"{pad}Bool {'true' if node.value else 'false'}{ty}"
    if isinstance(node, Var):
        return f"{pad}Var {node.name}{ty}"
    if isinstance(node, BinOp):
        return (f"{pad}BinOp '{node.op.value}'{ty}\n"
                f"{format_tree(node.left, indent + 1, show_types)}\n"
                f"{format_tree(node.right, indent + 1, show_types)}")
    if isinstance(node, UnaryOp):
        return f"{pad}UnaryOp '{node.op.value}'{ty}\n{format_tree(node.expr, indent + 1, show_types)}"
    if isinstance(node, FuncCall):
        return f"{pad}Call {node.func_name}(){ty}\n{format_tree(node.arg, indent + 1, show_types)}"
    if isinstance(node, Assign):
        return f"{pad}Assign {node.var_name}{ty}\n{format_tree(node.expr, indent + 1, show_types)}"
    if isinstance(node, Print):
        return f"{pad}Print\n{format_tree(node.expr, indent + 1, show_types)}"
    if isinstance(node, Block):
        return f"{pad}Block\n{format_tree(node.stmts, indent + 1, show_types)}" if node.stmts else f"{pad}Block (empty)"
    if isinstance(node, If):
        out = f"{pad}If\n{pad}  cond:\n{format_tree(node.cond, indent + 2, show_types)}\n{pad}  then:"
        out += ('\n' + format_tree(node.then_body, indent + 2, show_types)) if node.then_body else ' (empty)'
        if node.else_body is not None:
            out += f"\n{pad}  else:"
            out += ('\n' + format_tree(node.else_body, indent + 2, show_types)) if node.else_body else ' (empty)'
        return out
    if isinstance(node, While):
        out = f"{pad}While\n{pad}  cond:\n{format_tree(node.cond, indent + 2, show_types)}\n{pad}  body:"
        out += ('\n' + format_tree(node.body, indent + 2, show_types)) if node.body else ' (empty)'
        return out
    return f"{pad}{node!r}"
