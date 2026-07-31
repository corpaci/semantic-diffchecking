# Lean checker

This directory is a small Lake project used as a reproducible Lean 4 + mathlib
environment for batch-checking generated Lean snippets.

The project intentionally allows `sorry`. Do not pass `-E hasSorry` if your
dataset contains theorem statements without proofs.

## First-time setup

Run these commands from this directory:

```bash
lake update
lake exe cache get
lake build
```

`lake update` creates `lake-manifest.json`. Commit that file after the first
successful setup so future runs use the same mathlib revision.

## Check a file

```bash
lake env lean --json Examples/SorryAllowed.lean
```

Use the process exit code as the main pass/fail signal:

```text
0     Lean accepted the file, even if it emitted `sorry` warnings.
non-0 Lean found an actual error.
```

## Check code from stdin

```bash
printf 'import Mathlib\nexample : 1 + 1 = 2 := by\n  norm_num\n' | lake env lean --stdin --json
```

For generated code that may use mathlib, include `import Mathlib` or a more
specific mathlib import at the top of the snippet.

## Python subprocess example

```python
import subprocess

code = """
import Mathlib

example : False := by
  sorry
"""

p = subprocess.run(
    ["lake", "env", "lean", "--stdin", "--json"],
    input=code,
    text=True,
    capture_output=True,
    cwd="lean_checker",
)

ok = p.returncode == 0
print(ok)
print(p.stdout)
print(p.stderr)
```
