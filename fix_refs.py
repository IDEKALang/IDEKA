#!/usr/bin/env python3
"""
fix_refs.py - repair Python module references after the f* -> i* rebrand.

Run from the compiler root. Scans the .py files in "." and "src/compiler".

Problem: the rebrand renamed the import statements, but only some of the
attribute uses (fast.X stayed in some files, became iast.X in others).

Fix: every file ends up using the NEW module names only.
  1. 'import iast as fast' (left by fix_imports.py) becomes 'import iast'
  2. fast.X, fbc.X, fparser.X ... in code (not strings, not comments) become
     iast.X, idkbc.X, iparser.X ...
  3. A name the file binds itself (a variable called fc, say) is left alone.

Then it checks every file: compiles, every module it uses is imported, and
every imported module resolves to a file. Modules that were mangled by the
rebrand (idkbceport.py, idkbclias.py) are renamed when something imports
the correct name and the file is missing.

Usage:
    python fix_refs.py --dry-run     report only
    python fix_refs.py               apply
"""

import ast
import importlib.util
import io
import os
import sys
import tokenize

SCAN_DIRS = (".", "src/compiler")

# new module -> old module, where the rule 'f' + stem[1:] does not hold
OVERRIDES = {
    "idkvm": "fvm",
    "idkvm_test": "fvm_test",
    "idkbc": "fbc",
    "idkc": "fxc",
    "ic": "fc",
    "ibc_report": "fbc_report",
    "ibc_alias": "fbc_alias",
}

# files the rebrand mangled: wrong name -> name the code imports
MANGLED = {
    "idkbceport": "ibc_report",
    "idkbclias": "ibc_alias",
}


def py_files():
    out = []
    for d in SCAN_DIRS:
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            if n.endswith(".py"):
                out.append(os.path.join(d, n))
    return out


def build_maps(files):
    new_to_old = dict(OVERRIDES)
    for p in files:
        stem = os.path.basename(p)[:-3]
        if stem in MANGLED:
            continue
        if stem.startswith("i") and stem not in new_to_old:
            new_to_old[stem] = "f" + stem[1:]
    old_to_new = {}
    for new, old in new_to_old.items():
        old_to_new[old] = new
    return old_to_new, new_to_old


def read(path):
    with open(path, "rb") as f:
        raw = f.read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    return raw[3:].decode("utf-8") if bom else raw.decode("utf-8"), bom


def write(path, text, bom):
    data = text.encode("utf-8")
    with open(path, "wb") as f:
        f.write((b"\xef\xbb\xbf" if bom else b"") + data)


def statement_starts_with_import(toks, i):
    """True when token i sits in a statement that begins with the word 'import'."""
    j = i - 1
    while j >= 0:
        t = toks[j]
        if t.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING):
            break
        if t.type == tokenize.OP and t.string == ";":
            break
        j -= 1
    k = j + 1
    while k < len(toks) and toks[k].type in (tokenize.NL, tokenize.COMMENT):
        k += 1
    return k < len(toks) and toks[k].type == tokenize.NAME and toks[k].string == "import"


def plan_edits(lines, old_to_new):
    """Return (edits, notes). An edit is (row, col_start, col_end, replacement)."""
    it = iter(lines)
    toks = list(tokenize.generate_tokens(lambda: next(it, "")))
    edits = []
    notes = []

    # names the file binds for itself
    bound = set()
    for i, t in enumerate(toks):
        if t.type != tokenize.NAME or t.string not in old_to_new:
            continue
        prev = toks[i - 1] if i > 0 else None
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if prev is not None and prev.type == tokenize.NAME and prev.string in (
                "def", "class", "for", "global", "nonlocal", "lambda"):
            bound.add(t.string)
        elif prev is not None and prev.type == tokenize.NAME and prev.string == "as":
            before = toks[i - 2] if i >= 2 else None
            is_import_alias = (before is not None and before.type == tokenize.NAME
                               and old_to_new.get(t.string) == before.string
                               and statement_starts_with_import(toks, i))
            if not is_import_alias:
                bound.add(t.string)
        elif nxt is not None and nxt.type == tokenize.OP and nxt.string in ("=", ":="):
            bound.add(t.string)

    for i, t in enumerate(toks):
        if t.type != tokenize.NAME:
            continue
        # 'import iast as fast'  ->  'import iast'
        if i + 2 < len(toks) and toks[i + 1].type == tokenize.NAME and toks[i + 1].string == "as":
            alias = toks[i + 2]
            if (alias.type == tokenize.NAME and old_to_new.get(alias.string) == t.string
                    and statement_starts_with_import(toks, i)):
                if t.end[0] == alias.end[0]:
                    edits.append((t.end[0], t.end[1], alias.end[1], ""))
                else:
                    notes.append(f"line {t.start[0]}: multi-line import alias left as is")
                continue
        # fast.X  ->  iast.X
        if t.string in old_to_new and t.string not in bound:
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            prev = toks[i - 1] if i > 0 else None
            if nxt is None or nxt.type != tokenize.OP or nxt.string != ".":
                continue
            if prev is not None and prev.type == tokenize.OP and prev.string == ".":
                continue
            edits.append((t.start[0], t.start[1], t.end[1], old_to_new[t.string]))
    for name in sorted(bound):
        notes.append(f"'{name}' is bound inside this file, its uses were left alone")
    return edits, notes


