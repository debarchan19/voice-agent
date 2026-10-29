"""Regenerate the graph diagram (docs/graph.mmd) and the copy embedded in the README.

Usage: python scripts/draw_graph.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fakes import ScriptedModel  # noqa: E402

from wismo import build_graph  # noqa: E402

START, END = "<!-- graph:start -->", "<!-- graph:end -->"


def main() -> None:
    diagram = build_graph(ScriptedModel([])).get_graph().draw_mermaid().strip()
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "graph.mmd").write_text(diagram + "\n")

    readme = ROOT / "README.md"
    text = readme.read_text()
    if START in text and END in text:
        head, rest = text.split(START, 1)
        _, tail = rest.split(END, 1)
        readme.write_text(f"{head}{START}\n```mermaid\n{diagram}\n```\n{END}{tail}")
        print("updated docs/graph.mmd and README.md")
    else:
        print("updated docs/graph.mmd (no graph markers in README.md)")


if __name__ == "__main__":
    main()
