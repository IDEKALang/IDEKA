# IDEKA Developer Tools

Two developer utilities for the [IDEKA language](https://IDEKA-lang.org): a diagnostics-only LSP server for editor integration, and an automated test runner for the compiler.

---

## `flsp.py` — IDEKA Language Server

A [Language Server Protocol](https://microsoft.github.io/language-server-protocol/) server that provides real-time diagnostics for `.idk` files. It wraps the IDEKA parser (`fparser.py`) and surfaces parse errors directly in your editor as you type.

### Requirements

```
pip install pygls lsprotocol
```

The server must be able to import `fparser.py` and `fmacros.py` from the IDEKA compiler source. Either run the script from the repo root, or set the `IDEKA_SRCDIR` environment variable to the repo root path.

### Usage

**stdio mode** (default — for editors):
```
python flsp.py
```

**TCP mode** (port 2087, useful for debugging):
```
python flsp.py --tcp
python flsp.py --tcp --host 0.0.0.0 --port 9000
```

### Editor Configuration

**Neovim** (`init.lua`):
```lua
vim.lsp.start({
    name = "IDEKA",
    cmd  = { "python3", "/path/to/flsp.py" },
    filetypes = { "IDEKA" },
    root_dir = vim.fn.getcwd(),
})
```

For [nvim-lspconfig](https://github.com/neovim/nvim-lspconfig) users, register IDEKA as a custom server:
```lua
local lspconfig = require("lspconfig")
local configs = require("lspconfig.configs")

if not configs.IDEKA then
    configs.IDEKA = {
        default_config = {
            cmd = { "python3", "/path/to/flsp.py" },
            filetypes = { "IDEKA" },
            root_dir = lspconfig.util.root_pattern(".git"),
            single_file_support = true,
        },
    }
end

lspconfig.IDEKA.setup({})
```

**Helix** (`languages.toml`):
```toml
[[language]]
name = "IDEKA"
language-servers = ["IDEKA-lsp"]
file-types = ["fx"]

[language-server.IDEKA-lsp]
command = "python3"
args    = ["/path/to/flsp.py"]
```

**VS Code** (`settings.json` or extension `package.json`):

Install the [generic LSP client extension](https://marketplace.visualstudio.com/items?itemName=llvm-vs-code-extensions.vscode-clangd) or use [vscode-languageclient](https://www.npmjs.com/package/vscode-languageclient) in a custom extension. To wire it up manually via the multi-root workspace settings:

```json
{
    "languageServerExample.trace.server": "verbose",
    "[IDEKA]": {
        "editor.defaultFormatter": "IDEKA-lsp"
    }
}
```

For a quick no-extension setup, the [Command Variable](https://marketplace.visualstudio.com/items?itemName=rioj7.command-variable) + [Custom Local Formatters](https://marketplace.visualstudio.com/items?itemName=jkillian.custom-local-formatters) extensions can bridge stdio LSP servers. Alternatively, point any generic LSP client extension at `python3 /path/to/flsp.py` with file type `fx`.

**Emacs** (with [eglot](https://www.gnu.org/software/emacs/manual/html_mono/eglot.html), built-in since Emacs 29):
```elisp
(require 'eglot)

;; Register the IDEKA server
(add-to-list 'eglot-server-programs
             '(IDEKA-mode . ("python3" "/path/to/flsp.py")))

;; Define a minimal major mode for .idk files if you don't have one
(define-derived-mode IDEKA-mode prog-mode "IDEKA"
  "Major mode for IDEKA source files.")
(add-to-list 'auto-mode-alist '("\\.idk\\'" . IDEKA-mode))

;; Auto-start eglot when opening .idk files
(add-hook 'IDEKA-mode-hook #'eglot-ensure)
```

**Emacs** (with [lsp-mode](https://emacs-lsp.github.io/lsp-mode/)):
```elisp
(require 'lsp-mode)

(lsp-register-client
 (make-lsp-client
  :new-connection (lsp-stdio-connection '("python3" "/path/to/flsp.py"))
  :activation-fn (lsp-activate-on "IDEKA")
  :major-modes '(IDEKA-mode)
  :server-id 'IDEKA-lsp))

(add-hook 'IDEKA-mode-hook #'lsp)
```

**Sublime Text** (with [LSP](https://packagecontrol.io/packages/LSP)):

Open **Preferences → Package Settings → LSP → Settings** and add:
```json
{
    "clients": {
        "IDEKA-lsp": {
            "command": ["python3", "/path/to/flsp.py"],
            "enabled": true,
            "selector": "source.IDEKA"
        }
    }
}
```

You will also need a `IDEKA.sublime-syntax` file that sets the scope to `source.IDEKA` for `.idk` files.

**Kate** (`~/.config/katerc` or via the LSP Client plugin UI):

Go to **Settings → Configure Kate → LSP Client → User Server Settings** and add:
```json
{
    "servers": {
        "IDEKA": {
            "command": ["python3", "/path/to/flsp.py"],
            "highlightingModeRegex": "^IDEKA$",
            "url": "",
            "rootIndicationFileNames": [".git"]
        }
    }
}
```

**Zed** (`~/.config/zed/settings.json`):
```json
{
    "lsp": {
        "IDEKA-lsp": {
            "binary": {
                "path": "python3",
                "arguments": ["/path/to/flsp.py"]
            }
        }
    }
}
```

You will additionally need a IDEKA language extension for Zed that declares the `.idk` file type and references `IDEKA-lsp` by name.

### How It Works

The server listens for `textDocument/didOpen`, `didChange`, and `didSave` events. On each event it runs `IDEKAParser` against the file on disk and publishes any `ParseError` as an LSP diagnostic with the correct line, column, and token-length span so the offending token is underlined precisely. On `didClose`, diagnostics are cleared.

Parse errors surfaced by the compiler as `ValueError` wrapping a `ParseError` are unwrapped transparently. Unexpected internal compiler errors are reported as diagnostics at line 1 so they don't silently disappear.

All logging goes to `stderr` to avoid corrupting the stdio LSP stream.

---

## `run_tests.py` — IDEKA Test Runner

An automated test runner that compiles and executes every `.idk` file in the `tests/` directory (or `examples/` with `--examples`) and reports pass/fail results with timing information.

### Requirements

- Python 3.x
- `idkc.py` present at the project root (the IDEKA compiler)

### Usage

```
python run_tests.py [options]
```

| Option | Description |
|---|---|
| `--verbose`, `-v` | Show compiler/runtime output for each test |
| `--compile-only` | Compile only; skip running executables |
| `--keep-artifacts` | Don't delete compiled executables after the run |
| `--filter PATTERN` | Only run tests whose filename contains `PATTERN` |
| `--examples` | Run files from `examples/` instead of `tests/` |

### Examples

```sh
# Run all tests
python run_tests.py

# Verbose output with filter
python run_tests.py -v --filter parser

# Check that everything compiles without executing
python run_tests.py --compile-only

# Keep executables for manual inspection
python run_tests.py --keep-artifacts
```

### How It Works

The runner discovers all `.idk` files in `tests/` (sorted alphabetically), invokes `idkc.py` on each via subprocess, then executes the resulting binary. Each test has a 5-second execution timeout.

A test **passes** when the compiler exits with code 0 and the binary subsequently exits with code 0. A test **fails** if either step fails. In `--compile-only` mode a test passes on a clean compile alone.

After the run, a summary table is printed showing compile/run status and timing for each test. Compiled binaries and the `build/` directory are deleted automatically unless `--keep-artifacts` is set.

If `tests/` doesn't exist it is created automatically with a placeholder `hello.idk` file.

### Output Example

```
Running 3 test(s) from /path/to/tests
...

============================================================
TEST SUMMARY
============================================================
PASS  hello.idk                       Compile: PASS (0.31s), Run: PASS (0.01s)
PASS  structs.idk                     Compile: PASS (0.44s), Run: PASS (0.02s)
FAIL  bad_syntax.idk                  Compile: FAIL (0.12s)
============================================================
Total Tests: 3
Passed: 2 (66.7%)
Failed: 1
Total compile time: 0.87s
Total run time: 0.03s
Total time: 0.90s
============================================================
```

The process exits with code `0` if all tests pass, `1` otherwise — suitable for use in CI pipelines.