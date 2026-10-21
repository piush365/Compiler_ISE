"""
ssa.py - Module 4: Static Single Assignment form.

In SSA every name is assigned exactly once. Each assignment to x creates a new
version x1, x2, ...; where control flow merges, a phi-function picks the
version coming from the predecessor that was actually executed:

    x3 = phi(B2: x1, B5: x2)

Construction (Cytron et al.):
  1. dominators -> immediate dominators -> dominator tree
  2. dominance frontier DF(n): blocks where n's dominance stops
  3. place phi(x) in the iterated dominance frontier of every block defining x,
     but only for "global" names - names read in some block before being
     written there (semi-pruned SSA, Briggs et al.). Temporaries never live
     across blocks, so they never need phis.
  4. rename: walk the dominator tree keeping a stack of current versions per name
Versions are written x_1, x_2, ...; version 0 (x_0) means "the value x had on entry" (never assigned on that path).

Uses: SSA makes def-use chains explicit, which simplifies constant propagation,
dead-code elimination and value numbering. Here it is shown for study; the
optimizer works on ordinary TAC, and run_ssa() executes the SSA form to prove
it is equivalent.
"""
import copy
from cfg import dominators, immediate_dominators
from ops import fmt_value
from interpreter import _exec_instr, _Budget, MAX_STEPS, ZERO


class Phi:
    op = 'phi'

    def __init__(self, var, preds):
        self.var = var
        self.result = var
        self.args = {p: var for p in preds}    # pred block -> incoming version

    def __str__(self):
        args = ', '.join(f"{p}: {v}" for p, v in self.args.items())
        return f"{self.result} = phi({args})"


def dominance_frontiers(cfg, idom):
    df = {n: set() for n in idom.keys() | {cfg.entry.name}}
    names = cfg.by_name()
    for n in df:
        preds = [p for p in names[n].pred if p in df]
        if len(preds) >= 2:
            for p in preds:
                runner = p
                while runner != idom.get(n) and runner is not None:
                    df[runner].add(n)
                    runner = idom.get(runner)
    return df


class SSAForm:
    def __init__(self, cfg, user_vars=()):
        self.user_vars = set(user_vars)
        self.cfg = cfg.copy()
        # SSA is built on reachable blocks only
        reach = self.cfg.reachable()
        self.cfg.blocks = [b for b in self.cfg.blocks if b.name in reach]
        self.cfg.compute_edges()
        self.dom = dominators(self.cfg)
        self.idom = immediate_dominators(self.cfg, self.dom)
        self.df = dominance_frontiers(self.cfg, self.idom)
        self.final_names = {}
        self._place_phis()
        self._rename()

    def _place_phis(self):
        names = self.cfg.by_name()
        defsites, global_names = {}, set()
        for b in self.cfg.blocks:
            killed = set()
            for q in b.instrs:
                used = self.user_vars if q.op == 'halt' else q.uses()   # final values are read at exit
                global_names.update(u for u in used if u not in killed)
                d = q.defines()
                if d:
                    killed.add(d)
                    defsites.setdefault(d, set()).add(b.name)
        defsites = {v: s for v, s in defsites.items() if v in global_names}
        self.phis = {b.name: {} for b in self.cfg.blocks}
        for v, sites in defsites.items():
            work, has_phi = list(sites), set()
            while work:
                n = work.pop()
                for y in self.df.get(n, ()):
                    if y not in has_phi:
                        self.phis[y][v] = Phi(v, names[y].pred)
                        has_phi.add(y)
                        if y not in sites:
                            work.append(y)

    def _rename(self):
        names = self.cfg.by_name()
        children = {b.name: [] for b in self.cfg.blocks}
        for n, d in self.idom.items():
            children[d].append(n)
        counter, stacks = {}, {}

        def top(v):
            return stacks[v][-1] if stacks.get(v) else f"{v}_0"

        def new(v):
            counter[v] = counter.get(v, 0) + 1
            name = f"{v}_{counter[v]}"
            stacks.setdefault(v, []).append(name)
            return name

        def walk(bname):
            pushed = []
            block = names[bname]
            for v, phi in self.phis[bname].items():
                phi.result = new(v)
                pushed.append(v)
            new_instrs = []
            for q in block.instrs:
                q = copy.copy(q)
                if q.op != 'call':
                    if isinstance(q.arg1, str):
                        q.arg1 = top(q.arg1)
                    if isinstance(q.arg2, str):
                        q.arg2 = top(q.arg2)
                d = q.defines()
                if d:
                    q.result = new(d)
                    pushed.append(d)
                if q.op == 'halt':
                    self.final_names = {v: top(v) for v in stacks}
                new_instrs.append(q)
            block.instrs = new_instrs
            for s in block.succ:
                for v, phi in self.phis[s].items():
                    phi.args[bname] = top(v)
            for c in children[bname]:
                walk(c)
            for v in pushed:
                stacks[v].pop()

        walk(self.cfg.entry.name)
        for b in self.cfg.blocks:
            b.instrs = list(self.phis[b.name].values()) + b.instrs

    def format(self):
        out = ["Dominator tree (immediate dominators): " +
               ', '.join(f"idom({n})={d}" for n, d in sorted(self.idom.items(), key=lambda x: int(x[0][1:])))]
        out.append("Dominance frontiers: " + ', '.join(
            f"DF({n})={{{', '.join(sorted(s, key=lambda x: int(x[1:])))}}}"
            for n, s in sorted(self.df.items(), key=lambda x: int(x[0][1:])) if s))
        out.append(self.cfg.format(show_edges=False))
        return '\n'.join(out)


def run_ssa(ssa: SSAForm, symtab, max_steps=MAX_STEPS):
    """Execute SSA code: phis are evaluated (in parallel) according to the predecessor."""
    blocks = ssa.cfg.blocks
    order = [b.name for b in blocks]
    env, out, params = {f"{v.name}_0": ZERO[v.type] for v in symtab.variables()}, [], []
    budget = _Budget(max_steps)
    bi, prev = 0, None
    while True:
        block = blocks[bi]
        phis = [q for q in block.instrs if isinstance(q, Phi)]
        # coming from program start (prev None) a phi reads the initial version x_0
        vals = {p.result: env.get(p.args.get(prev, f"{p.var}_0")) for p in phis}
        env.update(vals)
        jumped = False
        for q in block.instrs:
            if isinstance(q, Phi):
                continue
            if q.op == 'halt':
                final = {v.name: env[ssa.final_names.get(v.name, v.name + '_0')] for v in symtab.variables()}
                return out, final
            budget.tick()
            taken = _exec_instr(q, env, out, params)
            if taken:
                prev, bi, jumped = block.name, order.index(q.result), True
                break
        if not jumped:
            prev, bi = block.name, bi + 1
