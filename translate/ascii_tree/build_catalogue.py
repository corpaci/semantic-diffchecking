"""Export the whole ETP catalogue as formal + ascii_tree pairs.

Renders every law in `equations.txt` (4694 in the current data drop) with
`treeify` and writes `{meta, equations}` — the same shape and the same node
numbering as every other catalogue in `translate/`, so the representations
join row for row.

The build refuses to write unless each rendering reads back to the syntax tree
it came from and all 4694 renderings are pairwise distinct. Both checks, the
CLI, and the writers live in [`../_catalogue.py`](../_catalogue.py); this file
supplies only which representation to build.

CLI:
    python3 build_catalogue.py                      # -> etp_equations_ascii_tree.json
    python3 build_catalogue.py --listing preview.txt --limit 40
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _catalogue import catalogue_main  # noqa: E402
from treeify import representation  # noqa: E402

if __name__ == "__main__":
    catalogue_main(representation, __file__, None)
