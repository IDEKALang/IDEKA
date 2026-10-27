# IDEKA Type Algebra - Relational Constraints

Type algebra relations are the operators used inside `constraint` blocks and inline `:{...}` constraint sets on template functions. Each operator defines an independent dimension of type behavior - a pair of types can satisfy constraints on one dimension while being restricted on another.

---

## Operator Reference

### `~=` - Compatible

```
A ~= B
```

A and B must be compatible types at instantiation. Compatibility requires matching pointer depth and matching bit width (if both widths are known). Violated at the call site when the concrete types resolved for A and B fail the compatibility check.

---

### `!~=` - Incompatible

```
A !~= B
```

A and B must be incompatible types at instantiation. Violated when the concrete types would otherwise be compatible (same pointer depth and matching bit width). Use this to enforce that two type parameters remain distinct.

---

### `!@` - No Address-Of

```
A !@ A
```

Values of type A cannot have their address taken (`@`) anywhere in the template function body. Checked by walking the original template AST before substitution. Any `@expr` where `expr` is a variable of the constrained type is a violation.

This is a usage restriction, not a type property - the types themselves may be perfectly valid; the constraint forbids a specific operation on them within the constrained template.

---

### `!`<` - No Truncation (Independent)

```
A !`< A
```

A cannot appear in a bit-lowering (truncation) context. Checked by walking the instantiated function body for cast expressions, binary operations, and return statements where a value of A's width is narrowed. The independent form fires when *either* operand of the narrowing is of the constrained type.

---

### `!`<=` - No Truncation (Between)

```
A !`<= B
```

No truncation is permitted *between* A and B specifically - both the source and destination of the narrowing must match the constrained types for the violation to fire. A value of type A narrowing to an unrelated type does not violate this constraint.

---

### `!`>` - No Widening (Independent)

```
A !`> A
```

A cannot appear in a bit-widening context. Mirror of `!`<` - fires when either operand of a widening operation is of the constrained type.

---

### `!`>=` - No Widening (Between)

```
A !`>= B
```

No widening is permitted between A and B specifically. Mirror of `!`<=`.

---

### `!-=` - No Unsigned Operations

```
A !-= B
```

A and B cannot be used together in unsigned arithmetic operations. Enforces that two type parameters retain distinct signedness semantics and cannot participate in unsigned arithmetic across each other.

---

## Syntax

### `constraint` Block

```
constraint Name(A, B, ...)
{
    relation_expr
};
```

Relations are parsed as chained binary expressions. The rhs of one relation becomes the lhs of the next in a chain:

```
A ~= B !~= C !`< D
```

is three independent relations: `A ~= B`, `B !~= C`, `C !`< D`.

Multiple independent chains are separated by commas:

```
constraint MyCS(A, B, C)
{
    A ~= B,
    C !`< C
};
```

### Compound Operands with `&`

Either side of a relation can be a `&`-joined list of type parameters:

```
A !~= B & C
```

This expands to two independent relations: `A !~= B` and `A !~= C`. The compound operand can appear on either side and participates as a unit in chained expressions:

```
D !~= B & [A !@ A] !~= C
```

Parses as: `D !~= B & [A !@ A]` (D is incompatible with both B and the A self-group), then `B & [A !@ A] !~= C` (that compound is also incompatible with C).

### Self-Relations (Unary Form)

When lhs and rhs are the same parameter, the relation applies to that type alone:

```
A !`< A   // A cannot be truncated, period
A !@ A    // A cannot have its address taken, period
```

This is the unary form - the single parameter appears on both sides.

---

## Applying a `constraint` to a Template Function

### Bare name (auto-mapped by declaration order)

```
def foo<T: int, :{MyCS}>(T x) -> void { ... };
```

The constra's formal parameters are mapped to the template's type parameters in declaration order. The constra's arity must exactly match the number of template type parameters - a mismatch is a compile error.

### Explicit arguments

```
def foo<T: int, U: int, :{MyCS(U, T)}>(T x, U y) -> void { ... };
```

The constra's formal parameters are explicitly mapped to the given template parameters.

### Inline raw relation

```
def foo<T: int, :{T !`< T}>(T x) -> void { ... };
```

A relation can be written directly inline without a named `constraint`.

---

## Merging Constraint Sets

```
constraint Combined = MyCS1 + MyCS2;
```

All sources must have the same arity. Parameter names are taken from the first source. An explicit rename list can be provided:

```
constraint Combined(M, N) = MyCS1 + MyCS2;
```

The merge checks for mutex conflicts at definition time. The following pairs are mutually exclusive on the same operand pair and will error if both appear in the merged set:

- `~=` and `!~=`
- `!`<=` and `!`>=`

---

## Enforcement

| Operator | When Checked | How |
|----------|-------------|-----|
| `~=`     | Call site / instantiation | Type compatibility check on concrete types |
| `!~=`    | Call site / instantiation | Type compatibility check on concrete types |
| `!@`     | Instantiation | AST walk of template body for `AddressOf` nodes |
| `!`<` `!`<=` | Instantiation | Body walk for casts, binary ops, return statements |
| `!`>` `!`>=` | Instantiation | Body walk for casts, binary ops, return statements |
| `!-=`    | Instantiation | Body walk for unsigned arithmetic operations |

The `~=` and `!~=` operators fire at the call site before the function body is instantiated. All body-check operators (`!@`, `!`<`, `!`<=`, `!`>`, `!`>=`, `!-=`) walk the function body after the concrete types are known.