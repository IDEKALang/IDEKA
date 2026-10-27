# IDEKA Borrow Checker (FBC) — Complete Reference

**Source file:** `fbc.py`  
**Copyright:** 2026 Karac V. Thweatt  
**Role:** Static pointer safety analysis for the IDEKA programming language.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Getting Started](#3-getting-started)
4. [Analysis Passes](#4-analysis-passes)
5. [The Call Graph (`CallGraph`)](#5-the-call-graph-callgraph)
6. [The Borrow Checker (`BorrowChecker`)](#6-the-borrow-checker-borrowchecker)
7. [Allocation Site Tracking](#7-allocation-site-tracking)
8. [Variable Declaration Analysis](#8-variable-declaration-analysis)
9. [Assignment Analysis](#9-assignment-analysis)
10. [Expression Walking](#10-expression-walking)
11. [Statement Walking](#11-statement-walking)
12. [Thread Safety Analysis](#12-thread-safety-analysis)
13. [Heap Leak Analysis](#13-heap-leak-analysis)
14. [Site Resolution](#14-site-resolution)
15. [Source Line Remapping](#15-source-line-remapping)
16. [Companion Modules](#16-companion-modules)
17. [Helper Functions](#17-helper-functions)
18. [File Parsing](#18-file-parsing)
19. [CLI Reference](#19-cli-reference)
20. [Exit Codes](#20-exit-codes)
21. [Integrating FBC Programmatically](#21-integrating-fbc-programmatically)
22. [Limitations and Design Notes](#22-limitations-and-design-notes)

---

## 1. Overview

The IDEKA Borrow Checker (`fbc.py`) is a standalone static analysis tool that performs pointer safety checks on IDEKA (`.idk`) source files. It is not part of the compiler's hot path — it is run separately, either by a developer or in CI, to catch memory safety bugs before they reach runtime.

**What it checks (by default):**

- **Pointer aliasing violations** — two mutable pointers aliasing the same memory site simultaneously.
- **Scope escapes** — a pointer to a stack-allocated variable outliving the scope that owns the stack frame.

**Optional checks (via flags):**

- **Thread safety** (`--threads`) — a pointer captured into a spawned thread while also accessible from the spawning scope.
- **Heap leaks** (`--leaks`) — an `fmalloc` allocation that has no matching `ffree` before the end of the function scope.

**What it does NOT check:**

- Data races on non-pointer types.

**What it needs to work:**  
- No changes to your source program  
- No lifetime annotation  
- Simply add `--borrowcheck` to the command line (blocking)  
- Use `--borrowcheck-warn` for non-blocking checks

---

## 2. Architecture

```
 CLI args
    │
    ▼
collect_fx_files()
    │  one or more .idk paths
    ▼
parse_file()  ──────────────────────────────────────────────────────────┐
    │  FXPreprocessor → IDEKALexer → IDEKAParser → fast.Program           │
    │                                                                   │
    ▼                                                              line_map[]
CallGraph.collect()
    │  walks fast.Program, indexes FunctionDef nodes by mangled name
    ▼
BorrowChecker.run()
    │  starts from entry point (default: FRTStartup)
    │
    ├── _check_function()   ← called recursively via call graph
    │       │
    │       ├── AliasMap.push_scope()      ← scope stack frame
    │       ├── _walk_block() / _walk_stmt() / _walk_expr()
    │       │       │
    │       │       ├── AliasMap.declare_ptr()    ← new pointer variable
    │       │       ├── AliasMap.assign_ptr()     ← pointer reassignment
    │       │       ├── AliasMap.record_malloc()  ← fmalloc site
    │       │       ├── AliasMap.record_free()    ← ffree site
    │       │       └── AliasMap.check_thread_escape() / check_use_after_escape()
    │       │
    │       ├── AliasMap.check_heap_leaks()  (if --leaks)
    │       └── AliasMap.pop_scope()
    │
    └── violations[]  ─── line remapping ──► print_violations() / print_summary()
```

**Core components:**

| Class / Module | Responsibility |
|---|---|
| `CallGraph` | Collects and indexes all `FunctionDef` nodes from the AST; resolves call targets including mangled names, short names, and overloads. |
| `BorrowChecker` | Drives the analysis: walks the call graph from the entry point, traverses each function's AST, and delegates pointer tracking to `AliasMap`. |
| `AliasMap` *(fbc_alias)* | Tracks live pointer variables and their allocation sites; detects aliasing violations, scope escapes, thread escapes, and heap leaks. |
| `Violation` *(fbc_alias)* | Data class representing a single detected violation with kind, message, file, line, and detail list. |
| `print_violations` / `print_summary` *(fbc_report)* | Render violations to stderr as coloured human-readable text or machine-readable JSON. |

---

## 3. Getting Started

### Installation requirements

`fbc.py` must be run from the project root alongside `idkc.py`. It discovers the compiler modules automatically:

```
<project_root>/
  fbc.py
  idkc.py
  src/compiler/       ← preferred location
    fparser.py
    flexer.py
    fpreprocess.py
    fmacros.py
    fast.py
    ftypesys.py
  fbc_alias.py        ← required companion
  fbc_report.py       ← required companion
```

The path search order is `src/compiler/`, then `compiler/`, then the project root itself.

### Basic usage

```
python fbc.py <file_or_directory> [options]
```

**Check a single file:**
```
python fbc.py src/main.idk
```

**Check all .idk files in a directory:**
```
python fbc.py src/
```

**Full analysis with all checks:**
```
python fbc.py src/ --threads --leaks
```

**CI mode (JSON output, fail on violation):**
```
python fbc.py src/ --json
echo "Exit: $?"
```

**Treat violations as warnings (never exit 1):**
```
python fbc.py src/ --warn
```

---

## 4. Analysis Passes

The FBC makes a single forward pass through the call graph starting from the entry point. The pass is **interprocedural** in both reachability and alias identity: argument sites from the caller are propagated into the callee's parameter slots, so alias checking operates on real site identities across call boundaries.

**Pass ordering:**

1. **Parse** -- all `.idk` files are preprocessed and parsed into ASTs.
2. **Collect** -- the call graph is built by indexing all `FunctionDef` nodes.
3. **Check** -- `BorrowChecker.run()` starts at the entry point and recursively visits every reachable function. Each function may be analysed multiple times if it is called with different argument site combinations (call contexts); it is only re-analysed when a new distinct context is seen.
4. **Report** -- accumulated violations are line-remapped and printed.

Each function analysis follows this sequence:

1. Push a new scope frame onto `AliasMap`.
2. Register all pointer parameters: if the caller supplied a resolved site for a parameter, use that site; otherwise fall back to the opaque `param:<func>:<name>` site.
3. Walk the function body statement by statement.
4. On scope exit, optionally check for heap leaks.
5. Pop the scope frame.
6. Remap merged line numbers to original source locations and collect violations.

**Call-context sensitivity** -- a call context is a tuple of site strings, one per pointer parameter of the callee in declaration order, derived from the argument expressions at the call site using the caller's current alias state. The callee is re-entered only when a new distinct context tuple is seen. This bounds the analysis: the number of distinct sites is finite and each context tuple is bounded by the callee's pointer-parameter count.

---

## 5. The Call Graph (`CallGraph`)

```python
class CallGraph:
    funcs:       dict[str, FunctionDef]          # mangled name -> FunctionDef
    short_names: dict[str, str]                  # short name -> mangled name (unique only)
    overloads:   dict[str, list]                 # base name -> [mangled names]
    visited_main:   dict[str, set[tuple]]        # func_name -> set of call-context tuples analysed (main context)
    visited_thread: dict[str, set[tuple]]        # func_name -> set of call-context tuples analysed (thread context)
```

`is_visited(name, ctx, thread)` returns `True` if the `(name, ctx)` pair has already been analysed in the given context. `mark_visited(name, ctx, thread)` records it. The `.visited` property returns the set of function names that have been entered in at least one context (for backward compatibility).

### `CallGraph.collect(program: fast.Program)`

Walks the top-level `fast.Program` and registers every non-prototype `FunctionDef`. After collection, it builds two auxiliary indexes:

**Short name index** (`short_names`) — maps the last segment of a mangled name (after the final `__`) to the full mangled name, but only when that short name is unambiguous (appears exactly once).

**Overload index** (`overloads`) — maps the base name (everything before the first all-digit arity segment in the mangled name) to a list of all mangled variants. For example, a function mangled as `main__0__ret_intE1` has base `main`.

### Name mangling scheme

FBC uses the same name mangling as the IDEKA compiler:

| Source location | Mangled name |
|---|---|
| Top-level `func foo` | `foo` |
| Namespace `ns`, function `foo` | `ns__foo` |
| Nested namespace `ns::sub`, function `foo` | `ns__sub__foo` |
| Object `Obj` in namespace `ns`, method `bar` | `ns__Obj__bar` |
| Overloaded function (arity segment) | `foo__0__ret_intE1` |

### Call resolution

When `BorrowChecker` encounters a `FunctionCall` node, it resolves the callee in this order:

1. Exact match in `cg.funcs`.
2. Short name lookup in `cg.short_names` (for unambiguous single-match functions).
3. Overload lookup in `cg.overloads` (all overloads of that base name are checked).

If none resolve (extern, intrinsic, or library call), the call is silently skipped for traversal purposes (no violation is generated for the call itself).

### Collected node types

| AST Node | Action |
|---|---|
| `fast.FunctionDef` | Registered directly under its `node.name`. |
| `fast.FunctionDefStatement` | Unwrapped, then the inner `FunctionDef` is registered. |
| `fast.NamespaceDef` | Functions registered as `<prefix>__<func.name>`; nested namespaces and objects recurse. |
| `fast.NamespaceDefStatement` | Unwrapped, then the inner `NamespaceDef` is processed. |
| `fast.ObjectDef` | Methods registered as `<prefix>__<obj.name>__<method.name>`. Nested objects recurse. |
| `fast.ObjectDefStatement` | Unwrapped, then the inner `ObjectDef` is processed. |
| `fast.ExportBlock` | Each non-prototype definition inside is registered directly. |
| `fast.ExternBlock`, `fast.StructDef`, `fast.StructDefStatement` | Skipped (no function bodies to register). |

---

## 6. The Borrow Checker (`BorrowChecker`)

```python
class BorrowChecker:
    def __init__(
        self,
        call_graph:    CallGraph,
        entry:         str,
        check_threads: bool = False,
        check_leaks:   bool = False,
        line_map:      list = None,
    ): ...
```

| Parameter | Description |
|---|---|
| `call_graph` | The populated `CallGraph` instance. |
| `entry` | Name of the entry point function (default `FRTStartup`). If not found, all reachable functions are checked instead with a warning. |
| `check_threads` | Enable thread safety analysis. |
| `check_leaks` | Enable heap leak analysis. |
| `line_map` | Preprocessor line map from `FXPreprocessor.line_map` — a list of `(filename, original_1based_line)` tuples, one per merged source line. Used to map merged line numbers back to original file locations in violation reports. |

**Public attributes after `run()`:**

| Attribute | Type | Description |
|---|---|---|
| `violations` | `list[Violation]` | All detected violations, with file/line remapped to original source locations. |
| `funcs_checked` | `int` | Count of functions that were actually analysed (not prototypes, not skipped). |

### `BorrowChecker.run()`

Entry point for analysis. Looks up `self.entry` in `cg.funcs` and calls `_check_function()`. If the entry point is not found (commonly because its body is inside an unresolved `#ifdef`), it falls back to checking all functions in the call graph.

### `BorrowChecker._check_function(func, thread_context, call_ctx)`

Analyses one function. Guards against re-entry via `(func.name, call_ctx)` in the appropriate visited table. Steps:

1. Mark `(func.name, call_ctx)` as visited.
2. Switch `AliasMap.func_name` to this function's name.
3. Push a new scope frame.
4. Register pointer parameters: if the caller supplied a resolved site at the corresponding positional index in `call_ctx`, use that site; otherwise use the opaque `param:<func>:<name>` fallback.
5. Walk the function body with `_walk_block()`.
6. Optionally check heap leaks (unless this function is a recognised allocator wrapper).
7. Pop the scope frame.
8. Remap and collect all violations accumulated in `AliasMap`.

### Allocator wrapper detection (`_func_returns_allocation`)

A function is considered an allocator wrapper — meaning that `fmalloc` calls inside it transfer ownership to the caller and do not count as leaks — if:

- Its name is `fmalloc` or `ffree`.
- Its body is a single `return fmalloc(...)` statement (optionally wrapped in a cast).
- Its body is a single `return someAllocFunc(...)` where the function name contains `malloc` or `alloc`.

When a function is identified as an allocator wrapper, `alias.heap_sites` is simply cleared rather than checked.

---

## 7. Allocation Site Tracking

The FBC identifies memory by **site strings** — stable identifiers for where a particular allocation or variable lives. Sites are the core identity used by `AliasMap` to detect when two pointers refer to the same memory.

### Site formats

| Format | Constructor | Meaning |
|---|---|---|
| `stack:<func>:<var>@<line>` | `_make_stack_site(func, var, line)` | Address of a stack-allocated variable `var` in function `func`, declared at `line`. |
| `heap:<func>:<line>` | `_make_heap_site(func, line)` | Result of an `fmalloc()` call at `line` inside `func`. |
| `param:<func>:<param>` | `_make_param_site(func, param)` | A pointer parameter `param` passed into `func` from the caller. |
| `derived:<base_site>` | inline in `_resolve_site` | A pointer derived from `<base_site>` via cast, type-convert, or pointer arithmetic. Treated as a distinct alias to avoid spurious aliasing with the original. |
| `unknown` | inline | Site could not be determined statically or via FVM execution (e.g. a value only known at program runtime). |

---

## 8. Variable Declaration Analysis

`_on_var_decl(node: fast.VariableDeclaration)` handles `VarDecl` statements.

**For every variable**, a `stack:<func>:<var>@<line>` site is registered in the current scope frame's `var_sites` and `owned_sites` so that `@varName` (address-of) expressions can later be resolved to this site.

**If the variable is a pointer type** (determined by `_is_pointer_type(node.type_spec)`), the declaration additionally:

1. Calls `_resolve_site()` on the initial value expression to determine what the pointer points to.
2. Calls `AliasMap.declare_ptr()` with the resolved target site.

The `is_stack_owner` flag is always `False` for pointer declarations — the pointer variable itself is on the stack, but ownership of the pointed-to memory is tracked separately by the site.

The initial value expression is always walked for side effects regardless of whether the variable is a pointer.

---

## 9. Assignment Analysis

`_on_assign(node: fast.Assignment)` handles assignment statements where the target is an `Identifier`.

1. Walks the right-hand side expression for side effects.
2. Looks up whether the target identifier is a known pointer in the current `AliasMap`.
3. If it is, resolves the new site from the right-hand side and calls `AliasMap.assign_ptr()` to update the pointer's tracked site.

Non-identifier assignment targets (e.g. `arr[i] = x`, `obj.field = y`) are not tracked for pointer aliasing, though their subexpressions are walked.

The same logic is also applied inside `_walk_expr` when an `Assignment` appears as an expression (e.g. inside a `for` update clause).

---

## 10. Expression Walking

`_walk_expr(node)` traverses an expression tree for side effects. It does not return a value; its job is to:

- Trigger `AliasMap.record_malloc()` for `fmalloc` calls (when `--leaks` is active).
- Trigger `AliasMap.record_free()` for `ffree` calls (when `--leaks` is active).
- Detect thread spawns and mark pointer arguments as thread-escaped (when `--threads` is active).
- Check uses of identifiers against thread-escaped sites (when `--threads` is active).
- Recursively walk into the call graph for `FunctionCall` nodes.
- Recurse into all sub-expressions.

### Expression node handling

| AST Node | Action |
|---|---|
| `fast.FunctionCall` | Resolve callee. If `node.name` is a plain string, look it up in the call graph directly. If it is an expression (function pointer), compile and execute it through the FVM to recover the callee name. Once resolved, enter `_check_function` with a call context built from the argument sites. If unresolved after FVM, check argument aliasing at the call site via `check_call_args`. Walk all arguments. |
| `fast.MethodCall` | Walk object and all arguments. Attempt static resolution via `<obj>__<method>` and short-name lookup. If that fails, compile and execute the full method call expression through the FVM to recover the callee name. Once resolved, enter `_check_function` with a call context. If still unresolved, check argument aliasing via `check_call_args`. |
| `fast.BinaryOp` | Walk left and right operands. |
| `fast.UnaryOp` | Walk operand. |
| `fast.AddressOf` | Walk inner expression. |
| `fast.PointerDeref` | If `--threads`: check if the pointer was thread-escaped. Walk the pointer expression. |
| `fast.MemberAccess` | Walk the object. |
| `fast.ArrayAccess` | If `--threads`: check if the array pointer was thread-escaped. Walk array and index. |
| `fast.CastExpression` | Walk inner expression. |
| `fast.TypeConvertExpression` | Walk inner expression. |
| `fast.IfExpression` | Walk condition, then-branch, and else-branch. |
| `fast.TernaryOp` | Walk condition, true branch, and false branch. |
| `fast.Assignment` | Walk value; if target is a known pointer identifier, update its tracked site via `assign_ptr()`. If `--threads`: check target identifier and array base for thread escape. |
| `fast.CompoundAssignment` | Walk value only (compound targets are not pointer-tracked). |
| `fast.Identifier` | If `--threads` and not inside a spawn implementation function: check for thread escape. |

---

## 11. Statement Walking

`_walk_stmt(node)` dispatches on the AST statement type. The full set of handled statement kinds:

| AST Node | Action |
|---|---|
| `fast.VariableDeclaration` | `_on_var_decl()` — register site, declare pointer if applicable. |
| `fast.Assignment` | `_on_assign()` — update pointer site on reassignment. |
| `fast.CompoundAssignment` | Walk the value expression only. |
| `fast.ExpressionStatement` | Walk the inner expression. |
| `fast.Block` | `_walk_block()` — push new scope, walk statements, pop scope. |
| `fast.IfStatement` | Walk condition; walk then-block and else-block (each as a separate scope). |
| `fast.WhileLoop` | Walk condition; walk body as a scope. |
| `fast.DoWhileLoop` | Walk body as a scope; walk condition. |
| `fast.ForLoop` | Walk init statement, condition, update, and body (body is a separate scope). |
| `fast.ForInLoop` | Walk body as a scope (iteration variable not pointer-tracked). |
| `fast.SwitchStatement` | Walk switch expression; walk each case body as a separate scope. |
| `fast.ReturnStatement` | Walk the return value expression. |
| `fast.DeferStatement` | Walk the deferred expression or each statement in the deferred body. |
| `fast.TryBlock` | Walk the try body and each catch body as separate scopes. |
| `fast.FunctionDefStatement` | Recursively check the nested function definition. |
| All others | Skipped (`break`, `continue`, `label`, `goto`, `assert`, etc. do not introduce pointers). |

### Scope management

Every block construct (`if`, `while`, `for`, `switch`, `try`, and explicit `{ }` blocks) pushes a new scope frame via `AliasMap.push_scope()` and pops it via `AliasMap.pop_scope(check_leaks=...)` on exit. This ensures that stack-site ownership is correctly attributed to the innermost enclosing scope.

---

## 12. Thread Safety Analysis

Enabled with `--threads`. The thread safety analysis is a heuristic that tracks pointer arguments passed to thread spawn functions.

### What counts as a thread spawn

Any `FunctionCall` or `MethodCall` whose name (case-insensitive) contains the substring `spawn` or `thread` is treated as a thread spawn site. This covers common patterns including `thread_create`, `pthread_create`, `CreateThread`, and any user-defined wrappers.

Internal spawn implementation functions (`thread_create`, `thread_create_stack`, `pthread_create`, `CreateThread`) are excluded from the escape check — violations are not reported for pointer uses inside these functions.

### Escape detection

When a thread spawn is detected:

1. Each argument is unwrapped through casts, `AddressOf`, and single-argument function calls (via `_unwrap_ptr_ident`) to find the underlying identifier.
2. `AliasMap.check_thread_escape()` is called for each resolved name.
3. After the spawn point, any use of the same pointer variable (dereference, array access, assignment target, or bare identifier) triggers `AliasMap.check_use_after_escape()`.

### Use-after-escape checking

Anywhere an `Identifier` is encountered in expression walking (and `--threads` is active and the current function is not a spawn implementation), `_check_ident_escape()` is called. This delegates to `AliasMap.check_use_after_escape()`, which records a violation if the identifier's site was marked as thread-escaped.

---

## 13. Heap Leak Analysis

Enabled with `--leaks`. Tracks `fmalloc`/`ffree` pairs within function scope.

### `fmalloc` tracking

When `_walk_expr` encounters a `FunctionCall` named `fmalloc`, it calls:

```python
alias.record_malloc(site, file, line)
```

where `site = "heap:<func>:<line>"`.

### `ffree` tracking

When `_walk_expr` encounters a `FunctionCall` named `ffree`, `_resolve_ffree_arg()` is called on the first argument to determine which heap site is being freed. The argument is unwrapped through the following patterns:

| Argument form | Resolution |
|---|---|
| `ffree(ptr)` — plain `Identifier` | Look up `ptr` in `AliasMap`, return its site. |
| `ffree(long(ptr))` — `FunctionCall` cast | Recurse into the first argument. |
| `ffree((u64)ptr)` — `CastExpression` | Recurse into the inner expression. |
| `ffree(@ptr)` — `AddressOf` of `Identifier` | Look up the inner identifier's site. |
| `ffree(long(ptr))` — `TypeConvertExpression` | Recurse into the inner expression. |

After resolution, `alias.record_free(freed_site)` is called to mark that site as freed.

### Leak reporting

At the end of a function, if `--leaks` is active and the function is not an allocator wrapper, `AliasMap.check_heap_leaks()` is called. This reports any `fmalloc` site that has no corresponding `ffree` site in the current function scope as a heap leak violation.

Allocations that are returned from the function transfer ownership to the caller — the allocator wrapper heuristic prevents false positives for `fmalloc`-wrapping functions.

---

## 14. Site Resolution

`_resolve_site(expr, var_name, file, line) -> str` determines what allocation site an expression refers to. It is called when a pointer variable is declared or reassigned, to know what the pointer points to.

The resolution rules, in order:

| Expression form | Resolved site |
|---|---|
| `None` | `"unknown"` |
| `@someVar` (`AddressOf` of `Identifier`) | Look up `someVar` in enclosing scope frames' `var_sites`; return that site, or `stack:<func>:someVar@<line>` if not found. |
| `@arr[i]` (`AddressOf` of `ArrayAccess`) | Same as `@someVar` using the base array identifier. |
| `fmalloc(...)` | `heap:<func>:<line>` |
| `ffree(...)` | `"unknown"` (side effect handled elsewhere) |
| `a + n` or `a - n` (`BinaryOp` ADD/SUB) | `derived:<site of left>`, or falls back to right side if left is `unknown`. |
| `someVar` (`Identifier`) | Copy the site from `someVar`'s `AliasMap` entry if it exists, else `"unknown"`. |
| `cast<T>(expr)` (`CastExpression`) | `derived:<resolved site of expr>`, or `"unknown"`. |
| `T(expr)` (`TypeConvertExpression`) | `derived:<resolved site of expr>`, or `"unknown"`. |
| `*ptr` (`PointerDeref`) | FVM execution attempted; if successful, slot-to-variable mapping recovers the site. Falls back to `"unknown"` only if FVM cannot resolve. |
| Anything else | FVM execution attempted on the full expression. Falls back to `"unknown"` only if FVM cannot resolve. |

The `derived:` prefix distinguishes a cast or arithmetic derivative from its original so that two differently-derived pointers to the same base do not spuriously alias each other.

---

## 15. Source Line Remapping

Because `FXPreprocessor` merges all `#include`d files into a single source string before lexing, all AST node line numbers refer to lines in this merged stream — not to lines in the original files.

`BorrowChecker._remap(merged_line) -> (filename, original_line)` converts a merged line number back to the original file and line using the `line_map` list produced by the preprocessor:

```python
line_map[merged_line - 1] == (original_filename, original_1based_line)
```

After `_check_function()` completes, all violations collected from `AliasMap` have their `.file` and `.line` updated via `_remap`. Detail strings in the format `"... at <unknown>:N"` are also remapped — the `N` after the final colon is extracted, remapped, and substituted back.

If no `line_map` is available (e.g. when running FBC programmatically without a preprocessor), line numbers are left as-is.

---

## 16. Companion Modules

`fbc.py` depends on two companion modules that must be present alongside it.

---

### `fbc_alias.py` — Pointer tracking and violation detection

This module contains three classes: `PtrInfo`, `ScopeFrame`, and `AliasMap`, plus the `Violation` data class. It is the core of the analysis engine; `fbc.py` delegates all pointer state mutations and violation detection to `AliasMap`.

#### `PtrInfo`

```python
@dataclass
class PtrInfo:
    var_name:    str   # the IDEKA variable name
    site:        str   # allocation site identity string
    mutable:     bool  # whether this is a mutable view of the site
    scope_depth: int   # depth of the scope frame where this pointer was declared
    func_name:   str   # name of the enclosing function
    file:        str   # source file at declaration
    line:        int   # source line at declaration
```

One `PtrInfo` is created for every live pointer variable. The `scope_depth` is used during `pop_scope()` to remove dead pointers from surviving frames.

#### `Violation`

```python
@dataclass
class Violation:
    kind:    str        # see violation kinds table below
    message: str        # human-readable one-line summary
    file:    str        # source file (remapped from merged line by BorrowChecker)
    line:    int        # source line (remapped)
    detail:  list[str]  # zero or more extra context lines
```

`Violation.format()` returns a multi-line string suitable for printing:

```
[FBC] mutable_alias
  src/main.idk:42  mutable alias violation on site 'heap:foo:17'
  'p' -> heap:foo:17 (mutable) at src/main.idk:42
  'q' -> heap:foo:17 (mutable) at src/main.idk:38
```

**Violation kinds:**

| Kind | Trigger | Severity colour |
|---|---|---|
| `mutable_alias` | Two live pointers reference the same site and at least one is mutable. | Red |
| `scope_escape` | A pointer survives a scope pop while its pointed-to stack site was owned by the exiting scope. | Red |
| `use_after_scope` | A pointer is used after its target scope has exited (reserved for future use). | Red |
| `thread_escape` | A pointer is passed to a spawned thread while a mutable alias exists at spawn time. | Yellow |
| `thread_race` | A pointer is accessed after its site was thread-escaped (potential data race). | Red |
| `heap_leak` | An `fmalloc` site has no reachable `ffree` before the end of the function. | Yellow |

#### `ScopeFrame`

```python
class ScopeFrame:
    depth:       int              # nesting depth (0 = outermost function scope)
    func_name:   str
    ptrs:        dict[str, PtrInfo]   # var_name → PtrInfo for pointers in this frame
    owned_sites: set[str]             # stack sites created in this scope
    var_sites:   dict[str, str]       # var_name → site for ALL stack vars (for address-of)
```

`ScopeFrame` is not used directly by `fbc.py` — it is internal to `AliasMap`. Each scope-introducing construct (block, if-branch, loop body, try/catch body) gets its own frame.

Key methods (called only by `AliasMap`):

- `declare_stack_site(var_name, site, line, file)` — adds `site` to `owned_sites`.
- `add_ptr(info)` — registers a `PtrInfo` in `ptrs`.
- `remove_ptr(var_name)` — removes a pointer from `ptrs`.
- `all_ptrs()` — returns all `PtrInfo` values as a list.

#### `AliasMap`

```python
class AliasMap:
    frames:                list[ScopeFrame]
    violations:            list[Violation]
    func_name:             str                         # current function (set by BorrowChecker)
    file:                  str                         # current file hint
    heap_sites:            dict[str, tuple[str, int]]  # site → (file, line) of fmalloc
    thread_escaped_sites:  dict[str, tuple[str, int]]  # site → (spawn_file, spawn_line)
```

`AliasMap` never raises exceptions. All detected problems are appended to `violations` and the walk continues. `BorrowChecker` drains `violations` after each function.

**Scope management:**

`push_scope()` appends a new `ScopeFrame` at the current depth.

`pop_scope(check_leaks=False)` removes the top frame and then:

1. Calls `_check_escape_after_pop()` — walks all surviving frames and reports a `scope_escape` violation for any pointer whose site is in the now-dead frame's `owned_sites`.
2. Removes from surviving frames any `PtrInfo` whose `scope_depth` equals the depth of the frame that just exited (those variables are now out of scope everywhere).

**Pointer registration:**

`declare_ptr(var_name, site, mutable, file, line, is_stack_owner=False)`

Registers a new pointer in the current (top) frame. If `is_stack_owner=True`, also calls `frame.declare_stack_site()` so the frame knows it owns that stack memory. Immediately calls `_check_mutable_alias()`.

`assign_ptr(var_name, site, mutable, file, line)`

Updates an existing pointer's site in whichever frame it lives. If the variable is not yet known, delegates to `declare_ptr()`. Calls `_check_mutable_alias()` after the update.

`_find_ptr(var_name) -> Optional[PtrInfo]`

Searches frames top-down (innermost first) for the named variable. Returns the first match or `None`.

**Aliasing detection:**

`_check_mutable_alias(new_ptr)` is called every time a pointer is declared or reassigned. It scans all live pointers across all frames:

- Skips the same variable.
- Skips if sites differ.
- Skips if the site is `"unknown"` or starts with `"derived:"`.
- If two pointers share the same site and at least one is mutable, appends a `mutable_alias` violation with a two-line detail block naming both pointers, their sites, mutability, and source locations.

**Scope escape detection:**

`_check_escape_after_pop(dead_sites, dead_frame)` iterates all surviving frames after a scope exits. For any `PtrInfo` whose `site` is in `dead_sites`, a `scope_escape` violation is appended.

**Heap tracking:**

`record_malloc(site, file, line)` — adds the site to `heap_sites`.

`record_free(site)` — removes the site from `heap_sites` (no error if absent, since `ffree` argument resolution may return a site FBC didn't see allocated in this function).

`check_heap_leaks()` — appends a `heap_leak` violation for every remaining entry in `heap_sites`, then clears it.

**Thread safety:**

`check_thread_escape(ptr_var, file, line)` — two-phase check:

1. **Phase 1 (spawn-time alias check):** scans all live pointers. If any live pointer (other than `ptr_var` itself) shares the same site, and either is mutable, appends a `thread_escape` violation.
2. **Phase 2 (mark for future access checks):** if the pointer is mutable and its site is not `"unknown"` or `"derived:..."`, records the site in `thread_escaped_sites` with the spawn location. Only sites with resolvable, non-derived identities are marked — this prevents cascading false positives from untracked pointers.

`check_use_after_escape(ptr_var, file, line)` — looks up `ptr_var` in `AliasMap`. If the pointer's site is in `thread_escaped_sites`, appends a `thread_race` violation, unless the current line is the same as the spawn line (the spawn call itself is exempt).

---

### `fbc_report.py` — Output formatting

#### Constants

```python
COLORS = {
    'red':    '\033[91m',
    'yellow': '\033[93m',
    'cyan':   '\033[96m',
    'dim':    '\033[2m',
    'bold':   '\033[1m',
    'reset':  '\033[0m',
}

KIND_COLOR = {
    'mutable_alias':   'red',
    'scope_escape':    'red',
    'use_after_scope': 'red',
    'thread_escape':   'yellow',
    'thread_race':     'red',
    'heap_leak':       'yellow',
}
```

The internal `_c(key, text, use_color)` helper applies an ANSI colour if `use_color=True`, otherwise returns `text` unchanged.

#### `print_violations(violations, mode, use_color, json_out, file=sys.stderr)`

Prints all violations. When the list is empty, returns immediately without printing anything.

**Human-readable mode** (`json_out=False`): for each violation, prints:

```
[FBC error] mutable_alias
  src/main.idk:42  mutable alias violation on site 'heap:foo:17'
  'p' -> heap:foo:17 (mutable) at src/main.idk:42
  'q' -> heap:foo:17 (mutable) at src/main.idk:38
```

Line 1 uses bold for `[FBC error]` or `[FBC warning]` and colours the kind string via `KIND_COLOR`. Line 2 uses cyan for the `file:line` location. Detail lines are dimmed. A blank line separates each violation.

**JSON mode** (`json_out=True`): emits a JSON array to **stdout** (not stderr). Each element is an object:

```json
[
  {
    "kind":    "mutable_alias",
    "message": "mutable alias violation on site 'heap:foo:17'",
    "file":    "src/main.idk",
    "line":    42,
    "detail":  [
      "'p' -> heap:foo:17 (mutable) at src/main.idk:42",
      "'q' -> heap:foo:17 (mutable) at src/main.idk:38"
    ],
    "level":   "error"
  }
]
```

`level` is `"error"` or `"warning"` according to the `mode` argument.

#### `print_summary(violations, files_checked, funcs_checked, use_color, json_out, file=sys.stdout)`

Prints a single summary line to **stdout** after all violations.

**No violations:**
```
[FBC] OK -- 3 file(s), 47 function(s) checked, no violations found.
```
`OK` is printed in cyan.

**With violations:**
```
[FBC] 2 violation(s) -- 3 file(s), 47 function(s) checked
  heap_leak: 1, mutable_alias: 1
```
The violation count is in red. The second line lists each kind and its count, sorted alphabetically.

In `--json` mode, `print_summary` returns immediately without printing anything (the JSON array from `print_violations` is the sole machine-readable output).

---

## 17. Helper Functions

| Function | Signature | Description |
|---|---|---|
| `_is_pointer_type` | `(type_spec) -> bool` | Returns `True` if a TypeSystem node represents a pointer type, by checking `is_pointer` or `pointer_depth > 0`. |
| `_node_file` | `(node) -> str` | Returns `node.source_file` or `'<unknown>'` if absent. |
| `_node_line` | `(node) -> int` | Returns `node.source_line` or `0` if absent. |
| `_make_stack_site` | `(func, var, line) -> str` | Constructs `"stack:<func>:<var>@<line>"`. |
| `_make_heap_site` | `(func, line) -> str` | Constructs `"heap:<func>:<line>"`. |
| `_make_param_site` | `(func, param) -> str` | Constructs `"param:<func>:<param>"`. |
| `_is_fmalloc` | `(node) -> bool` | Returns `True` if `node` is a `FunctionCall` named `fmalloc`. |
| `_is_ffree` | `(node) -> bool` | Returns `True` if `node` is a `FunctionCall` named `ffree`. |
| `_is_thread_spawn` | `(node) -> bool` | Returns `True` if `node` is a `FunctionCall` or `MethodCall` whose name (lowercased) contains `spawn` or `thread`. |

---

## 18. File Parsing

### `parse_file(path: str) -> (fast.Program, line_map)`

Parses a single `.idk` file through the full compiler front-end pipeline:

1. **`FXPreprocessor`** — expands `#include`, `#def`, `#ifdef`, etc., producing a merged source string and a `line_map`.
2. **`IDEKALexer`** — tokenises the merged source.
3. **`IDEKAParser`** — parses tokens into a `fast.Program` AST.

`build_compiler_macros()` is called before preprocessing to populate platform detection macros (equivalent to what the compiler itself uses).

### `collect_fx_files(path: str) -> list[str]`

If `path` is a file, returns `[path]`. If it is a directory, recursively finds all `*.idk` files with `rglob` and returns them sorted.

---

## 19. CLI Reference

```
python fbc.py <target> [options]
```

### Positional argument

| Argument | Description |
|---|---|
| `target` | Path to a `.idk` file or a directory. If a directory, all `.idk` files found recursively are checked. |

### Options

| Flag | Default | Description |
|---|---|---|
| `--entry NAME` | `FRTStartup` | Name of the entry point function. FBC starts call-graph traversal from this function. If not found, all functions are checked with a warning. |
| `--warn` | off | Treat all violations as warnings. Output is still printed, but the exit code is always 0. |
| `--threads` | off | Enable thread safety analysis: detect pointer arguments passed to thread spawn functions and flag subsequent uses in the spawning scope. |
| `--leaks` | off | Enable heap leak analysis: track `fmalloc`/`ffree` pairs and report unmatched allocations at function scope exit. |
| `--json` | off | Emit machine-readable JSON to stdout instead of human-readable text. Suppresses the informational header lines. Suitable for CI pipeline integration. |
| `--no-color` | off | Disable ANSI escape codes in output. Automatically applied when stderr is not a TTY. |

### Output

By default, violations are written to **stderr** and the summary is written to **stderr**. The `--json` flag writes to **stdout**.

Informational lines (file count, function count) are written to stdout in normal mode and suppressed in `--json` mode.

---

## 20. Exit Codes

| Code | Meaning |
|---|---|
| `0` | No violations found, or `--warn` mode was used (violations may exist but are not errors). |
| `1` | One or more violations found in default (error) mode. |
| `2` | Invocation error: no `.idk` files found, no files could be parsed, or compiler modules could not be imported. |

---

## 21. Integrating FBC Programmatically

```python
import sys
from pathlib import Path

# Add compiler module path
sys.path.insert(0, 'src/compiler')

from fbc import CallGraph, BorrowChecker, parse_file, collect_fx_files

# Parse files
fx_files = collect_fx_files('src/')
programs, line_maps = [], []
for fx in fx_files:
    prog, line_map = parse_file(fx)
    programs.append((fx, prog))
    line_maps.append(line_map)

# Build call graph
cg = CallGraph()
for fx, prog in programs:
    cg.collect(prog)

# Run checker
checker = BorrowChecker(
    call_graph=cg,
    entry='FRTStartup',
    check_threads=True,
    check_leaks=True,
    line_map=line_maps[0] if line_maps else [],
)
checker.run()

# Inspect results
for v in checker.violations:
    print(f"[{v.kind}] {v.file}:{v.line}: {v.message}")
    for detail in v.detail:
        print(f"  {detail}")

print(f"Checked {checker.funcs_checked} functions, "
      f"{len(checker.violations)} violation(s).")
```

### Key integration points

- `checker.violations` — list of `Violation` objects with `.kind`, `.message`, `.file`, `.line`, `.detail`.
- `checker.funcs_checked` — number of function bodies that were analysed.
- `cg.funcs` — full dict of all collected `FunctionDef` nodes, keyed by mangled name.
- `cg.visited` — set of function names that were reached during analysis.

You can inject a custom entry point or run the checker multiple times against different entry points by resetting `cg.visited` between runs:

```python
cg.visited.clear()
checker2 = BorrowChecker(cg, entry='test_main', check_leaks=True)
checker2.run()
```

---

## 22. Limitations and Design Notes

### Conservative pointer classification

All pointer parameters are treated as mutable (`mutable=True`). This is conservative — it may produce more aliasing violation candidates than necessary for parameters that are logically immutable, but prevents missed violations.

### Derived sites

Cast and pointer-arithmetic expressions produce `"derived:<base_site>"` sites rather than sharing the base site. Two derived pointers from the same base are thus treated as distinct — this is intentional to prevent false aliasing reports for common C-style patterns like `char* p = (char*)buf; char* q = (char*)buf + offset;`.

### Thread spawn heuristic

The thread spawn detector is heuristic-based (substring match on function name). It will not catch thread spawns through function pointers or through wrappers with non-obvious names. It will also trigger on non-spawn functions that happen to contain `thread` in their name (e.g. `get_thread_id`). The exclusion of known spawn implementation functions (`thread_create`, etc.) mitigates some false positives.

### Single merged line map

When multiple `.idk` files are parsed, each goes through its own preprocessor and produces its own `line_map`. The FBC currently only uses the `line_map` from the first file. For multi-file projects where the second or later file's violations need accurate line remapping, the host should concatenate or merge the line maps appropriately before constructing `BorrowChecker`.

### Cycle prevention

The `cg.visited` set prevents infinite recursion on recursive or mutually recursive functions. Each function is analysed at most once per `BorrowChecker` run, regardless of how many call sites reach it.