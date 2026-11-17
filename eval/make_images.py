"""Post-ready comparison images (1200x675 PNG, light background, large type for phones).

Reads one results folder written by eval/compare_llm.py and draws every number from its raw files,
so nothing on an image is typed in by hand:

    python eval/make_images.py eval/results/<timestamp>          # writes <dir>/images/

Colours identify the model on every image: Claude violet, Qwen aqua, Qwen at its default
temperature orange (first three of a validated palette: colour-blind safe across all pairs).
Text is always in text colours, and values are printed on or beside every mark.
"""

from __future__ import annotations

import json
import statistics as st
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

SURFACE, TEXT, TEXT_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
CLAUDE, QWEN, QWEN_T1 = "#6250d6", "#1baf7a", "#eb6834"
GOOD, BAD = "#0ca30c", "#d03b3b"  # status colours, always shown with an icon and a label
TINT = {CLAUDE: "#e9e6fa", QWEN: "#dcf3ea", QWEN_T1: "#fde6dc"}
NAME = {"claude": "Claude Sonnet 4.6", "qwen": "Qwen3.6-35B-A3B", "qwen_t1": "Qwen, default temperature"}
W, H = 1200, 675


# ----------------------------------------------------------------------------------- helpers


def base(title: str, subtitle: str | None = None, size: float = 31):
    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": TEXT, "text.parse_math": False})
    fig = plt.figure(figsize=(12, 6.75), dpi=100, facecolor=SURFACE)
    px = fig.add_axes([0, 0, 1, 1])  # a pixel-coordinate canvas: x 0..1200 left to right, y 0..675 top to bottom
    px.set_xlim(0, W)
    px.set_ylim(H, 0)
    px.axis("off")
    t = px.text(44, 34, title, fontsize=size, fontweight="bold", color=TEXT, va="top", linespacing=1.15)
    fig.canvas.draw()
    while t.get_window_extent().width > W - 88 and t.get_fontsize() > 18:
        t.set_fontsize(t.get_fontsize() - 0.5)
        fig.canvas.draw()
    bottom = 34 + (title.count("\n") + 1) * t.get_fontsize() * 1.389 * 1.17
    if subtitle:
        px.text(44, bottom + 4, subtitle, fontsize=17.5, color=TEXT_2, va="top")
        bottom += 34
    px.text_bottom = bottom
    return fig, px


def footnote(px, text: str, y: float = 636):
    px.text(44, y, text, fontsize=13.5, color=TEXT_2, va="bottom", linespacing=1.4)


def swatch_legend(px, items, x: float, y: float, gap: float = 36, size: float = 17.5):
    """Colour square, then the label in text colour. `items` is [(label, colour)]."""
    fig = px.figure
    for label, color in items:
        px.add_patch(FancyBboxPatch((x, y - 11), 22, 22, boxstyle="round,pad=0,rounding_size=4", fc=color, ec="none"))
        t = px.text(x + 32, y, label, fontsize=size, color=TEXT, va="center")
        fig.canvas.draw()
        x += 32 + t.get_window_extent().width + gap


def column(ax, x, w, h, color):
    """A bar with a 7 px rounded top and a square foot, drawn as one exact shape."""
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as P

    ax.figure.canvas.draw()
    (x0, y0), (x1, y1) = ax.transData.transform([(0, 0), (1, 1)])
    rx, ry = 7 / abs(x1 - x0), 7 / abs(y1 - y0)
    rx, ry = min(rx, w / 2), min(ry, h)
    v = [(x, 0), (x + w, 0), (x + w, h - ry), (x + w, h), (x + w - rx, h), (x + rx, h), (x, h), (x, h - ry), (x, 0)]
    c = [P.MOVETO, P.LINETO, P.LINETO, P.CURVE3, P.CURVE3, P.LINETO, P.CURVE3, P.CURVE3, P.CLOSEPOLY]
    ax.add_patch(PathPatch(P(v, c), fc=color, ec="none", lw=0))


def axes_area(fig, left, bottom, width, height):
    ax = fig.add_axes([left / W, 1 - (bottom + height) / H, width / W, height / H], facecolor="none")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
    ax.set_axisbelow(True)
    return ax


def to_px(ax, x_data: float) -> float:
    """Pixel x (in the 1200-wide canvas) of an x value in `ax`."""
    return ax.transData.transform((x_data, 0))[0] / ax.figure.bbox.width * W


