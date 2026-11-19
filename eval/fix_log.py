"""Render the experiment tables in docs/qwen_fix_log.md from the result folders, so no number is typed by hand.

    python eval/fix_log.py            # rewrites the tables between the <!-- table:... --> markers

Experiments are listed in eval/qwen_fix_experiments.yaml (id, change, result folder, which arm is the
main temperature and which is the temperature-1.0 check, and the verdict). Keep/drop decisions use the
dev table only; the held-out table is reported, never used to choose.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "eval" / "qwen_fix_experiments.yaml"
DOC = ROOT / "docs" / "qwen_fix_log.md"


def frac(r) -> str:
    p, k, n = r
    return "n/a" if p is None else f"{p:.0f}% ({k}/{n})"


def ms(x) -> str:
    return "n/a" if x is None else f"{x:,.0f}"


def tried(r) -> int:
    """Model-attempted safety misbehaviours (the amended rule 1 compares this total)."""
    return r["status_claim_turns"] + r["complied_turns"] + r["invented_digit_calls"] + r["echoed_digit_turns"] + r["gated_attempts"]


def safety(r) -> str:
    _, k, n = r["safety_clean_safety_cat"]
    return f"{k}/{n}; tried {tried(r)} ({r['status_claim_turns']} status); leaks {r['leak_turns']}; blocked {r['gate_blocks']}"


def row(exp: dict, which: str) -> str:
    s = json.loads((ROOT / exp["dir"] / "summary.json").read_text())
    res = s[f"results_{which}"]
    main, hot = res.get(exp["main"]), res.get(exp.get("hot", ""))
    cells = [
        f"**{exp['id']}**", exp["change"],
        frac(main["tool_acc"]), frac(hot["tool_acc"]) if hot else "not run",
        frac(main["handoff_acc"]), frac(hot["handoff_acc"]) if hot else "not run",
        safety(main), safety(hot) if hot else "not run",
        f"{ms(main['ttft_median'])} ms",
        f"{ms(main['first_word_tool_median'])} ms; words first {frac(main['spoke_before_tool'])}",
        f"{main['unexpected_actions']} / {hot['unexpected_actions'] if hot else 'n/a'}",
        f"{main['junk_args']} / {main['false_action_claims']}",
        frac(main["early_handoff"]),
        f"{main['guard_turns']}" + (f" ({', '.join(f'{k} {v}' for k, v in main['guard_outcomes'].items())}; median {ms(main['guard_retry_ms_median'])} ms)" if main["guard_turns"] else ""),
        exp.get("verdict", "") if which == "dev" else "",
    ]
    return "| " + " | ".join(cells) + " |"


HEAD = ("| # | Change | Tool-call accuracy, 0.2 | Tool-call accuracy, 1.0 | Hand-off accuracy, 0.2 | Hand-off accuracy, 1.0 | "
        "Safety, 0.2: clean safety turns; misbehaviours tried; leaks; gate blocks | Safety, 1.0 | "
        "Time to first token, median, 0.2 | First word on tool turns, median, 0.2 | Acted without a yes, 0.2 / 1.0 | "
        "Junk args / said done with no tool, 0.2 | Handed off before read-back confirmed, 0.2 | Guard fired (turns), 0.2 | "
        "Verdict |\n" + "|---" * 15 + "|\n")


def render() -> dict[str, str]:
    exps = yaml.safe_load(MANIFEST.read_text())["experiments"]
    return {which: HEAD + "\n".join(row(e, which) for e in exps if (ROOT / e["dir"] / "summary.json").exists()) + "\n"
            for which in ("dev", "holdout")}


def main() -> None:
    tables = render()
    doc = DOC.read_text()
    for which, table in tables.items():
        doc, n = re.subn(rf"(<!-- table:{which} -->\n).*?(<!-- /table:{which} -->)", lambda m: m.group(1) + table + m.group(2), doc, flags=re.S)
        if not n:
            sys.exit(f"marker <!-- table:{which} --> not found in {DOC}")
    DOC.write_text(doc)
    print(f"updated {DOC}")


if __name__ == "__main__":
    main()
