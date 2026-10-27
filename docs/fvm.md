# IDEKA Virtual Machine (FVM) — Complete Reference

**Source file:** `fvm.py`  
**Copyright:** 2026 Karac V. Thweatt  
**Role:** Experimental comptime execution backend for the IDEKA language compiler.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Getting Started](#3-getting-started)
4. [The .fvm File Format](#4-the-fvm-file-format)
5. [Type System (TTag)](#5-type-system-ttag)
6. [Stack Values (Val)](#6-stack-values-val)
7. [Instruction Reference (Op)](#7-instruction-reference-op)
8. [Memory Model](#8-memory-model)
9. [Control Flow & Functions](#9-control-flow--functions)
10. [Exception Handling](#10-exception-handling)
11. [Structs and Arrays](#11-structs-and-arrays)
12. [Type Introspection](#12-type-introspection)
13. [File I/O](#13-file-io)
14. [Foreign Function Interface (FFI)](#14-foreign-function-interface-ffi)
15. [Inline Assembly (INLINE_ASM)](#15-inline-assembly-inline_asm)
16. [Compiler Built-ins](#16-compiler-built-ins)
17. [Boundary Crossing — Emit Operations](#17-boundary-crossing--emit-operations)
18. [String Operations](#18-string-operations)
19. [Type Conversion](#19-type-conversion)
20. [Diagnostics](#20-diagnostics)
21. [Python API](#21-python-api)
22. [Serialisation and Deserialisation](#22-serialisation-and-deserialisation)
23. [Error Handling](#23-error-handling)
24. [Examples](#24-examples)

---

## 1. Overview

The IDEKA Virtual Machine (FVM) is a stack-based bytecode interpreter that executes **comptime** (compile-time) code for the IDEKA programming language. It is not a general-purpose runtime — it runs during the compiler's compilation phase to evaluate constant expressions, generate code fragments, perform metaprogramming, and interact with the host system (file I/O, FFI, inline assembly) before the final program is emitted.

**Key characteristics:**

- **Stack-based** — all operand passing and results use a value stack.
- **Typed values** — every value on the stack carries a type tag (`TTag`).
- **Comptime only** — the VM is invoked by the compiler, not at program runtime.
- **Boundary crossing** — instructions like `EMIT_CONST`, `EMIT_GLOBAL`, `EMITIDEKA` pass computed values back to the compiler's code-generation layer.
- **FFI and inline ASM** — comptime code can load native libraries and execute x86-64 AT&T assembly snippets at compile time.
- **Watchdog** — a 5-minute execution timeout prevents infinite comptime loops from hanging the compiler.
- **16 MB heap** — a private bump-allocator heap is available for comptime memory operations.

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────┐
│                       IDEKAVM                             │
│                                                          │
│  ┌─────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │  Stack  │  │  Call Frames │  │  VMHeap (16 MB)    │  │
│  │ List[Val│  │ List[CallFrm]│  │  bump + free-list  │  │
│  └─────────┘  └──────────────┘  └────────────────────┘  │
│                                                          │
│  ┌──────────────────┐  ┌──────────────────────────────┐  │
│  │  _functions dict │  │  _globals dict               │  │
│  │  name->List[Instr│  │  cross-frame comptime vars   │  │
│  └──────────────────┘  └──────────────────────────────┘  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │  emit_results  [ ('const', val), ('IDEKA', src) ] │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
         ↑  parse_fvm_source()
         │
    .fvm text file
```

**Core classes:**

| Class | Purpose |
|---|---|
| `IDEKAVM` | The interpreter — holds stack, heap, frames, and all execution logic. |
| `VMHeap` | 16 MB bump-allocator with a type-tag map and a free list. |
| `CallFrame` | A function activation record — instruction pointer, locals array, exception handler stack. |
| `Val` | A typed value on the VM stack (tag + data + optional meta dict). |
| `Instr` | A single decoded instruction (opcode + operand list + source line). |
| `StructLayout` | Cached field layout for a IDEKA struct type (names, tags, byte offsets, sizes). |
| `Op` | Enum of all opcodes. |
| `TTag` | Enum of all type tags. |

---

## 3. Getting Started

### Running a .fvm file directly

```
python fvm.py <program.fvm>
```

The CLI parses the file, creates a `IDEKAVM`, registers all `func` blocks, and executes the main instruction block. Any `emit_results` are printed to stdout.

### Embedding the VM in Python

```python
from fvm import IDEKAVM, parse_fvm_source, VMError

source = open("my_program.fvm").read()
instructions, local_count, functions, struct_layouts = parse_fvm_source(source)

vm = IDEKAVM(struct_layouts=struct_layouts)

for name, instrs in functions.items():
    vm.register_function(name, instrs)

try:
    result = vm.execute(instructions, local_count)
except VMError as e:
    print(f"Runtime error: {e}")

# Inspect emit results from boundary-crossing opcodes:
for entry in vm.emit_results:
    print(entry)
```

### Optional integrations

The CLI auto-detects and loads two optional companion modules:

- **`fvmcodegen`** — provides `FVMCodegen`, injected as `vm._codegen_class` for `compiler.import.*` operations.
- **`fmacros`** — provides `build_compiler_macros()`, populating `vm._compiler_constants` with preprocessor `#def` constants.

---

## 4. The .fvm File Format

A `.fvm` file is a plain UTF-8 text file. Lines beginning with `#` (after stripping leading whitespace) are comments. Blank lines are ignored.

### Directives

#### `locals <N>`
Declares that the top-level block uses `N` local variable slots. Must appear before any instructions at the top level.

```
locals 4
```

#### `func <name>` / `endfunc`
Defines a named comptime function. Instructions between `func` and `endfunc` form the function body.

```
func add_one
    LOCAL_GET 0
    PUSH int:1
    ADD
    RET
endfunc
```

#### `struct <name> <endian> <total_byte_size> <total_bits>` / `endstruct`
Declares a struct layout used by `STRUCT_NEW`, `STRUCT_LOAD`, `STRUCT_STORE`.

```
struct Point little 8 0
    field x int 0 4
    field y int 4 4
endstruct
```

Each `field` line has the format:

```
field <name> <type_tag> <byte_offset> <byte_size>
```

### Instruction lines

Each instruction line has the form:

```
OPCODE [operand1] [operand2] ...
```

Operands are space-separated. Quoted strings may contain spaces.

### Value token syntax

Values appear as operands to `PUSH` and are also used in serialised `.fvm` files.

| Syntax | Meaning |
|---|---|
| `int:42` | Signed 32-bit integer |
| `uint:100` | Unsigned 32-bit integer |
| `long:-1` | Signed 64-bit integer |
| `ulong:0xFF` | Unsigned 64-bit integer (hex OK) |
| `float:3.14` | 32-bit float |
| `double:2.718` | 64-bit double |
| `bool:true` / `bool:1` | Boolean |
| `bool:false` / `bool:0` | Boolean |
| `byte:0x41` | Unsigned 8-bit integer |
| `char:65` | Character (8-bit) |
| `ptr:0` | Pointer (heap offset) |
| `bytes:"hello\n"` | Raw byte string (UTF-8, escape sequences supported) |
| `"hello"` | Shorthand for `bytes:"hello"` |
| `void:0` | Void value |

**PTR meta bracket** (for round-tripping struct pointers):

```
ptr:29[struct_type=Point,stack_slot,x:0,y:32]
```

---

## 5. Type System (TTag)

Every `Val` carries one of the following type tags:

| TTag | IDEKA Type | Python Representation |
|---|---|---|
| `INT` | `int` (i32) | `int` |
| `UINT` | `uint` (u32) | `int` |
| `LONG` | `long` (i64) | `int` |
| `ULONG` | `ulong` (u64) | `int` |
| `FLOAT` | `float` (f32) | `float` |
| `DOUBLE` | `double` (f64) | `float` |
| `BOOL` | `bool` | `int` (0 or 1) |
| `BYTE` | `byte` (u8) | `int` |
| `CHAR` | `char` (u8) | `int` |
| `DATA` | `data<N>` (arbitrary bit-width) | `int` |
| `PTR` | pointer | `int` (heap offset or OS address) |
| `VOID` | `void` | `0` |
| `STRUCT` | struct value | `str` (type name), fields in `meta['fields']` |
| `ENUM` | enum value | `int` or `str` discriminant |
| `ARRAY` | array value | `int` (count), elements in `meta['elements']` |
| `BYTES` | raw byte buffer | `bytes` or `bytearray` |
| `FFI_LIB` | loaded native library | `str` (library path) |
| `FFI_SYM` | symbol in a native library | ctypes callable |
| `FILE` | open file handle | `int` (handle ID) |

### Integer width semantics

Arithmetic and bitwise results are wrapped to the bit width implied by the value's `TTag`:

- `INT` / `UINT` → 32-bit (`i32` / `u32`)
- `LONG` / `ULONG` → 64-bit (`i64` / `u64`)
- `BYTE` / `CHAR` / `BOOL` → 8-bit
- `DATA` → uses the `bits` field in `meta`

This matches IDEKA's fixed-width integer overflow semantics.

---

## 6. Stack Values (Val)

```python
@dataclass
class Val:
    tag:  TTag
    data: Any
    meta: Dict[str, Any] = {}
```

The `meta` dict carries optional auxiliary information:

| Key | Used by | Meaning |
|---|---|---|
| `struct_type` | STRUCT | Name of the IDEKA struct type |
| `fields` | STRUCT | `dict[str, Val]` — field values |
| `stack_slot` | PTR | Flag: pointer addresses a frame local slot |
| `field_bit_offsets` | PTR/STRUCT | `dict[str, int]` — bit offsets of fields |
| `elem_type` | ARRAY/PTR | Element type name string |
| `count` | ARRAY/PTR | Number of elements |
| `elem_size` | ARRAY | Size of each element in bytes |
| `elements` | ARRAY | `list[Val]` — element values |
| `sym_name` | FFI_SYM | Symbol name string |

---

## 7. Instruction Reference (Op)

### Stack Operations

| Opcode | Operands | Stack effect | Description |
|---|---|---|---|
| `PUSH` | `value` | `-- val` | Push a typed literal value onto the stack. |
| `POP` | | `val --` | Discard the top stack value. |
| `DUP` | | `a -- a a` | Duplicate the top value. |
| `SWAP` | | `a b -- b a` | Swap the top two values. |
| `ROT` | | `a b c -- b c a` | Rotate the top three values: third rises to top. |
| `OVER` | | `a b -- a b a` | Copy the second-from-top onto the stack. |

### Arithmetic Operations

All binary arithmetic ops pop two values and push the result, preserving the type tag of the first (left) operand and wrapping to its integer bit width.

| Opcode | Stack effect | Description |
|---|---|---|
| `ADD` | `a b -- a+b` | Addition. |
| `SUB` | `a b -- a-b` | Subtraction. |
| `MUL` | `a b -- a*b` | Multiplication. |
| `DIV` | `a b -- a/b` | Division (integer truncation for integer types; raises `VMError` on divide-by-zero). |
| `MOD` | `a b -- a%b` | Modulo. |
| `NEG` | `a -- -a` | Unary negation. |
| `POW` | `a b -- a**b` | Exponentiation. |
| `ABS` | `a -- \|a\|` | Absolute value. |
| `MIN` | `a b -- min(a,b)` | Minimum of two values. |
| `MAX` | `a b -- max(a,b)` | Maximum of two values. |
| `CLAMP` | `val lo hi -- clamped` | Clamp `val` to `[lo, hi]`. Pops `hi` first, then `lo`, then `val`. |

**Special:** `BYTES + int` → pointer arithmetic. When adding an integer offset to a `BYTES` value, the bytes are pinned in native memory and a `PTR` to `bytes_base + offset` is returned. This enables C-style string/buffer pointer arithmetic.

### Bitwise Operations

| Opcode | Operands | Stack effect | Description |
|---|---|---|---|
| `BAND` | | `a b -- a&b` | Bitwise AND. |
| `BOR` | | `a b -- a\|b` | Bitwise OR. |
| `BXOR` | | `a b -- a^b` | Bitwise XOR. |
| `BNOT` | | `a -- ~a` | Bitwise NOT (complement). |
| `SHL` | | `a b -- a<<b` | Shift left. |
| `SHR` | | `a b -- a>>b` | Shift right (arithmetic for signed types). |
| `ROTL` | `width` | `a -- rotl(a,width)` | Rotate left within `width` bits. |
| `ROTR` | `width` | `a -- rotr(a,width)` | Rotate right within `width` bits. |
| `BITREV` | `width` | `a -- bitrev(a,width)` | Reverse bits within `width` bits. |
| `POPCOUNT` | | `a -- popcount(a)` | Count set bits (operates on low 64 bits). |
| `CLZ` | `width` | `a -- clz(a,width)` | Count leading zeros within `width` bits. |
| `CTZ` | `width` | `a -- ctz(a,width)` | Count trailing zeros within `width` bits. |

### Comparison Operations

All comparisons pop two values and push a `BOOL` (1 or 0).

| Opcode | Description |
|---|---|
| `CMP_EQ` | Equal (`==`) |
| `CMP_NE` | Not equal (`!=`) |
| `CMP_LT` | Less than (`<`) |
| `CMP_LE` | Less than or equal (`<=`) |
| `CMP_GT` | Greater than (`>`) |
| `CMP_GE` | Greater than or equal (`>=`) |

### Logic Operations

| Opcode | Stack effect | Description |
|---|---|---|
| `AND` | `a b -- bool(a and b)` | Logical AND (truthy check). |
| `OR` | `a b -- bool(a or b)` | Logical OR (truthy check). |
| `NOT` | `a -- bool(not a)` | Logical NOT. |

---

## 8. Memory Model

The FVM has two memory spaces:

**1. VM Heap** — a private 16 MB `bytearray` managed by `VMHeap`. Allocations use a bump-pointer with a free list for reuse. Pointer values into this heap are small integers (byte offsets). The null pointer is offset 0; allocations start at offset 8.

**2. OS memory** — native addresses from `extern` calls (e.g. `malloc`), FFI, or pinned BYTES buffers. These are tracked in `_os_ptrs` and accessed via `ctypes`.

### Memory Instructions

| Opcode | Operands | Stack effect | Description |
|---|---|---|---|
| `ALLOC` | | `size -- ptr` | Pop integer byte size, allocate that many bytes on the VM heap, push the pointer offset. |
| `FREE` | | `ptr --` | Pop a pointer and return its allocation to the free list. |
| `LOAD` | `ttag byte_size` | `ptr -- val` | Pop a pointer, read `byte_size` bytes from the VM heap (or OS memory), and push a `Val` with tag `ttag`. |
| `STORE` | `ttag byte_size` | `val ptr --` | Pop a pointer and a value, serialise the value to `byte_size` bytes, and write to memory. |
| `OFFSET` | | `ptr n -- ptr+n` | Add integer `n` to pointer `ptr` (pointer arithmetic). |

**`LOCAL_DEREF`** — pop a `PTR(slot)` or OS address, push the value it points to. If the address is an OS pointer, reads one byte. If it is a slot index, returns `locals[slot]`.

**`LOCAL_DEREF_SET`** — pop a value and a pointer, store the value at the pointer location.

---

## 9. Control Flow & Functions

### Jumps

All jump addresses are zero-based instruction indices within the current function's instruction list.

| Opcode | Operands | Stack effect | Description |
|---|---|---|---|
| `JMP` | `addr` | | Unconditional jump to instruction `addr`. |
| `JIF` | `addr` | `cond --` | Pop `cond`; jump to `addr` if `cond` is truthy. |
| `JNF` | `addr` | `cond --` | Pop `cond`; jump to `addr` if `cond` is falsy. |
| `JTABLE` | `default addr0 addr1 ...` | `idx --` | Pop integer index; jump to `addrs[idx]`, or `default` if out of range. |
| `HALT` | | | Stop execution. The top-of-stack value becomes the return value of `execute()`. Clears all frames. |
| `RET` | | | Return from the current function frame. The return value is whatever is on top of the stack. |

### Function Calls

| Opcode | Operands | Stack effect | Description |
|---|---|---|---|
| `CALL` | `name argc` | `argN .. arg1 -- retval` | Pop `argc` arguments (last-pushed = first arg), push a new `CallFrame` for function `name`, execute it. |
| `CALL_PTR` | `argc` | `name argN .. arg1 -- retval` | Pop a `BYTES` function name string, then call it with `argc` arguments, same as `CALL`. |
| `TAIL_SELF` | `argc` | `argN .. arg1 --` | Self tail-call optimisation: pop `argc` args, reload into `locals[0..argc-1]`, reset `ip` to 0. No new frame is allocated. |

**Overload resolution:**

- Functions can be registered with arity-encoded names (`print__$byte`, `print__$byte_int`) to support overloading. The VM selects the best match by comparing the call's `argc` against the suffix.
- If multiple overloads match on arity, the VM scores each by `TTag` compatibility and picks the highest scorer.

**Namespace-qualified names:**

If `name` is not found exactly, the VM tries a suffix match against names like `standard__datetime__dt_from_unix_ms` when calling `dt_from_unix_ms`.

### Locals and Globals

| Opcode | Operands | Stack effect | Description |
|---|---|---|---|
| `LOCAL_GET` | `slot` | `-- val` | Push `locals[slot]` of the current frame. |
| `LOCAL_SET` | `slot` | `val --` | Pop and store into `locals[slot]`. |
| `GLOBAL_GET` | `name` | `-- val` | Push `vm._globals[name]` (or `int:0` if absent). |
| `GLOBAL_SET` | `name` | `val --` | Pop and store into `vm._globals[name]`. |

Globals persist across function calls and across multiple `execute()` invocations on the same VM instance.

---

## 10. Exception Handling

The FVM supports comptime try/catch/throw.

| Opcode | Operands | Stack effect | Description |
|---|---|---|---|
| `TRY_BEGIN` | `catch_addr` | | Register a catch handler at `catch_addr`. Records the current stack depth. |
| `TRY_END` | | | Remove the innermost exception handler (normal exit from a try body). |
| `THROW` | | `val --` | Pop a value and raise `IDEKAThrowSignal(val)`. The VM walks the frame stack looking for a `TRY_BEGIN` handler. If found, the stack is trimmed to the recorded depth, the thrown value is pushed, and execution jumps to `catch_addr`. If no handler exists, a `VMError` is raised. |

**Example pattern:**

```
TRY_BEGIN 10        # catch_addr = instruction 10
PUSH bytes:"hello"
THROW               # throws the string value
TRY_END
JMP 12              # skip catch block
# instruction 10: catch handler
COMPILER_PRINT      # print the caught exception
# instruction 12:
HALT
```

---

## 11. Structs and Arrays

### Struct Operations

Struct values are stored as `Val(TTag.STRUCT, type_name, meta={'fields': {...}})`.

| Opcode | Operands | Stack effect | Description |
|---|---|---|---|
| `STRUCT_NEW` | `type_name` | `-- struct_val` | Create a zero-initialised struct of the given type. Requires the type to be in `struct_layouts`. |
| `STRUCT_LOAD` | `field_name` | `struct -- field_val` | Pop a struct value, push the value of the named field. |
| `STRUCT_STORE` | `field_name` | `new_val struct -- updated_struct` | Pop a value and a struct, return an updated struct with the named field replaced. (Structs are immutable values; `STRUCT_STORE` produces a new copy.) |

### Enum Operations

Enum values are stored as `Val(TTag.ENUM, discriminant)`.

| Opcode | Operands | Stack effect | Description |
|---|---|---|---|
| `ENUM_NEW` | `type_name` | `-- enum_val` | Push a zero enum value with the given type name in meta. |
| `ENUM_LOAD` | | `enum -- int_or_str` | Pop an enum, push its integer or string discriminant. |
| `ENUM_STORE` | | `val enum -- updated_enum` | Pop an integer or string, pop an enum, push an updated enum with the new discriminant. |

### Array Operations

Array values are stored as `Val(TTag.ARRAY, count, meta={'elem_type': ..., 'elements': [...]})`.

| Opcode | Operands | Stack effect | Description |
|---|---|---|---|
| `ARRAY_NEW` | `type_name count` | `-- array_val` | Allocate an array of `count` zero-initialised elements of `type_name`. |
| `ARRAY_LEN` | | `arr -- int` | Pop an array, push its element count. |
| `ARRAY_LOAD` | | `arr idx -- elem` | Pop an array and an index, push the element at that index. Also supports native pointer indexing (OS and VM heap). |
| `ARRAY_STORE` | | `val idx arr -- updated_arr` | Pop a value, index, and array, push an updated array with element `[idx]` replaced. |

**Native pointer indexing:** if the array value is a `PTR` (e.g. from `ALLOC` or `extern malloc`), `ARRAY_LOAD` reads one byte at `ptr + idx`. `ARRAY_STORE` writes one byte.

---

## 12. Type Introspection

| Opcode | Operands | Stack effect | Description |
|---|---|---|---|
| `SIZEOF` | `type_name` | `-- uint` | Push the size of the type in **bits** (not bytes). |
| `TYPEOF` | | `val -- val bytes` | Peek at the top value, push its TTag name as a `BYTES` value. Does not consume the original value. |
| `ALIGNOF` | `type_name` | `-- uint` | Push the alignment requirement in bytes. For structs, this is the size of the largest field. |
| `ENDIANOF` | `type_name` | `-- bytes` | Push `bytes:"little"` or `bytes:"big"` depending on the type's declared endianness. |

---

## 13. File I/O

The FVM exposes low-level file handles.

| Opcode | Stack effect | Description |
|---|---|---|
| `IO_OPEN` | `path mode -- handle` | Pop a mode string and a path string, open the file, push a `FILE` handle. Mode strings follow Python `open()` conventions (`"r"`, `"wb"`, etc.). |
| `IO_READ` | `handle size -- bytes` | Pop a handle and a byte count (`0` = read all), push the read bytes as a `BYTES` value. |
| `IO_WRITE` | `handle ptr size --` | Pop a handle, a VM heap pointer, and a byte count; write that many bytes from the heap to the file. |
| `IO_CLOSE` | `handle --` | Close and release the file handle. |

Higher-level wrappers are also available via the compiler built-ins `COMPILER_READFILE` and `COMPILER_WRITEFILE` (see §16).

---

## 14. Foreign Function Interface (FFI)

The FVM can load native shared libraries and call their functions at comptime.

### FFI Instructions

| Opcode | Operands | Stack effect | Description |
|---|---|---|---|
| `FFI_LOAD` | `"lib_path"` | `-- ffi_lib` | Load the shared library at the given path using `ctypes.CDLL`, push an `FFI_LIB` handle. |
| `FFI_SYM` | `sym_name` | `ffi_lib -- ffi_sym` | Pop an `FFI_LIB`, look up the named symbol, push an `FFI_SYM` callable. |
| `FFI_CALL` | `argc ret_ttag` | `ffi_sym argN .. arg1 -- result` | Pop the symbol and `argc` arguments, call the native function, push the result with tag `ret_ttag`. |
| `FFI_FREE` | | `ffi_lib --` | Unload the library and discard the handle. |

### Extern Declarations

The `EXTERN_DECL` opcode registers a function name so it can be called via `CALL` without an explicit `FFI_LOAD`/`FFI_SYM` cycle. The VM resolves the symbol through explicitly loaded libraries (`compiler.fvm.loadlib`) and then falls back to the C runtime.

```
EXTERN_DECL malloc PTR
```

Calls to `malloc` via `CALL malloc 1` will then dispatch through `ctypes`.

### Argument marshalling

| TTag | Ctypes type |
|---|---|
| `INT` | `c_int32` |
| `UINT` | `c_uint32` |
| `LONG` | `c_int64` |
| `ULONG` | `c_uint64` |
| `FLOAT` | `c_float` |
| `DOUBLE` | `c_double` |
| `BOOL` | `c_bool` |
| `BYTE` | `c_uint8` |
| `PTR` | `c_void_p` |

---

## 15. Inline Assembly (INLINE_ASM)

**Requires:** `keystone-engine` (`pip install keystone-engine`). Only supported on **x86-64** hosts.

### Syntax

```
INLINE_ASM "body" "constraints" n_inputs n_outputs [output_names...]
```

- **`body`** — AT&T-syntax x86-64 assembly, with `$N` operand placeholders.
- **`constraints`** — currently unused (reserved for future GCC-style constraint strings).
- **`n_inputs`** — number of input values to pop from the stack.
- **`n_outputs`** — number of output values to push (currently 0 or 1; output always comes from `%rax`).
- **`output_names`** — optional list of global variable names to also store the result into.

### Operand placeholders

- `$0` through `$n_outputs-1` — output operands (mapped to `%rax`).
- `$n_outputs` through `$n_outputs+n_inputs-1` — input operands.

Input values are loaded into scratch registers (`%r10`–`%r15`) via `movabsq` immediates before the user body runs. The register size is inferred from the instruction mnemonic suffix (`l`→32-bit, `w`→16-bit, `b`→8-bit, else 64-bit).

### External calls

`call symbol` in the body is automatically resolved to a `movabsq $addr, %rax; callq *%rax` sequence, searching explicitly loaded libs (via `compiler.fvm.loadlib`) before falling back to the C runtime.

### Stack frame

The generated code includes a standard function prologue (`pushq %rbp; movq %rsp, %rbp`) and epilogue (`popq %rbp; retq`). Callee-saved scratch registers (`%r12`–`%r15`) are preserved if used.

### Example

```
PUSH int:42
INLINE_ASM "movq $1, $0\naddq $1, $0" "" 1 1 result
# Pops 42 as an input, computes rax = rax + 42 (where rax starts as 1), pushes the result.
```

---

## 16. Compiler Built-ins

These opcodes implement the `compiler.*` namespace that IDEKA comptime code uses to interact with the compilation environment.

### Console I/O

| Opcode | Stack effect | Description |
|---|---|---|
| `COMPILER_PRINT` | `val --` | Print a value to stdout. Handles `BYTES`, `PTR`, `CHAR`, or any scalar (via `str()`). |
| `COMPILER_INPUT` | `-- bytes` | Read one line from stdin, push as `BYTES`. |

### File I/O

| Opcode | Stack effect | Description |
|---|---|---|
| `COMPILER_READFILE` | `path -- ptr` | Read the entire file at `path` into the VM heap, push a `PTR` with `meta['count']` set to the file size. |
| `COMPILER_WRITEFILE` | `path content flags --` | Write `content` (PTR or BYTES) to `path`. `flags` is one of: `"r"`, `"w"`, `"a"`, `"rw"` (optionally suffixed with `t` for text mode). |

### Debugging and Diagnostics

| Opcode | Stack effect | Description |
|---|---|---|
| `COMPILER_FVM_TRACE_BEGIN` | | Enable per-instruction tracing to stdout for the next 2000 instructions. Prints opcode, operands, locals, and top-4 stack at each step. |
| `COMPILER_FVM_TRACE_END` | | Disable per-instruction tracing. |
| `COMPILER_FVM_SETBP` | | Comptime breakpoint: print current function, instruction pointer, all locals, and the full stack to stderr, then pause execution until the user presses Enter. |
| `COMPILER_FVM_DUMP` | `path --` | Serialise the current comptime state (all instructions logged so far + functions + struct layouts) to a `.fvm` file at `path`. |

### Imports and Packages

| Opcode | Stack effect | Description |
|---|---|---|
| `COMPILER_IMPORT_STDLIB` | `path --` | Import a standard library module (resolved relative to the compiler's stdlib root). Requires `_codegen_class` to be injected. |
| `COMPILER_IMPORT_LOCAL` | `path --` | Import a local IDEKA source file (resolved relative to `source_file`). Requires `_codegen_class`. |
| `COMPILER_FPM_PACKAGE` | `path --` | Install or resolve an FPM (IDEKA Package Manager) package. Requires `_codegen_class`. |
| `COMPILER_LOADLIB` | `name ext --` | Load a native shared library by name and extension (e.g. `"mylib"` `"so"`). The library is made available for `INLINE_ASM` symbol resolution and `EXTERN_DECL` calls. Platform-specific candidates are tried automatically (`lib<name>.<ext>`, `lib<name>.so`, `lib<name>.dylib`). |

---

## 17. Boundary Crossing — Emit Operations

These opcodes pass comptime-computed values back to the compiler's code-generation layer. Results are accumulated in `vm.emit_results` as a list of tuples.

| Opcode | Stack effect | Emit entry | Description |
|---|---|---|---|
| `EMIT_CONST` | `val --` | `('const', val)` | Emit a comptime value as an IR constant. |
| `EMIT_GLOBAL` | `size -- bytes` | `('global', bytes)` | Pop a size, snapshot that many bytes from the VM heap starting at the current bump pointer (or per the operand), emit as a global variable. |
| `EMIT_TYPE` | `val --` | `('type', val)` | Emit a type reference. The value should be a type tag. |
| `EMITIDEKA` | `src_text var_names` | `('IDEKA', substituted_text)` | Substitute comptime local values into `src_text` using `{varname:slot}` tokens, then emit the resulting IDEKA source fragment. |

### EMITIDEKA operand format

```
EMITIDEKA "const N = {value:0};" value:0
```

Each `name:slot` pair substitutes the value from `locals[slot]` into the placeholder `{name}` in the source text.

---

## 18. String Operations

All string ops work on `BYTES` values (UTF-8 byte strings).

| Opcode | Stack effect | Description |
|---|---|---|
| `STR_LEN` | `bytes -- int` | Push the byte length of the top string. |
| `STR_CAT` | `a b -- ab` | Concatenate two strings (pushes `BYTES`). |
| `STR_SLICE` | `str start len -- substr` | Pop a string, a start index, and a length; push the substring. |
| `STR_EQ` | `a b -- bool` | Push 1 if two strings are equal, else 0. |
| `STR_FIND` | `haystack needle -- int` | Pop needle then haystack, push byte offset of first occurrence, or −1 if not found. |
| `INT_TO_STR` | `int -- bytes` | Convert an integer to its decimal string representation. |
| `STR_TO_INT` | `bytes -- int` | Parse a decimal string to an integer. |

---

## 19. Type Conversion

| Opcode | Operands | Stack effect | Description |
|---|---|---|---|
| `CAST` | `ttag [hint]` | `val -- val'` | Convert the top value to the target `TTag`. Handles numeric widening/narrowing, `bool`↔numeric, `bytes`↔numeric (UTF-8 decode/encode), and struct/array identity casts. An optional `hint` string provides additional context. |
| `BITCAST` | `ttag` | `val -- val'` | Reinterpret the bytes of the top value as the target `TTag` without converting. E.g. bitcasting `float:1.0` to `uint` yields the IEEE 754 bit pattern. |

---

## 20. Diagnostics

| Opcode | Stack effect | Description |
|---|---|---|
| `ASSERT` | `val --` | Pop a value; if it is falsy, abort with `VMError: comptime assertion failed`. |
| `WARN` | `str --` | Pop a string and print it as a compiler warning to stderr. |
| `PANIC` | `str --` | Pop a string and unconditionally abort with `VMError`. |

---

## 21. Python API

### `IDEKAVM`

```python
class IDEKAVM:
    def __init__(
        self,
        struct_layouts: Dict[str, StructLayout] = None,
        type_sizes:     Dict[str, int]          = None,
        heap_size:      int                     = 16 * 1024 * 1024,
        source_file:    str                     = None,
    ): ...
```

| Parameter | Description |
|---|---|
| `struct_layouts` | Dict of struct name → `StructLayout`, pre-populated by the parser or compiler. |
| `type_sizes` | Optional override dict of type name → byte size for custom types. |
| `heap_size` | Comptime heap size in bytes (default 16 MB). |
| `source_file` | Path of the source file being compiled; used to resolve relative imports. |

**Public methods:**

```python
vm.register_function(name: str, instructions: List[Instr])
```
Register a comptime function by name. Must be called before `execute()` if the instructions call this function.

```python
vm.execute(instructions: List[Instr], local_count: int = 0) -> Optional[Val]
```
Execute a flat instruction list as a top-level comptime block. Returns the top-of-stack `Val` after `HALT`, or `None` if the stack is empty.

**Public attributes after `execute()`:**

| Attribute | Type | Description |
|---|---|---|
| `vm.emit_results` | `List[tuple]` | Accumulated emit operations from `EMIT_CONST`, `EMIT_GLOBAL`, `EMIT_TYPE`, `EMITIDEKA`. |
| `vm.last_locals` | `List[Val]` | Snapshot of the top-level frame's locals after the last `HALT`. |
| `vm.stack` | `List[Val]` | The value stack (may be non-empty if `HALT` was reached mid-stack). |
| `vm._globals` | `dict` | Comptime global variables (persist between `execute()` calls). |

**Injected attributes (optional, set by the host compiler):**

| Attribute | Description |
|---|---|
| `vm._codegen_class` | Compiler's code-generation class, used by `compiler.import.*`. |
| `vm._compiler_constants` | Dict of preprocessor `#def` constants from `fmacros`. |

### `parse_fvm_source`

```python
def parse_fvm_source(source: str) -> Tuple[
    List[Instr],
    int,
    Dict[str, List[Instr]],
    Dict[str, StructLayout],
]:
```

Parse a `.fvm` text file. Returns `(instructions, local_count, functions, struct_layouts)`.

Raises `FVMParseError` with a line number on any syntax error.

### `serialise_fvm`

```python
def serialise_fvm(
    instructions: List[Instr],
    local_count:  int,
    functions:    Dict[str, List[Instr]],
    struct_layouts: Dict[str, StructLayout] = None,
) -> str:
```

Serialise a set of instructions and function definitions back to `.fvm` text. This is the inverse of `parse_fvm_source()`, used by `COMPILER_FVM_DUMP`.

### `VMHeap`

```python
class VMHeap:
    DEFAULT_SIZE = 16 * 1024 * 1024

    def alloc(self, byte_size: int, tag: TTag = TTag.PTR) -> int: ...
    def free(self, ptr: int): ...
    def read(self, ptr: int, byte_size: int) -> bytes: ...
    def write(self, ptr: int, data: bytes): ...
    def type_of(self, ptr: int) -> Optional[TTag]: ...
    def snapshot(self, ptr: int, byte_size: int) -> bytes: ...
```

The heap can be accessed directly via `vm.heap` if needed from Python host code.

### Errors

```python
class VMError(Exception): ...          # Runtime errors
class FVMParseError(Exception):        # Parse errors; has .lineno attribute
    lineno: int
class IDEKAThrowSignal(Exception):      # Raised by THROW; has .value: Val
    value: Val
```

---

## 22. Serialisation and Deserialisation

The `.fvm` format is fully round-trippable. The host compiler uses `COMPILER_FVM_DUMP` to snapshot comptime state to disk; the CLI can then replay it.

### Value serialisation (`_serialise_val`)

Converts a `Val` back to a `type:value` token string. PTR values with meta (struct pointer, array pointer) include a bracketed meta suffix so struct field values and array elements are preserved across serialisation.

### Instruction serialisation (`_serialise_instr`)

Converts an `Instr` to a `.fvm` line (opcode + operands). Handles all opcodes including multi-operand ones (`CALL`, `JTABLE`, `EMITIDEKA`, `INLINE_ASM`).

### File layout (output of `serialise_fvm`)

```
# Generated by compiler.fvm.dump

struct PointList little 16 0
    field head ptr 0 8
    field len int 8 4
endstruct

func compute_sum
    LOCAL_GET 0
    LOCAL_GET 1
    ADD
    RET
endfunc

locals 3
PUSH int:10
PUSH int:20
CALL compute_sum 2
HALT
```

---

## 23. Error Handling

| Condition | Error |
|---|---|
| Stack underflow | `VMError: Stack underflow` |
| Division by zero | `VMError: Division by zero in comptime` |
| Unknown opcode | `VMError: Unknown opcode: <name>` |
| Unknown function | `VMError: Unknown comptime function: <name>` |
| Ambiguous overload | `VMError: Ambiguous comptime function: <name> matches [...]` |
| Heap out-of-memory | `VMError: VMHeap: out of memory (requested N, available M)` |
| Heap out-of-bounds | `VMError: VMHeap: out-of-bounds access at ptr=N size=M` |
| Invalid free | `VMError: VMHeap.free: invalid pointer N` |
| Unhandled throw | `VMError: Unhandled comptime throw: <val>` |
| FFI load failure | `VMError: FFI_LOAD: <os error>` |
| FFI symbol not found | `VMError: FFI_SYM: symbol <name> not found` |
| Extern symbol not resolved | `VMError: extern: symbol <name> not found in any loaded library` |
| INLINE_ASM: wrong arch | `VMError: INLINE_ASM: x86-64 required at comptime, got <arch>` |
| INLINE_ASM: keystone missing | `VMError: INLINE_ASM: keystone-engine is not installed` |
| INLINE_ASM: assembly failed | `VMError: INLINE_ASM: assembly failed: <details>` |
| Watchdog timeout | `VMError: comptime execution exceeded 300s (N instructions) ...` |
| Parse error | `FVMParseError: line N: <message>` |

The watchdog checks every 50,000 instructions and raises `VMError` if the 5-minute limit is exceeded. The error message includes the current function name, instruction pointer, locals, and top-6 stack values to assist debugging.

---

## 24. Examples

### Hello world

```
# hello.fvm
PUSH bytes:"Hello, world!\n"
COMPILER_PRINT
HALT
```

Run with:
```
python fvm.py hello.fvm
```

### Arithmetic and locals

```
# compute.fvm
locals 2
PUSH int:10
LOCAL_SET 0
PUSH int:32
LOCAL_SET 1
LOCAL_GET 0
LOCAL_GET 1
ADD
INT_TO_STR
COMPILER_PRINT
HALT
```

Output: `42`

### Defining and calling a function

```
# factorial.fvm
func factorial
    # arg in locals[0]
    LOCAL_GET 0
    PUSH int:1
    CMP_LE
    JIF 8           # if n <= 1, jump to instruction 8
    LOCAL_GET 0
    PUSH int:1
    SUB
    CALL factorial 1
    LOCAL_GET 0
    MUL
    RET
    # instruction 8: base case
    PUSH int:1
    RET
endfunc

locals 1
PUSH int:10
CALL factorial 1
INT_TO_STR
COMPILER_PRINT
HALT
```

### Using a struct

```
# struct_demo.fvm
struct Vec2 little 8 0
    field x int 0 4
    field y int 4 4
endstruct

STRUCT_NEW Vec2
PUSH int:3
STRUCT_STORE x
PUSH int:4
STRUCT_STORE y
DUP
STRUCT_LOAD x
INT_TO_STR
COMPILER_PRINT
HALT
```

### Reading a file at comptime

```
# read_cfg.fvm
PUSH bytes:"config.txt"
COMPILER_READFILE
COMPILER_PRINT
HALT
```

### Exception handling

```
# exceptions.fvm
TRY_BEGIN 6        # catch at instruction 6
PUSH bytes:"something failed"
THROW
TRY_END            # not reached
JMP 7              # skip catch block
# instruction 6: catch handler
PUSH bytes:"Caught: "
SWAP
STR_CAT
COMPILER_PRINT
# instruction 7:
HALT
```

### FFI call to strlen

```
# ffi_strlen.fvm
FFI_LOAD "libc.so.6"
FFI_SYM strlen
PUSH bytes:"hello world"
FFI_CALL 1 uint
INT_TO_STR
COMPILER_PRINT
HALT
```

### Emitting a constant to the compiler

```
# emit_const.fvm
PUSH int:256
EMIT_CONST
HALT
```

After `execute()`, `vm.emit_results` will contain `[('const', Val(TTag.INT, 256))]`.