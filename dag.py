"""
dag.py - Module 6 (and 5): DAG representation of a basic block.

Construction (Dragon book, section 8.5.1). For each instruction x = y op z:
  * find the node currently holding y (create a leaf "y_0" for y's initial value
    if there is none), and likewise for z;
  * look for an existing node with label op and the same children - if one
    exists, that is a COMMON SUB-EXPRESSION and it is reused; otherwise a new
    node is created;
  * attach x to that node (and detach x from the node it was attached to before).
x = y simply attaches x to y's node.

Uses of the DAG: detecting common sub-expressions, finding names used in the
block but computed outside it (the leaves), names whose values are available
at the end of the block (attached identifiers), and reordering evaluation.
Instructions with side effects (print, param/call, jumps) become root nodes in
program order.
"""
from icg import BINARY_OPS, UNARY_OPS, fmt
from optimizer import ckey, is_const


class DAGNode:
    def __init__(self, num, label, children=(), leaf=False):
        self.target = None
        self.num = num
        self.label = label
        self.children = list(children)
        self.leaf = leaf
        self.ids = []


class DAG:
    def __init__(self, block):
        self.block = block
        self.nodes = []
        self.current = {}        # name -> node currently holding its value
        self.leaves = {}         # key -> leaf node
        self.interior = {}       # (op, child numbers) -> node
        self.roots = []          # side-effect nodes, in order
        pending_params = []
        for q in block.instrs:
            if q.op in BINARY_OPS or q.op in UNARY_OPS:
                kids = [self.node_for(q.arg1)] + ([self.node_for(q.arg2)] if q.op in BINARY_OPS else [])
                key = (q.op, tuple(k.num for k in kids))
                if q.op in ('+', '*') and len(kids) == 2:
                    key = (q.op, tuple(sorted(k.num for k in kids)))
                n = self.interior.get(key)
                if n is None:
                    n = self.new(q.op, kids)
                    self.interior[key] = n
                self.attach(q.result, n)
            elif q.op == '=':
                self.attach(q.result, self.node_for(q.arg1))
            elif q.op == 'param':
                pending_params.append(self.node_for(q.arg1))
            elif q.op == 'call':
                n = self.new(f"call {q.arg1}", pending_params)
                pending_params = []
                self.roots.append(n)
                self.attach(q.result, n)
            elif q.op == 'print':
                self.roots.append(self.new('print', [self.node_for(q.arg1)]))
            elif q.op in ('goto', 'halt'):
                n = self.new(q.op, [])
                n.target = q.result
                self.roots.append(n)
            elif q.is_cond_jump():
                kids = [self.node_for(q.arg1)] + ([self.node_for(q.arg2)] if q.arg2 is not None else [])
                n = self.new(q.op, kids)
                n.target = q.result
                self.roots.append(n)

    def new(self, label, children, leaf=False):
        n = DAGNode(len(self.nodes) + 1, label, children, leaf)
        self.nodes.append(n)
        return n

    def node_for(self, a):
        if isinstance(a, str) and a in self.current:
            return self.current[a]
        key = ckey(a)
        if key not in self.leaves:
            self.leaves[key] = self.new(f"{a}_0" if isinstance(a, str) else fmt(a), [], leaf=True)
        return self.leaves[key]

    def attach(self, name, node):
        old = self.current.get(name)
        if old is not None and name in old.ids:
            old.ids.remove(name)
        node.ids.append(name)
        self.current[name] = node

    def format(self):
        out = []
        for n in self.nodes:
            kids = f"({', '.join('n' + str(k.num) for k in n.children)})" if n.children else ''
            ids = f"   [{', '.join(n.ids)}]" if n.ids else ''
            kind = 'leaf ' if n.leaf else ''
            tgt = f" -> {n.target}" if n.target else ''
            out.append(f"    n{n.num}: {kind}{n.label}{kids}{tgt}{ids}")
        shared = [n for n in self.nodes if not n.leaf and
                  sum(1 for m in self.nodes for c in m.children if c is n) > 1]
        if shared:
            out.append("    shared (common sub-expression) nodes: " + ', '.join(f"n{n.num}" for n in shared))
        return '\n'.join(out)


def format_dags(cfg):
    out = []
    for b in cfg.blocks:
        out.append(f"{b.name}:")
        out.append(DAG(b).format() or "    (empty)")
    return '\n'.join(out)