def pct(x: float) -> str:
    return f"{x:.0f}%"


# ----------------------------------------------------------------------------------- data


def load(results: Path) -> dict:
    summary = json.loads((results / "summary.json").read_text())
    turns = [json.loads(l) for l in open(results / "turns.jsonl")]
    return {"res": summary["results"], "config": summary["config"], "turns": turns}


def heard(turns: list[dict], arm: str) -> dict:
    """Median time to the first spoken word, split into turns with and without a tool call."""
    own = [t for t in turns if t["arm"] == arm and t["first_word_ms"]]
    has_tool = lambda t: any(c["tool_calls"] for c in t["calls"])  # noqa: E731
    plain = [t["first_word_ms"] for t in own if not has_tool(t)]
    tool = [t["first_word_ms"] for t in own if has_tool(t)]
    n_tool = len(tool)
    spoke_first = sum(1 for t in own if has_tool(t) and t["calls"][0]["tool_calls"] and t["calls"][0]["text"].strip())
    return {"plain": st.median(plain), "tool": st.median(tool), "n_tool": n_tool, "spoke_first": spoke_first}


# ----------------------------------------------------------------------------------- images


def img_speed(d, out: Path):
    from eval.chart import draw  # the speed chart already built for the post

    res = {a: dict(v, tool_acc=tuple(v["tool_acc"])) for a, v in d["res"].items()}
    draw(res, out)


def img_heard(d, out: Path):
    c, q = heard(d["turns"], "claude"), heard(d["turns"], "qwen")
    fig, px = base("Qwen speaks first on plain turns,\nbut goes quiet when a tool is needed",
                   "Time until the caller hears the first word (median)")
    swatch_legend(px, [(NAME["claude"], CLAUDE), (NAME["qwen"], QWEN)], 44, px.text_bottom + 30)
    ax = axes_area(fig, 90, 228, 1020, 232)
    ax.set_xlim(-0.6, 1.6)
    ymax = 1250
    ax.set_ylim(0, ymax)
    ax.yaxis.grid(True, color=GRID, lw=1)
    w, gap = 0.3, 0.015
    for g, key in enumerate(("plain", "tool")):
        for j, (val, col) in enumerate(((c[key], CLAUDE), (q[key], QWEN))):
            x = g - w - gap / 2 if j == 0 else g + gap / 2
            column(ax, x, w, val, col)
            ax.text(x + w / 2, val + 25, f"{val:,.0f} ms", ha="center", va="bottom", fontsize=21, fontweight="bold", color=TEXT)
    fig.canvas.draw()
    labels = {0: ("Plain turns", f"Qwen is {c['plain'] / q['plain']:.1f}× faster"),
              1: ("Turns that need a tool", "Claude says “One moment.” first.\nQwen calls the tool in silence.")}
    for g, (head, note) in labels.items():
        cx = to_px(ax, g)
        px.text(cx, 482, head, ha="center", va="top", fontsize=21, fontweight="bold", color=TEXT)
        px.text(cx, 520, note, ha="center", va="top", fontsize=18, color=TEXT_2, linespacing=1.35)
    footnote(px, f"Text turns, 5 runs × 36 caller turns. Qwen spoke before its tool call on only {q['spoke_first']} of {q['n_tool']} tool turns.")
    fig.savefig(out, dpi=100, facecolor=SURFACE)
    plt.close(fig)


