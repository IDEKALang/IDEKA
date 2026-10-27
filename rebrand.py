#!/usr/bin/env python3
"""
rebrand.py - Flux -> IDEKA rebrand. Plain string replacement, no regex.

Run from the compiler root:

    python rebrand.py [--dry-run]

Contents of every text file and the names of files and directories are rewritten.
Compiler files named f*.fx / f*.py become i*.idk / i*.py (fparser.fx -> iparser.idk,
fparser.py -> iparser.py), every other .fx becomes .idk, and the Python import
statements of the f* modules follow (import fparser -> import iparser).
"""

import os
import sys

SKIP_DIRS = {".git", "build", "__pycache__", ".venv", "node_modules"}

# Where the f* compiler files live (relative to the root). "." covers fxc.fx, fxc.py, fvm.py ...
COMPILER_DIRS = [
    ".",
    os.path.join("src", "compiler"),
    os.path.join("src", "compiler", "v1.5.4", "core"),
    os.path.join("src", "compiler", "v1.5.4", "entrypoint"),
]

# Order matters: specific before general.
KEYWORDS = [
    ("emitflux", "emitideka"),
    ("fluxvm",   "idkvm"),
    ("FLUXC",    "IDEKA"),
    ("FLUX",     "IDEKA"),
    ("Flux",     "IDEKA"),
    ("flux",     "IDEKA"),
    ("fxc",      "idkc"),
    ("FXC",      "IDKC"),
]

EXTENSION = (".fx", ".idk")        # applied after everything else

# Module stems that do not follow the plain f -> i rule
STEM_OVERRIDES = {
    "fvm":      "idkvm",
    "fvm_test": "idkvm_test",
    "fbc":      "idkbc",
}

COMPILER_EXTS = (".fx", ".py")


def swap(text, pairs):
    for old, new in pairs:
        text = text.replace(old, new)
    return text


def new_stem(stem):
    if stem in STEM_OVERRIDES:
        return STEM_OVERRIDES[stem]
    renamed = swap(stem, KEYWORDS)
    if renamed == stem:
        renamed = "i" + stem[1:]
    return renamed


def new_file_name(name):
    """The renamed form of a compiler f*.fx or f*.py file name."""
    for ext in COMPILER_EXTS:
        if name.endswith(ext):
            stem = name[:-len(ext)]
            return new_stem(stem) + (EXTENSION[1] if ext == EXTENSION[0] else ext)
    return name


def find_compiler_files(root):
    """(old, new) for every f*.fx and f*.py in the compiler directories."""
    pairs = []
    seen = set()
    for d in COMPILER_DIRS:
        folder = os.path.join(root, d)
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if not name.startswith("f") or not name.endswith(COMPILER_EXTS):
                continue
            if name in seen or not os.path.isfile(os.path.join(folder, name)):
                continue
            seen.add(name)
            pairs.append((name, new_file_name(name)))
    # longest first so a longer name is never clobbered by a shorter one it contains
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def module_map(file_pairs):
    """Python module name -> new module name."""
    mods = {}
    for old, new in file_pairs:
        if old.endswith(".py"):
            mods[old[:-3]] = new[:-3]
    return mods


def fix_module(name, mods):
    head, dot, tail = name.partition(".")
    return mods.get(head, head) + dot + tail


def rewrite_import_line(line, mods):
    """import a, b as c / from a.b import c, with the module names renamed."""
    end = line[len(line.rstrip("\r\n")):]
    body = line[:len(line) - len(end)]
    comment = ""
    cut = body.find("#")
    if cut >= 0:
        comment = body[cut:]
        body = body[:cut]
    stripped = body.lstrip()
    indent = body[:len(body) - len(stripped)]

    if stripped.startswith("from "):
        rest = stripped[5:]
        sp = rest.find(" ")
        if sp < 0:
            return line
        return indent + "from " + fix_module(rest[:sp], mods) + rest[sp:] + comment + end

    if stripped.startswith("import "):
        items = stripped[7:].split(",")
        out = []
        for item in items:
            lead = item[:len(item) - len(item.lstrip())]
            trail = item[len(item.rstrip()):]
            core = item.strip()
            name, sep, alias = core.partition(" as ")
            out.append(lead + fix_module(name, mods) + sep + alias + trail)
        return indent + "import " + ",".join(out) + comment + end

    return line


def rewrite_python(text, mods):
    lines = text.splitlines(True)
    for i in range(len(lines)):
        lines[i] = rewrite_import_line(lines[i], mods)
    text = "".join(lines)
    # dynamic imports with a literal module name
    dynamic = []
    for old, new in mods.items():
        for call in ("__import__", "import_module"):
            for q in ('"', "'"):
                dynamic.append((call + "(" + q + old + q + ")", call + "(" + q + new + q + ")"))
    return swap(text, dynamic)


def walk_files(root, self_path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.abspath(path) != self_path:
                yield path


def rewrite_contents(root, pairs, mods, dry, self_path):
    changed = 0
    for path in walk_files(root, self_path):
        try:
            with open(path, "r", encoding="utf-8", newline="") as f:
                text = f.read()
        except (UnicodeDecodeError, OSError):
            continue                       # binary or unreadable
        out = text
        if path.endswith(".py"):
            out = rewrite_python(out, mods)
        out = swap(out, pairs)
        if out != text:
            changed += 1
            print("edit    " + os.path.relpath(path, root))
            if not dry:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(out)
    return changed


def rename_paths(root, file_pairs, dry):
    renamed = 0
    # bottom-up so a directory is renamed after the files inside it
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        parts = os.path.relpath(dirpath, root).split(os.sep)
        if any(p in SKIP_DIRS for p in parts):
            continue
        for name in filenames + dirnames:
            target = None
            for old, new in file_pairs:
                if name == old:
                    target = new
                    break
            if target is None:
                target = swap(swap(name, KEYWORDS), [EXTENSION])
            if target != name:
                src = os.path.join(dirpath, name)
                dst = os.path.join(dirpath, target)
                print("rename  " + os.path.relpath(src, root) + " -> " + target)
                if not dry:
                    if os.path.exists(dst):
                        print("  skipped, target exists")
                        continue
                    os.rename(src, dst)
                renamed += 1
    return renamed


def main():
    dry = "--dry-run" in sys.argv
    root = os.getcwd()
    self_path = os.path.abspath(__file__)

    file_pairs = find_compiler_files(root)
    mods = module_map(file_pairs)
    # f* file name references first, then the keyword rules, then the extension
    content_pairs = file_pairs + KEYWORDS + [EXTENSION]

    edited = rewrite_contents(root, content_pairs, mods, dry, self_path)
    renamed = rename_paths(root, file_pairs, dry)

    print()
    print(("Would edit " if dry else "Edited ") + str(edited) + " file(s), "
          + ("would rename " if dry else "renamed ") + str(renamed) + " path(s).")


if __name__ == "__main__":
    main()