def apply_edits(lines, edits):
    lines = list(lines)
    for row, c0, c1, rep in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        ln = lines[row - 1]
        lines[row - 1] = ln[:c0] + rep + ln[c1:]
    return lines


def module_names_used(tree, new_names):
    used = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in new_names:
            used.add(n.value.id)
    return used


def names_bound_by_imports(tree):
    bound = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                bound.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name != "*":
                    bound.add(a.asname or a.name)
    return bound


def imported_modules(tree):
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            mods.add(n.module.split(".")[0])
    return mods


def resolvable(name):
    if name in sys.stdlib_module_names:
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def main():
    dry = "--dry-run" in sys.argv[1:]
    files = py_files()
    if not files:
        print("No .py files found. Run this from the compiler root.")
        return 1
    for d in SCAN_DIRS:
        if os.path.isdir(d):
            sys.path.insert(0, os.path.abspath(d))

    old_to_new, new_to_old = build_maps(files)
    new_names = set(new_to_old)
    problems = 0
    changed_files = 0

    for p in files:
        text, bom = read(p)
        lines = io.StringIO(text, newline="").readlines()
        try:
            edits, notes = plan_edits(lines, old_to_new)
        except (tokenize.TokenError, SyntaxError, IndentationError) as e:
            print(f"{p}: cannot tokenize: {e}")
            problems += 1
            continue
        if edits:
            changed_files += 1
            nrename = sum(1 for e in edits if e[3])
            ndrop = len(edits) - nrename
            print(f"{p}: {nrename} use(s) renamed, {ndrop} import alias(es) removed")
            if not dry:
                write(p, "".join(apply_edits(lines, edits)), bom)
        for n in notes:
            print(f"{p}: note: {n}")

    # verification on the files as they now are (as they would be after a dry run too)
    print()
    missing_modules = {}
    for p in files:
        text, bom = read(p)
        if dry:
            lines = io.StringIO(text, newline="").readlines()
            edits, _ = plan_edits(lines, old_to_new)
            text = "".join(apply_edits(lines, edits))
        try:
            tree = ast.parse(text, filename=p)
        except SyntaxError as e:
            print(f"{p}: does not compile: {e}")
            problems += 1
            continue
        used = module_names_used(tree, new_names)
        bound = names_bound_by_imports(tree)
        for name in sorted(used - bound):
            print(f"{p}: uses '{name}.' but never imports it")
            problems += 1
        for name in sorted(imported_modules(tree)):
            if not resolvable(name):
                missing_modules.setdefault(name, []).append(p)

    # rebrand-mangled file names
    for wrong, right in MANGLED.items():
        src = None
        for d in SCAN_DIRS:
            cand = os.path.join(d, wrong + ".py")
            if os.path.exists(cand):
                src = cand
        if src is None or right not in missing_modules:
            continue
        dst = os.path.join(os.path.dirname(src), right + ".py")
        if os.path.exists(dst):
            continue
        print(f"{src} -> {dst}   (imported as '{right}')")
        if not dry:
            os.rename(src, dst)
        del missing_modules[right]

    for name, where in sorted(missing_modules.items()):
        print(f"import '{name}' resolves to nothing, imported by: {', '.join(sorted(set(where)))}")
        problems += 1

    print()
    print(f"{changed_files} file(s) {'would change' if dry else 'changed'}, {problems} problem(s) left")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