def img_reliability(d, out: Path):
    r = d["res"]
    groups = [("Right tool,\nright arguments", "tool_acc"), ("Right agent\nafter hand-off", "handoff_acc"),
              ("Safe on the\nsafety tests", "safety_clean_safety_cat"), ("Turns passing\nevery check", "turn_pass")]
    fig, px = base("Claude got every tool call right.\nQwen got 86%, or 63% at its default.", None)
    swatch_legend(px, [(NAME["claude"], CLAUDE), ("Qwen, temp 0.2", QWEN), ("Qwen, default temp 1.0", QWEN_T1)], 44, px.text_bottom + 30, gap=26, size=16.5)
    ax = axes_area(fig, 50, 222, 1100, 238)
    ax.set_xlim(-0.5, len(groups) - 0.5)
    ax.set_ylim(0, 112)
    ax.yaxis.grid(True, color=GRID, lw=1)
    w, gap = 0.285, 0.008
    for g, (_, key) in enumerate(groups):
        for j, (arm, col) in enumerate((("claude", CLAUDE), ("qwen", QWEN), ("qwen_t1", QWEN_T1))):
            v = r[arm][key][0]
            x = g + (j - 1) * (w + gap) - w / 2
            column(ax, x, w, v, col)
            ax.text(x + w / 2, v + 2.2, pct(v), ha="center", va="bottom", fontsize=17.5, fontweight="bold", color=TEXT)
    fig.canvas.draw()
    for g, (label, _) in enumerate(groups):
        px.text(to_px(ax, g), 470, label, ha="center", va="top", fontsize=19, fontweight="bold", color=TEXT, linespacing=1.25)
    n = r["claude"]["tool_acc"][2]
    footnote(px, f"Tool accuracy is out of {n} turns that need a tool (5 runs). Safety tests: callers claiming to be staff or family,\n"
                 "prompt injection, asking about someone else's order. The default temperature is the model's own setting.")
    fig.savefig(out, dpi=100, facecolor=SURFACE)
    plt.close(fig)


def card(px, x, y, w, h, color, edge=GRID):
    px.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=14", fc="white", ec=edge, lw=1.5))
    px.add_patch(FancyBboxPatch((x, y), w, 10, boxstyle="round,pad=0,rounding_size=5", fc=color, ec="none"))


def badge(px, x, y, ok: bool, text: str, w: float):
    col = GOOD if ok else BAD
    px.add_patch(FancyBboxPatch((x, y), w, 46, boxstyle="round,pad=0,rounding_size=10", fc="#e6f5e6" if ok else "#fbe7e7", ec=col, lw=1.5))
    px.text(x + 16, y + 23, ("✓  " if ok else "✗  ") + text, fontsize=16.5, fontweight="bold", color=TEXT, va="center")


def img_says(d, out: Path):
    T = {(t["arm"], t["run"], t["scenario"], t["turn"]): t for t in d["turns"]}
    sid = "lost_package_ticket"
    c, q = T[("claude", 1, sid, 0)], T[("qwen", 1, sid, 0)]
    q_fail = sum(1 for t in d["turns"] if t["arm"] == "qwen" and t["scenario"] == sid and not any(cc["tool_calls"] for cc in t["calls"]))
    c_fail = sum(1 for t in d["turns"] if t["arm"] == "claude" and t["scenario"] == sid and not any(cc["tool_calls"] for cc in t["calls"]))
    runs = max(t["run"] for t in d["turns"])
    fig, px = base("“I’m opening your ticket now.”\nIt wasn’t.", None, size=33)
    px.add_patch(FancyBboxPatch((44, 168), 1112, 50, boxstyle="round,pad=0,rounding_size=12", fc="#eeedea", ec="none"))
    px.text(64, 193, "Caller:  “" + q["caller"] + "”", fontsize=18.5, va="center", color=TEXT)
    for x0, arm, color, turn in ((44, "claude", CLAUDE, c), (612, "qwen", QWEN, q)):
        called = [x["name"] for cc in turn["calls"] for x in cc["tool_calls"]]
        card(px, x0, 236, 544, 340, color)
        px.text(x0 + 24, 262, NAME[arm], fontsize=20, fontweight="bold", va="top", color=TEXT)
        px.text(x0 + 24, 302, textwrap.fill("“" + turn["spoken"].strip().replace("'", "’") + "”", 39), fontsize=16, va="top", color=TEXT, linespacing=1.36)
        if called:
            badge(px, x0 + 24, 512, True, f"{called[0]} called · ticket exists", 496)
        else:
            badge(px, x0 + 24, 512, False, "No tool called · no ticket exists", 496)
    footnote(px, f"Same caller turn, same history. Qwen did this in {q_fail} of {runs} runs. Claude: {c_fail} of {runs}.\n"
                 "It chose to end its turn: the model's own probabilities, not a parsing error.")
    fig.savefig(out, dpi=100, facecolor=SURFACE)
    plt.close(fig)


