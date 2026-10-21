"""
peephole.py - Module 6: Peephole optimization of the target code.

A small window slides over the instructions and replaces patterns with shorter
or faster ones, repeating until nothing changes:

  * redundant loads and stores   ST x, R ; LD R, x      ->  ST x, R
                                 LD R, x ; ST x, R      ->  LD R, x
  * useless moves                MOV R, R               ->  (deleted)
  * algebraic simplification     SUB R, R, #0 / MUL R, R, #1 / DIV R, R, #1 -> (deleted)
  * machine idioms               ADD R, R, #1 -> INC R ;  SUB R, R, #1 -> DEC R
  * flow-of-control              BR L where L is the next instruction -> deleted
                                 BR L1 ... L1: BR L2   ->  BR L2   (jump chaining)
  * unreachable code             instructions after BR / HALT up to the next label
  * unused labels                labels no branch refers to

A label between two instructions means another path can arrive there, so the
"redundant load" patterns never look across a label.
"""
from collections import Counter
from target import MInstr, Imm, Lbl, JUMPS


def _is_imm(a, v):
    return isinstance(a, Imm) and not isinstance(a.value, bool) and type(a.value) is int and a.value == v


def peephole(code):
    code = [MInstr(i.op, list(i.args)) for i in code]     # never modify the caller's code
    stats = Counter()
    changed = True
    while changed:
        changed = False
        out = []
        i = 0
        while i < len(code):
            ins = code[i]
            prev = out[-1] if out else None
            # redundant load after store / store after load of the same location
            if prev is not None and ins.op == 'LD' and prev.op == 'ST' and \
                    not isinstance(ins.args[1], Imm) and ins.args[1] == prev.args[0] and ins.args[0] == prev.args[1]:
                stats['redundant load removed'] += 1
                i += 1; changed = True; continue
            if prev is not None and ins.op == 'ST' and prev.op == 'LD' and \
                    not isinstance(prev.args[1], Imm) and prev.args[1] == ins.args[0] and prev.args[0] == ins.args[1]:
                stats['redundant store removed'] += 1
                i += 1; changed = True; continue
            if ins.op == 'MOV' and ins.args[0] == ins.args[1]:
                stats['useless move removed'] += 1
                i += 1; changed = True; continue
            if ins.op in ('SUB', 'MUL', 'DIV') and ins.args[0] == ins.args[1] and \
                    _is_imm(ins.args[2], 0 if ins.op == 'SUB' else 1):
                stats['algebraic identity removed'] += 1
                i += 1; changed = True; continue
            if ins.op in ('ADD', 'SUB') and ins.args[0] == ins.args[1] and _is_imm(ins.args[2], 1):
                out.append(MInstr('INC' if ins.op == 'ADD' else 'DEC', [ins.args[0]]))
                stats['machine idiom (INC/DEC)'] += 1
                i += 1; changed = True; continue
            # unreachable code after an unconditional jump / halt
            if prev is not None and prev.op in ('BR', 'HALT') and ins.op != 'LABEL':
                stats['unreachable instruction removed'] += 1
                i += 1; changed = True; continue
            out.append(ins)
            i += 1
        code = out

        # jump to the immediately following label
        labels_at = {}
        for idx, ins in enumerate(code):
            if ins.op == 'LABEL':
                labels_at[ins.args[0]] = idx
        out = []
        for idx, ins in enumerate(code):
            if ins.op == 'BR':
                j = idx + 1
                following = set()
                while j < len(code) and code[j].op == 'LABEL':
                    following.add(code[j].args[0]); j += 1
                if ins.args[0].name in following:
                    stats['jump to next removed'] += 1
                    changed = True
                    continue
            out.append(ins)
        code = out

        # jump chaining: a branch to a label whose first instruction is BR L2
        labels_at = {ins.args[0]: idx for idx, ins in enumerate(code) if ins.op == 'LABEL'}

        def final_target(name, seen):
            j = labels_at[name] + 1
            while j < len(code) and code[j].op == 'LABEL':
                j += 1
            if j < len(code) and code[j].op == 'BR' and code[j].args[0].name not in seen:
                return final_target(code[j].args[0].name, seen | {name})
            return name

        for ins in code:
            if ins.op in JUMPS:
                t = final_target(ins.args[-1].name, {ins.args[-1].name})
                if t != ins.args[-1].name:
                    ins.args[-1] = Lbl(t)
                    stats['jump chaining'] += 1
                    changed = True

        # unused labels
        used = {ins.args[-1].name for ins in code if ins.op in JUMPS}
        before = len(code)
        code = [ins for ins in code if not (ins.op == 'LABEL' and ins.args[0] not in used)]
        if len(code) != before:
            stats['unused label removed'] += before - len(code)
            changed = True
    return code, stats
