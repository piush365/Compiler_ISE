"""
cfg.py - Basic blocks and flow graphs (Modules 4 & 5).

Partitioning into basic blocks (Dragon book, Algorithm 8.5). LEADERS are:
  1. the first instruction,
  2. any instruction that is the target of a jump,
  3. any instruction that immediately follows a jump.
Each basic block runs from a leader up to (not including) the next leader.

In the flow graph, jump targets are block labels (B1, B2, ...) instead of quad
numbers, and there is an edge B -> C if C can run right after B: either B ends
in a jump to C, or C follows B in the layout and B does not end in an
unconditional jump.
"""
import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class BasicBlock:
    name: str
    instrs: list = field(default_factory=list)
    succ: List[str] = field(default_factory=list)
    pred: List[str] = field(default_factory=list)

    def last(self):
        return self.instrs[-1] if self.instrs else None


class FlowGraph:
    def __init__(self, blocks: List[BasicBlock]):
        self.blocks = blocks
        self.compute_edges()

    @property
    def entry(self):
        return self.blocks[0]

    def by_name(self) -> Dict[str, BasicBlock]:
        return {b.name: b for b in self.blocks}

    def compute_edges(self):
        for b in self.blocks:
            b.succ, b.pred = [], []
        for i, b in enumerate(self.blocks):
            last = b.last()
            fall = self.blocks[i + 1].name if i + 1 < len(self.blocks) else None
            if last is not None and last.op == 'halt':
                succ = []
            elif last is not None and last.op == 'goto':
                succ = [last.result]
            elif last is not None and last.is_cond_jump():
                succ = [fall, last.result] if fall != last.result else [fall]
            else:
                succ = [fall] if fall else []
            b.succ = [s for s in succ if s is not None]
        names = self.by_name()
        for b in self.blocks:
            for s in b.succ:
                names[s].pred.append(b.name)

    def reachable(self) -> Set[str]:
        names = self.by_name()
        seen, work = set(), [self.entry.name]
        while work:
            n = work.pop()
            if n not in seen:
                seen.add(n)
                work.extend(names[n].succ)
        return seen

    def instr_count(self):
        return sum(len(b.instrs) for b in self.blocks)

    def copy(self):
        return FlowGraph([BasicBlock(b.name, [copy.copy(q) for q in b.instrs]) for b in self.blocks])

    def format(self, show_edges=True):
        out = []
        for b in self.blocks:
            head = f"{b.name}:"
            if show_edges:
                head += f"{'':<6}; pred: {', '.join(b.pred) or '-'}   succ: {', '.join(b.succ) or '-'}"
            out.append(head)
            for q in b.instrs:
                out.append(f"    {q}")
        return '\n'.join(out)


def build_flow_graph(quads) -> FlowGraph:
    n = len(quads)
    leaders = {0}
    for i, q in enumerate(quads):
        if q.is_jump():
            leaders.add(q.result)
            if i + 1 < n:
                leaders.add(i + 1)
        elif q.op == 'halt' and i + 1 < n:
            leaders.add(i + 1)
    leaders = sorted(l for l in leaders if l < n)
    label_of = {l: f"B{k + 1}" for k, l in enumerate(leaders)}
    blocks = []
    for k, start in enumerate(leaders):
        end = leaders[k + 1] if k + 1 < len(leaders) else n
        instrs = []
        for q in quads[start:end]:
            q = copy.copy(q)
            if q.is_jump():
                q.result = label_of[q.result]
            instrs.append(q)
        blocks.append(BasicBlock(label_of[start], instrs))
    return FlowGraph(blocks)


def leaders_report(quads):
    """Human-readable list of leaders with the rule that made each one a leader."""
    reasons = {0: 'first instruction'}
    for i, q in enumerate(quads):
        if q.is_jump():
            reasons.setdefault(q.result, f'target of jump at {i}')
            if i + 1 < len(quads):
                reasons.setdefault(i + 1, f'follows jump at {i}')
    return ', '.join(f"{l} ({r})" for l, r in sorted(reasons.items()) if l < len(quads))


# ---------------- dominators and loops ----------------
def dominators(cfg: FlowGraph) -> Dict[str, Set[str]]:
    """Iterative data-flow algorithm: D(n) = {n} U intersection of D(p) for p in pred(n)."""
    reach = cfg.reachable()
    blocks = [b for b in cfg.blocks if b.name in reach]
    all_names = {b.name for b in blocks}
    dom = {b.name: set(all_names) for b in blocks}
    dom[cfg.entry.name] = {cfg.entry.name}
    changed = True
    while changed:
        changed = False
        for b in blocks:
            if b.name == cfg.entry.name:
                continue
            preds = [p for p in b.pred if p in reach]
            new = set.intersection(*(dom[p] for p in preds)) if preds else set()
            new = new | {b.name}
            if new != dom[b.name]:
                dom[b.name] = new
                changed = True
    return dom


def immediate_dominators(cfg, dom):
    idom = {}
    for n, ds in dom.items():
        strict = ds - {n}
        for d in strict:
            # d is the idom if every other strict dominator of n dominates d
            if all(o in dom[d] for o in strict):
                idom[n] = d
                break
    return idom


def natural_loops(cfg: FlowGraph, dom=None):
    """
    A back edge is an edge n -> h whose head h dominates its tail n.
    The natural loop of n -> h is h plus every block that can reach n without
    going through h. Loops sharing a header are merged.
    Returns a list of (header, set_of_blocks, back_edges) sorted inner-first.
    """
    dom = dom or dominators(cfg)
    names = cfg.by_name()
    loops = {}
    for b in cfg.blocks:
        if b.name not in dom:
            continue
        for h in b.succ:
            if h in dom[b.name]:
                body = {h, b.name}
                work = [b.name] if b.name != h else []
                while work:
                    m = work.pop()
                    for p in names[m].pred:
                        if p not in body and p in dom:
                            body.add(p)
                            work.append(p)
                if h in loops:
                    loops[h][0].update(body)
                    loops[h][1].append((b.name, h))
                else:
                    loops[h] = [body, [(b.name, h)]]
    result = [(h, body, edges) for h, (body, edges) in loops.items()]
    result.sort(key=lambda x: len(x[1]))
    return result


def liveness(cfg: FlowGraph, exit_live):
    """
    Live-variable analysis (backward data flow):
        out[B] = union of in[S] for successors S
        in[B]  = use[B] U (out[B] - def[B])
    `halt` is treated as reading every name in exit_live (observable final values).
    Returns (live_in, live_out).
    """
    def uses(q):
        return set(exit_live) if q.op == 'halt' else set(q.uses())

    live_in = {b.name: set() for b in cfg.blocks}
    live_out = {b.name: set() for b in cfg.blocks}
    changed = True
    while changed:
        changed = False
        for b in reversed(cfg.blocks):
            out = set().union(*(live_in[s] for s in b.succ)) if b.succ else set()
            live = set(out)
            for q in reversed(b.instrs):
                d = q.defines()
                if d:
                    live.discard(d)
                live |= uses(q)
            if out != live_out[b.name] or live != live_in[b.name]:
                live_out[b.name], live_in[b.name] = out, live
                changed = True
    return live_in, live_out
