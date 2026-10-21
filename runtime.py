"""
runtime.py - Module 3: Run-time environment (storage organization & allocation).

The program's memory, as laid out by this compiler:

    +---------------------------+  low addresses
    | Code      (target code)   |  fixed size, known after code generation
    +---------------------------+
    | Static    (all variables) |  STATIC allocation: every variable has a fixed
    |                           |  offset decided at compile time (symbol table)
    +---------------------------+
    | Temporaries spill area    |  temporaries that did not fit in registers
    +---------------------------+
    | Heap   (unused)           |  the language has no dynamic data
    |            ...            |
    | Stack  (grows downward)   |  STACK allocation: one activation record per
    +---------------------------+  call of a built-in function     high addresses

Activation record pushed by CALL (call-by-value parameter passing):

    +--------------------+
    | actual parameter   |  value copied in by PUSH  (call by value)
    | returned value     |  callee writes it, caller reads it from register RV
    | control link       |  frame pointer of the caller (dynamic link)
    | return address     |  instruction after the CALL
    +--------------------+

The language has no user-defined procedures and no recursion, so there are no
access links (no nested scopes) and the stack never holds more than one frame.
The simulator in vm.py really builds these frames on a stack while it runs.
"""


def storage_report(symtab, code_size=None, spilled=()):
    lines = ["Storage organization:"]
    lines.append(f"  Code area      : {code_size if code_size is not None else '?'} instructions")
    vars_ = symtab.variables()
    lines.append(f"  Static area    : {symtab.static_size} bytes for {len(vars_)} variable(s)")
    for s in vars_:
        lines.append(f"      [{s.offset:>3} .. {s.offset + s.width - 1:>3}]  {s.name:<10} {s.type}")
    spilled = sorted(spilled)
    if spilled:
        lines.append(f"  Temporaries    : {len(spilled)} spilled to memory: {', '.join(spilled)}")
    else:
        lines.append("  Temporaries    : all kept in registers")
    lines.append("  Heap           : not used (no dynamic data structures)")
    lines.append("  Stack          : one activation record per built-in call "
                 "[param | return value | control link | return address], call-by-value")
    return '\n'.join(lines)
