"""The comparison chart: median and 90th-percentile time to first token per model, as a 1200x675 PNG.

Static image for a post, so everything a reader needs is printed on it: values on the bars,
tool-call accuracy and running cost under each model, and the method in one footnote.
Colours: the first two categorical slots of the dataviz reference palette (validated: CVD and
normal-vision separation pass, both >= 3:1 on the surface). Text uses text tokens, never series colours.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
MEDIAN = "#2a78d6"  # slot 1, blue
P90 = "#eb6834"  # slot 2, orange

NAMES = {
    "claude": ("Claude Sonnet 4.6", "Anthropic API, over the internet"),
    "qwen": ("Qwen3.6-35B-A3B", "self-hosted on a DGX Spark, localhost"),
    "qwen_t1": ("Qwen3.6-35B-A3B, temp 1.0", "self-hosted, model's default sampling"),
}


def _column(ax, x, width, height, color, radius_px=6):
    """A column with a rounded data end and a square foot on the baseline."""
    # rounding in data units: convert a pixel radius using the axes' current scale
    (x0, y0), (x1, y1) = ax.transData.transform([(0, 0), (1, 1)])
    rx = radius_px / max(x1 - x0, 1e-9)
    ry = radius_px / max(y1 - y0, 1e-9)
    r = min(rx, width / 2)
    ax.add_patch(FancyBboxPatch((x, 0), width, height, boxstyle=f"round,pad=0,rounding_size={r}",
                                mutation_aspect=ry / r if r else 1, linewidth=0, facecolor=color))
    ax.add_patch(Rectangle((x, 0), width, min(height, ry * 1.2), linewidth=0, facecolor=color))


def _cost(r: dict) -> str:
    if "cost_total" in r:
        return f"${r['cost_per_1k_turns']:.2f} API cost"
    if r.get("cost_per_1k_turns") is not None:
        upper = r.get("cost_per_1k_turns_upper")
        if upper is not None and upper < 0.01:
            return "under $0.01 electricity*"
        return f"${upper:.2f} electricity*" if upper else f"${r['cost_per_1k_turns']:.3f} electricity*"
    return "n/a"


def default_title(res: dict) -> str:
    c, q = res["claude"], res["qwen"]
    ratio = c["ttft_median"] / q["ttft_median"]
    ca, qa = c["tool_acc"][0], q["tool_acc"][0]
    speed = f"Qwen starts answering {ratio:.1f}× sooner" if ratio >= 1.15 else "Similar first-token speed"
    if qa + 3 < ca:
        return f"{speed}, but gets fewer tool calls right ({qa:.0f}% vs {ca:.0f}%)"
    if ca + 3 < qa:
        return f"{speed} and gets more tool calls right ({qa:.0f}% vs {ca:.0f}%)"
    return f"{speed}, with similar tool-call accuracy ({qa:.0f}% vs {ca:.0f}%)"


def draw(res: dict, path: Path, arms: tuple = ("claude", "qwen"), title: str | None = None,
         footnote: str | None = None) -> None:
    arms = [a for a in arms if a in res]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 15, "text.color": TEXT,
                         "axes.labelcolor": TEXT_2, "xtick.color": TEXT_2, "ytick.color": TEXT_2})
    fig = plt.figure(figsize=(12, 6.75), dpi=100, facecolor=SURFACE)
    ax = fig.add_axes([0.085, 0.385, 0.89, 0.37], facecolor=SURFACE)

    # title: shrink until it fits the width
    t = fig.text(0.03, 0.945, title or default_title(res), fontsize=24, fontweight="bold", color=TEXT, va="top")
    fig.canvas.draw()
    while t.get_window_extent().width > fig.bbox.width * 0.94 and t.get_fontsize() > 16:
        t.set_fontsize(t.get_fontsize() - 0.5)
        fig.canvas.draw()
    runs = res[arms[0]]["runs"]
    turns = res[arms[0]]["turns"] // max(runs, 1)
    fig.text(0.03, 0.872, f"Time to first token per model call, same agent, prompts and tools · {runs} run{'s' if runs != 1 else ''} × {turns} caller turns",
             fontsize=15, color=TEXT_2, va="top")

    ymax = max(res[a]["ttft_p90"] for a in arms) * 1.22
    ax.set_xlim(-0.55, len(arms) - 0.45)
    ax.set_ylim(0, ymax)
    fig.canvas.draw()  # so the data->pixel transform is final before drawing rounded columns

    w, gap = 0.17, 0.012
    for i, a in enumerate(arms):
        r = res[a]
        for j, (val, color) in enumerate(((r["ttft_median"], MEDIAN), (r["ttft_p90"], P90))):
            x = i - w - gap / 2 if j == 0 else i + gap / 2
            _column(ax, x, w, val, color)
            ax.text(x + w / 2, val + ymax * 0.018, f"{val:,.0f} ms", ha="center", va="bottom", fontsize=16,
                    fontweight="bold", color=TEXT)

    ax.yaxis.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="y", length=0, labelsize=13)
    ax.tick_params(axis="x", length=0)
    ax.set_xticks([])
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_ylabel("milliseconds", fontsize=13)

    # model names and the two other headline numbers, under each group
    for i, a in enumerate(arms):
        r = res[a]
        name, sub = NAMES[a]
        xf = ax.transData.transform((i, 0))[0] / fig.bbox.width
        fig.text(xf, 0.355, name, ha="center", va="top", fontsize=18, fontweight="bold", color=TEXT)
        fig.text(xf, 0.305, sub, ha="center", va="top", fontsize=13, color=TEXT_2)
        fig.text(xf, 0.245, f"Tool calls right: {r['tool_acc'][0]:.0f}%", ha="center", va="top", fontsize=16, color=TEXT)
        fig.text(xf, 0.195, f"Per 1,000 turns: {_cost(r)}", ha="center", va="top", fontsize=16, color=TEXT)

    # legend: swatch beside text, text in text colour
    lx, ly = 0.03, 0.815
    for k, (label, color) in enumerate((("Median", MEDIAN), ("90th percentile", P90))):
        x = lx + k * 0.095
        fig.patches.append(FancyBboxPatch((x, ly - 0.028), 0.014, 0.025, boxstyle="round,pad=0,rounding_size=0.003",
                                          transform=fig.transFigure, facecolor=color, linewidth=0))
        fig.text(x + 0.02, ly - 0.016, label, fontsize=14, color=TEXT, va="center")

    fig.text(0.03, 0.03, footnote or (
        "Text turns, no speech recognition or synthesis. Claude's time includes the internet round trip; Qwen's is on localhost.\n"
        "*Qwen: electricity only, whole box at its 240 W maximum, $0.15/kWh assumed; hardware cost not included."),
        fontsize=12, color=TEXT_2, va="bottom", linespacing=1.4)

    fig.savefig(path, dpi=100, facecolor=SURFACE)
    plt.close(fig)