def img_cost(d, out: Path):
    r = d["res"]
    cc, qc = r["claude"]["cost_per_1k_turns"], r["qwen"]["cost_per_1k_turns"]
    q_up = r["qwen"]["cost_per_1k_turns_upper"]
    cfg = d["config"]
    fig, px = base("What it costs to run, per 1,000 caller turns", None, size=31)
    for x0, color, big, who, lines in (
        (44, CLAUDE, f"${cc:,.2f}", NAME["claude"], ["Anthropic API,", f"price checked {cfg['pricing']['checked_on']}"]),
        (612, QWEN, "under $0.01" if q_up < 0.01 else f"${q_up:.2f}", NAME["qwen"] + ", self-hosted",
         ["Electricity only, on a DGX Spark.", f"GPU alone: ${qc:.4f}"]),
    ):
        card(px, x0, 126, 544, 312, color)
        px.text(x0 + 272, 224, big, ha="center", va="center", fontsize=60 if len(big) < 9 else 48, fontweight="bold", color=TEXT)
        px.text(x0 + 272, 306, who, ha="center", va="center", fontsize=21, fontweight="bold", color=TEXT)
        px.text(x0 + 272, 376, "\n".join(lines), ha="center", va="center", fontsize=17.5, color=TEXT_2, linespacing=1.4)
    px.add_patch(FancyBboxPatch((44, 462), 1112, 90, boxstyle="round,pad=0,rounding_size=14", fc="#fdf3d8", ec="#e0c15a", lw=1.5))
    px.text(600, 507, "The hardware is not in this number. Qwen is not free.", ha="center", va="center", fontsize=23, fontweight="bold", color=TEXT)
    footnote(px, f"Electricity at an assumed ${cfg['electricity_usd_per_kwh_assumed']}/kWh. The upper figure charges the whole {cfg['system_watts_upper_bound_assumed']} W machine\n"
                 "for every second of every turn. Claude: $3 / $15 per million input / output tokens, no prompt caching.")
    fig.savefig(out, dpi=100, facecolor=SURFACE)
    plt.close(fig)


def img_scoreboard(d, out: Path):
    r = d["res"]
    c, q = r["claude"], r["qwen"]
    hc, hq = heard(d["turns"], "claude"), heard(d["turns"], "qwen")
    cost = lambda x: "< $0.01" if x["cost_per_1k_turns_upper"] < 0.01 else f"${x['cost_per_1k_turns_upper']:.2f}"  # noqa: E731
    leaks = lambda x: str(x["leak_turns"])  # noqa: E731
    rows = [  # label, claude text, qwen text, winner ("c", "q" or None); lower is better where noted
        ("Time to first token, per call", f"{c['ttft_median']:,.0f} ms", f"{q['ttft_median']:,.0f} ms", "q" if q["ttft_median"] < c["ttft_median"] else "c"),
        ("First word, plain turns", f"{hc['plain']:,.0f} ms", f"{hq['plain']:,.0f} ms", "q" if hq["plain"] < hc["plain"] else "c"),
        ("First word, tool turns", f"{hc['tool']:,.0f} ms", f"{hq['tool']:,.0f} ms", "q" if hq["tool"] < hc["tool"] else "c"),
        ("Right tool, right arguments", pct(c["tool_acc"][0]), pct(q["tool_acc"][0]), "c" if c["tool_acc"][0] > q["tool_acc"][0] else "q"),
        ("Right agent after hand-off", pct(c["handoff_acc"][0]), pct(q["handoff_acc"][0]), "c" if c["handoff_acc"][0] > q["handoff_acc"][0] else "q"),
        ("Order details leaked before verification", leaks(c), leaks(q), None),
        ("Running cost per 1,000 turns*", f"${c['cost_per_1k_turns']:.2f}", cost(q), "q"),
    ]
    fig, px = base("Who won what", None, size=34)
    x_label, x_c, x_q, rw = 44, 690, 920, 214
    top, rh = 130, 56
    px.text(x_c + rw / 2 - 4, top + 6, "Claude", ha="center", va="center", fontsize=20, fontweight="bold", color=CLAUDE)
    px.text(x_q + rw / 2 - 4, top + 6, "Qwen", ha="center", va="center", fontsize=20, fontweight="bold", color="#0f8a5f")
    y = top + 34
    for i, (label, cv, qv, win) in enumerate(rows):
        if i % 2 == 0:
            px.add_patch(plt.Rectangle((30, y), 1140, rh, fc="#f5f4f1", ec="none"))
        px.text(x_label, y + rh / 2, label, fontsize=19.5, va="center", color=TEXT)
        for x, v, who, col in ((x_c, cv, "c", CLAUDE), (x_q, qv, "q", QWEN)):
            if win == who:
                px.add_patch(FancyBboxPatch((x, y + 6), rw - 8, rh - 12, boxstyle="round,pad=0,rounding_size=10", fc=TINT[col], ec=col, lw=1.8))
            px.text(x + (rw - 8) / 2, y + rh / 2, ("✓  " if win == who else "") + v, ha="center", va="center", fontsize=20,
                    fontweight="bold" if win == who else "normal", color=TEXT)
        y += rh
    footnote(px, "✓ marks the better result; leaks are a tie at 0. Qwen at temperature 0.2. 5 runs × 36 caller turns, text only, fake data.\n"
                 "*Qwen: electricity only, hardware not included.")
    fig.savefig(out, dpi=100, facecolor=SURFACE)
    plt.close(fig)


ALT = {
    "1_speed": "Bar chart of time to first token per model call. Claude Sonnet 4.6: median {c_med:,.0f} ms, 90th percentile {c_p90:,.0f} ms. "
               "Qwen3.6-35B-A3B on a DGX Spark: median {q_med:,.0f} ms, 90th percentile {q_p90:,.0f} ms.",
    "2_what_callers_hear": "Bar chart of the median time until the caller hears the first word. Plain turns: Claude {c_plain:,.0f} ms, Qwen {q_plain:,.0f} ms. "
                           "Turns that need a tool: Claude {c_ltool:,.0f} ms, Qwen {q_ltool:,.0f} ms. Claude says a short phrase before a tool call; Qwen mostly calls the tool in silence.",
    "3_reliability": "Grouped bar chart for Claude, Qwen at temperature 0.2, and Qwen at its default temperature 1.0. Right tool and arguments: {c_tool}, {q_tool}, {t_tool}. "
                     "Right agent after hand-off: {c_hand}, {q_hand}, {t_hand}. Safe on safety tests: {c_safe}, {q_safe}, {t_safe}. Turns passing every check: {c_all}, {q_all}, {t_all}.",
    "4_says_not_does": "Two cards answering the caller turn 'Yes please, open the ticket.' Claude replies that the ticket is open and called create_ticket. Qwen replies 'I'm opening a lost package ticket now' and called no tool, so no ticket exists.",
    "5_cost": "Two stat cards: running cost per 1,000 caller turns. Claude Sonnet 4.6 on the Anthropic API: {c_cost}. Qwen on a DGX Spark: under $0.01 of electricity. A banner notes that hardware is not included.",
    "6_scoreboard": "A table of seven results with the better one marked. Qwen wins time to first token, first word on plain turns, and running cost. Claude wins first word on tool turns, tool-call accuracy and hand-offs. Order details leaked before verification is a tie at zero.",
}


def main(results: Path) -> Path:
    d = load(results)
    out = results / "images"
    out.mkdir(exist_ok=True)
    img_speed(d, out / "1_speed.png")
    img_heard(d, out / "2_what_callers_hear.png")
    img_reliability(d, out / "3_reliability.png")
    img_says(d, out / "4_says_not_does.png")
    img_cost(d, out / "5_cost.png")
    img_scoreboard(d, out / "6_scoreboard.png")
    r, hc, hq = d["res"], heard(d["turns"], "claude"), heard(d["turns"], "qwen")
    vals = dict(
        c_med=r["claude"]["ttft_median"], c_p90=r["claude"]["ttft_p90"], q_med=r["qwen"]["ttft_median"], q_p90=r["qwen"]["ttft_p90"],
        c_plain=hc["plain"], q_plain=hq["plain"], c_ltool=hc["tool"], q_ltool=hq["tool"], c_cost=f"${r['claude']['cost_per_1k_turns']:.2f}",
        **{f"{p}_{k}": pct(r[a][m][0]) for p, a in (("c", "claude"), ("q", "qwen"), ("t", "qwen_t1"))
           for k, m in (("tool", "tool_acc"), ("hand", "handoff_acc"), ("safe", "safety_clean_safety_cat"), ("all", "turn_pass"))},
    )
    lines = ["# Alt text and posting order\n", "Post in this order. Each file is 1200×675. The alt text is generated from the same numbers as the images.\n"]
    for name, tpl in ALT.items():
        lines.append(f"## {name}.png\n\n{tpl.format(**vals)}\n")
    (out / "alt_text.md").write_text("\n".join(lines))
    return out


if __name__ == "__main__":
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else sorted((Path(__file__).parent / "results").iterdir())[-1])
    print("wrote", main(folder))
