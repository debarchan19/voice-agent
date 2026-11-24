"""Images for the LinkedIn post about the Qwen fixes (docs/qwen_fix_log.md). Every number is read from result files.

    python eval/make_fix_images.py                    # writes linkedin_fixes_kit/images/ + alt_text.md + carousel.pdf

Six slides, 1200x675, light surface, same colours as the earlier post: Claude violet, Qwen aqua. "Qwen before the
fixes" is the same aqua as a pale, outlined bar, so a model keeps one colour and only its state changes (a third
hue failed the palette validator: grey has no chroma and sits too close to the aqua). Values are printed on every
bar, which the validator's contrast warning on the aqua requires.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, PathPatch  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402

from eval.make_images import (  # noqa: E402
    CLAUDE, GOOD, GRID, QWEN, SURFACE, TEXT, TEXT_2, TINT, W, axes_area, base, card, footnote, pct, to_px,
)

R = ROOT / "eval" / "results" / "qwen_fixes"
FINAL = R / "FINAL_three_way"
OUT = ROOT / "linkedin_fixes_kit"
PALE = TINT[QWEN]


def summary(d: Path) -> dict:
    return json.loads((d / "summary.json").read_text())


def column(ax, x, w, h, fc, ec=None, lw=0):
    """A bar with a 7 px rounded top and a square foot (the earlier posts' mark), optionally outlined."""
    ax.figure.canvas.draw()
    (x0, y0), (x1, y1) = ax.transData.transform([(0, 0), (1, 1)])
    rx, ry = min(7 / abs(x1 - x0), w / 2), min(7 / abs(y1 - y0), h)
    v = [(x, 0), (x + w, 0), (x + w, h - ry), (x + w, h), (x + w - rx, h), (x + rx, h), (x, h), (x, h - ry), (x, 0)]
    c = [MPath.MOVETO, MPath.LINETO, MPath.LINETO, MPath.CURVE3, MPath.CURVE3, MPath.LINETO, MPath.CURVE3, MPath.CURVE3, MPath.CLOSEPOLY]
    ax.add_patch(PathPatch(MPath(v, c), fc=fc, ec=ec or "none", lw=lw))


def legend(px, items, x, y, size=16.5, gap=28):
    """items: [(label, fill, edge)]"""
    fig = px.figure
    for label, fc, ec in items:
        px.add_patch(FancyBboxPatch((x, y - 11), 22, 22, boxstyle="round,pad=0,rounding_size=4", fc=fc, ec=ec or "none", lw=2))
        t = px.text(x + 32, y, label, fontsize=size, color=TEXT, va="center")
        fig.canvas.draw()
        x += 32 + t.get_window_extent().width + gap


def grouped(fig, px, groups, series, ymax, top, height, label_y, label_size=18, bar_w=0.27):
    """groups: [(label, [values per series])]; series: [(fill, edge)] aligned with the values."""
    ax = axes_area(fig, 50, top, 1100, height)
    ax.set_xlim(-0.5, len(groups) - 0.5)
    ax.set_ylim(0, ymax)
    ax.yaxis.grid(True, color=GRID, lw=1)
    n, gap = len(series), 0.012
    for g, (_, vals) in enumerate(groups):
        for j, (v, (fc, ec)) in enumerate(zip(vals, series)):
            x = g + (j - (n - 1) / 2) * (bar_w + gap) - bar_w / 2
            column(ax, x, bar_w, v, fc, ec, 2.2 if ec else 0)
            ax.text(x + bar_w / 2, v + ymax * 0.02, f"{v:.0f}%", ha="center", va="bottom", fontsize=19, fontweight="bold", color=TEXT)
    fig.canvas.draw()
    for g, (label, _) in enumerate(groups):
        px.text(to_px(ax, g), label_y, label, ha="center", va="top", fontsize=label_size, fontweight="bold", color=TEXT, linespacing=1.25)


def rows(px, items, y0, rh, with_icon=None):
    """List slide: bold change, grey effect underneath, a bold metric and caption on the right."""
    for i, (head, effect, metric, caption) in enumerate(items):
        y = y0 + i * rh
        if i % 2 == 0:
            px.add_patch(plt.Rectangle((30, y), 1140, rh - 4, fc="#f5f4f1", ec="none"))
        if with_icon:
            px.text(52, y + (rh - 4) / 2, with_icon[0], fontsize=26, fontweight="bold", va="center", color=with_icon[1])
        px.text(100, y + 22, textwrap.fill(head, 44), fontsize=19.5, fontweight="bold", va="center", color=TEXT)
        px.text(100, y + 56, effect, fontsize=15.5, va="center", color=TEXT_2)
        px.text(1150, y + 26, metric, ha="right", fontsize=23, fontweight="bold", va="center", color=TEXT)
        px.text(1150, y + 58, caption, ha="right", fontsize=13.5, va="center", color=TEXT_2)


# ----------------------------------------------------------------------------------------------- numbers


def numbers() -> dict:
    f = summary(FINAL)
    all_, dev, hold = f["results"], f["results_dev"], f["results_holdout"]
    n: dict = {}
    for a in ("claude", "qwen_base", "qwen", "qwen_base_t1", "qwen_t1"):
        n[a] = {"tool": all_[a]["tool_acc"][0], "pass": all_[a]["turn_pass"][0], "ttft": all_[a]["ttft_median"],
                "junk": all_[a]["junk_args"], "ft_tool": all_[a]["first_word_tool_median"],
                "early": all_[a]["early_handoff"][0], "guard_turns": all_[a]["guard_turns"],
                "guard_ms": all_[a]["guard_retry_ms_median"], "turns": all_[a]["turns"],
                "dev_tool": dev[a]["tool_acc"][0], "hold_tool": hold[a]["tool_acc"][0],
                "dev_pass": dev[a]["turn_pass"][0], "hold_pass": hold[a]["turn_pass"][0]}
    per = {a: all_[a]["per_scenario_pass"] for a in ("qwen_base", "qwen")}
    n["lost"] = (per["qwen_base"]["lost_package_ticket"], per["qwen"]["lost_package_ticket"])
    n["resched"] = (per["qwen_base"]["reschedule_confirm_flow"], per["qwen"]["reschedule_confirm_flow"])
    dev_tool = lambda d: summary(R / d)["results_dev"]["qwen"]["tool_acc"][0]  # noqa: E731
    n["a2_a4"] = (dev_tool("A2_omit_empty_args"), dev_tool("A4_no_unverified_status"))
    n["a3"] = (dev_tool("A2_omit_empty_args"), dev_tool("A3_filler_first"))
    safe = lambda d: summary(R / d)["results_dev"]["qwen"]["safety_clean_safety_cat"]  # noqa: E731
    n["a5_safe"] = (safe("A4_no_unverified_status"), safe("A5_few_shot"))
    x = summary(R / "D_parser_qwen3_xml")["results"]["qwen"]["tool_acc"]
    n["xml"] = (x[1], x[2])

    def handoff_with_junk(d):  # turns that carried a "None" value, and how many still reached Order Status
        tot = ok = 0
        for line in open(R / d / "turns.jsonl"):
            t = json.loads(line)
            if t["arm"] != "qwen":
                continue
            if any(str(v).strip().lower() in ("none", "null", "undefined", "") for c in t["calls"] for tc in c["tool_calls"] for v in tc["args"].values()):
                tot += 1
                ok += t["state_after"]["active_agent"] == "order_status"
        return ok, tot
    n["b1"] = (handoff_with_junk("B0_baseline"), handoff_with_junk("B1x_on_baseline_prompt"))
    return n


# ----------------------------------------------------------------------------------------------- slides


def s1_result(n, out):
    fig, px = base(f"Tool-call accuracy: {n['qwen_base']['tool']:.0f}% to {n['qwen']['tool']:.0f}%",
                   "Qwen3.6-35B-A3B on a DGX Spark, before and after the fixes. Claude for reference.", size=36)
    legend(px, [("Claude", CLAUDE, None), ("Qwen before the fixes", PALE, QWEN), ("Qwen after the fixes", QWEN, None)],
           44, px.text_bottom + 30)
    series = [(CLAUDE, None), (PALE, QWEN), (QWEN, None)]
    groups = [("Temperature 0.2\n(the setting I use)", [n["claude"]["tool"], n["qwen_base"]["tool"], n["qwen"]["tool"]]),
              ("Temperature 1.0\n(the model's default)", [n["claude"]["tool"], n["qwen_base_t1"]["tool"], n["qwen_t1"]["tool"]])]
    grouped(fig, px, groups, series, 118, 232, 232, 478, label_size=19)
    footnote(px, "29 scenarios, 5 runs each. Includes the scenarios the fixes were tuned on: slide 4 shows the ones I held back.")
    fig.savefig(out, dpi=100, facecolor=SURFACE)
    plt.close(fig)


def s2_worked(n, out):
    fig, px = base("Five changes that worked", "Each added on its own, then the full test. Claude's prompts were not touched.", size=36)
    (b0, b0n), (b1, b1n) = n["b1"]
    items = [
        ("Call the tool in the same reply", "Stops “I'm opening your ticket” with no ticket",
         f"{n['lost'][0][1]}/{n['lost'][0][2]} → {n['lost'][1][1]}/{n['lost'][1][2]}", "lost-package scenario passing"),
        ("Leave out arguments you don't have", "The string “None” sent as a value",
         f"{n['qwen_base']['junk']} → {n['qwen']['junk']}", "junk values, 29 scenarios × 5 runs"),
        ("Don't state a status no tool returned", "Aimed at made-up statuses; the gain showed in tool accuracy",
         f"{n['a2_a4'][0]:.0f}% → {n['a2_a4'][1]:.0f}%", "tool accuracy on dev scenarios"),
        ("Code: treat “None” as a missing argument", "Gate untouched: a “None” order id is still refused",
         f"{b1}/{b1n} handed off", f"turns carrying “None” (before: {b0}/{b0n})"),
        ("Catch claimed actions with no tool call", "Retries once, through the same gate",
         f"fired on {n['qwen']['guard_turns']} of {n['qwen']['turns']}", "caller turns, temperature 0.2"),
    ]
    rows(px, items, 140, 98, with_icon=("✓", GOOD))
    fig.savefig(out, dpi=100, facecolor=SURFACE)
    plt.close(fig)


def s3_didnt(n, out):
    fig, px = base("What didn't work", "Tried, measured, dropped or left unsolved.", size=36)
    (rb, rbn), (ra, ran) = (n["resched"][0][1], n["resched"][0][2]), (n["resched"][1][1], n["resched"][1][2])
    items = [
        ("Say “One moment” before every tool call", "Fixed the silence. Broke the tool calls.",
         f"{n['a3'][0]:.0f}% → {n['a3'][1]:.0f}%", "tool accuracy, dev"),
        ("Act-first: reschedules before the yes", "Made worse by a fix that helped elsewhere.",
         f"{rb}/{rbn} → {ra}/{ran}", "held-out reschedule scenario passing"),
        ("Worked examples in the prompt", "Safety got worse",
         f"{n['a5_safe'][0][1]} → {n['a5_safe'][1][1]} of {n['a5_safe'][0][2]}", "safety turns clean, dev"),
        ("The other tool-call parser (qwen3_xml)", "Every tool call came out as spoken text",
         f"{n['xml'][0]} of {n['xml'][1]}", "tool-call turns right"),
        ("Temperature 0 to 0.3, top_p, top_k", "Nothing beat the 0.2 default",
         "noise", "time to first token flat at ~335 ms"),
    ]
    rows(px, items, 140, 98, with_icon=("✗", "#d03b3b"))
    fig.savefig(out, dpi=100, facecolor=SURFACE)
    plt.close(fig)


def s4_heldout(n, out):
    fig, px = base("On the scenarios I held back,\nthe gain mostly disappeared", "Qwen at temperature 0.2. “All checks passed” = caller turns that passed every check.", size=33)
    legend(px, [("Before the fixes", PALE, QWEN), ("After the fixes", QWEN, None)], 44, px.text_bottom + 30)
    b, a = n["qwen_base"], n["qwen"]
    groups = [("Tool calls right\nDev", [b["dev_tool"], a["dev_tool"]]),
              ("Tool calls right\nHeld-out", [b["hold_tool"], a["hold_tool"]]),
              ("All checks passed\nDev", [b["dev_pass"], a["dev_pass"]]),
              ("All checks passed\nHeld-out", [b["hold_pass"], a["hold_pass"]])]
    grouped(fig, px, groups, [(PALE, QWEN), (QWEN, None)], 118, 240, 222, 478, label_size=17, bar_w=0.34)
    footnote(px, "Dev = 19 scenarios used to write and choose the fixes. Held-out = 10 scenarios never used for either.\n"
                 "The held-out baseline was already high, so there was little room to improve. Claude scored 100% on all of them.")
    fig.savefig(out, dpi=100, facecolor=SURFACE)
    plt.close(fig)


def s5_cost(n, out):
    b, a = n["qwen_base"], n["qwen"]
    fig, px = base("What the fixes cost", None, size=36)
    cards = [(44, f"+{a['ttft'] - b['ttft']:.0f} ms", "median time to first token", f"{b['ttft']:.0f} → {a['ttft']:.0f} ms. The prompt is about 20% longer."),
             (424, f"+{a['guard_ms']:.0f} ms", f"when the retry fires ({a['guard_turns']} of {a['turns']} turns)", "A second model call after the first reply."),
             (804, f"{b['early'] * 1:.0f}% → {a['early']:.0f}%", "hand-offs before the caller confirmed", "Read-back confirmation skipped more often.")]
    for x0, big, who, sub in cards:
        card(px, x0, 126, 352, 340, QWEN)
        px.text(x0 + 176, 218, big, ha="center", va="center", fontsize=36, fontweight="bold", color=TEXT)
        px.text(x0 + 176, 296, textwrap.fill(who, 24), ha="center", va="center", fontsize=19, fontweight="bold", color=TEXT, linespacing=1.3)
        px.text(x0 + 176, 388, textwrap.fill(sub, 30), ha="center", va="center", fontsize=15.5, color=TEXT_2, linespacing=1.4)
    px.add_patch(FancyBboxPatch((44, 492), 1112, 80, boxstyle="round,pad=0,rounding_size=14", fc="#fdf3d8", ec="#e0c15a", lw=1.5))
    px.text(600, 532, f"Still slower than Claude on tool turns: first word {a['ft_tool']:,.0f} ms vs {n['claude']['ft_tool']:,.0f} ms.",
            ha="center", va="center", fontsize=18, fontweight="bold", color=TEXT)
    footnote(px, "Temperature 0.2, 5 runs × 36 caller turns, text only.\nQwen's first word on plain turns is still about 3× sooner than Claude's.")
    fig.savefig(out, dpi=100, facecolor=SURFACE)
    plt.close(fig)


def s6_takeaway(n, out):
    fig, px = base("Hold out scenarios,\nor you won't know what you broke.", None, size=38)
    points = ["29 scenarios and 18 distinct tool situations. At temperature 0.2 the 5 runs are nearly the same run,\nso a gap of 1 to 4 turns is noise.",
              "Text only, fake data, scripted callers, one Claude model (Sonnet 4.6).",
              "I changed my keep/drop rule twice mid-way. Both changes, and why, are in the log.",
              "Not fixed: acting before the caller says yes, silence before a tool call, and a made-up status\nwhen the caller fakes a “system note”."]
    y = 190
    for p in points:
        px.add_patch(plt.Circle((60, y + 14), 6, fc=QWEN, ec="none"))
        wrapped = textwrap.fill(p.replace("\n", " "), 74)
        px.text(84, y, wrapped, fontsize=18.5, va="top", color=TEXT, linespacing=1.4)
        y += 38 * (wrapped.count("\n") + 1) + 26
    footnote(px, "The scenarios, raw results and the full experiment log are in the repo.")
    fig.savefig(out, dpi=100, facecolor=SURFACE)
    plt.close(fig)


def alt_texts(n) -> dict:
    c, b, a = n["claude"], n["qwen_base"], n["qwen"]
    return {
        "1_result": f"Grouped bar chart of tool-call accuracy. At temperature 0.2: Claude {c['tool']:.0f}%, Qwen before the fixes {b['tool']:.0f}%, Qwen after the fixes {a['tool']:.0f}%. "
                    f"At temperature 1.0: Claude {c['tool']:.0f}%, Qwen before {n['qwen_base_t1']['tool']:.0f}%, Qwen after {n['qwen_t1']['tool']:.0f}%.",
        "2_worked": "A list of five changes that worked, each with its effect: calling the tool in the same reply, leaving out arguments the model doesn't have, "
                    "not stating a status no tool returned, treating the string None as a missing argument in code, and retrying once when a reply claims an action with no tool call.",
        "3_didnt": "A list of five things that did not work: saying One moment before tool calls broke tool accuracy, the act-first rule made the model reschedule before the caller's yes, "
                   "worked examples made safety worse, another tool-call parser turned every tool call into spoken text, and sampling changes made no difference.",
        "4_heldout": f"Bar chart, before and after the fixes, at temperature 0.2. Tool calls right: dev {b['dev_tool']:.0f}% to {a['dev_tool']:.0f}%, held-out {b['hold_tool']:.0f}% to {a['hold_tool']:.0f}%. "
                     f"Turns passing every check: dev {b['dev_pass']:.0f}% to {a['dev_pass']:.0f}%, held-out {b['hold_pass']:.0f}% to {a['hold_pass']:.0f}%.",
        "5_cost": f"Three stat cards on what the fixes cost. Median time to first token rose from {b['ttft']:.0f} to {a['ttft']:.0f} ms. The retry adds about {a['guard_ms']:.0f} ms on the {a['guard_turns']} of {a['turns']} turns where it fires. "
                  f"Hand-offs before the caller confirmed a read-back rose from {b['early']:.0f}% to {a['early']:.0f}%.",
        "6_takeaway": "Closing slide: hold out scenarios or you won't know what you broke. Limits: 29 scenarios, text only, fake data, one Claude model, and the keep/drop rule was changed twice. Three problems are not fixed.",
    }


def claims_table(n) -> str:
    c, b, a = n["claude"], n["qwen_base"], n["qwen"]
    rows = [
        ("Tool-call accuracy, Qwen before / after, temp 0.2", f"{b['tool']:.0f}% / {a['tool']:.0f}%", "FINAL_three_way/summary.json results.qwen_base / qwen .tool_acc"),
        ("Tool-call accuracy, Qwen before / after, temp 1.0", f"{n['qwen_base_t1']['tool']:.0f}% / {n['qwen_t1']['tool']:.0f}%", "same, qwen_base_t1 / qwen_t1"),
        ("Claude tool-call accuracy", f"{c['tool']:.0f}%", "same, claude"),
        ("Dev tool accuracy before / after", f"{b['dev_tool']:.0f}% / {a['dev_tool']:.0f}%", "results_dev"),
        ("Held-out tool accuracy before / after", f"{b['hold_tool']:.0f}% / {a['hold_tool']:.0f}%", "results_holdout"),
        ("Held-out turns passing every check before / after", f"{b['hold_pass']:.0f}% / {a['hold_pass']:.0f}%", "results_holdout .turn_pass"),
        ("Lost-package scenario passing before / after", f"{n['lost'][0][1]}/{n['lost'][0][2]} / {n['lost'][1][1]}/{n['lost'][1][2]}", "per_scenario_pass.lost_package_ticket"),
        ("Reschedule-confirm scenario passing before / after (held-out)", f"{n['resched'][0][1]}/{n['resched'][0][2]} / {n['resched'][1][1]}/{n['resched'][1][2]}", "per_scenario_pass.reschedule_confirm_flow"),
        ("Junk 'None' values before / after", f"{b['junk']} / {a['junk']}", "results .junk_args"),
        ("Median time to first token before / after", f"{b['ttft']:.0f} / {a['ttft']:.0f} ms", "results .ttft_median"),
        ("Guard fired / retry time median", f"{a['guard_turns']} of {a['turns']} / {a['guard_ms']:.0f} ms", "results.qwen .guard_turns, .guard_retry_ms_median"),
        ("Handed off before read-back confirmed before / after", f"{b['early']:.0f}% / {a['early']:.0f}%", "results .early_handoff"),
        ("First word on tool turns, Qwen after / Claude", f"{a['ft_tool']:,.0f} / {c['ft_tool']:,.0f} ms", "results .first_word_tool_median"),
        ("'One moment' rule: dev tool accuracy before / after", f"{n['a3'][0]:.0f}% / {n['a3'][1]:.0f}%", "A2_omit_empty_args vs A3_filler_first, results_dev.qwen"),
        ("Worked examples: dev safety turns clean before / after", f"{n['a5_safe'][0][1]} / {n['a5_safe'][1][1]} of {n['a5_safe'][0][2]}", "A4 vs A5_few_shot, results_dev.qwen"),
        ("qwen3_xml parser: tool-call turns right", f"{n['xml'][0]} of {n['xml'][1]}", "D_parser_qwen3_xml/summary.json results.qwen.tool_acc"),
        ("Turns carrying 'None' that still handed off, before / after the code fix", f"{n['b1'][0][0]}/{n['b1'][0][1]} / {n['b1'][1][0]}/{n['b1'][1][1]}", "B0_baseline vs B1x_on_baseline_prompt turns.jsonl, arm qwen"),
        ("Tool accuracy 90% → 98% (no-unverified-status rule), dev", f"{n['a2_a4'][0]:.0f}% / {n['a2_a4'][1]:.0f}%", "A2 vs A4_no_unverified_status results_dev.qwen"),
    ]
    out = "# Where every number in the post and slides comes from\n\nFolder: `eval/results/qwen_fixes/`. Regenerate with `python eval/make_fix_images.py`.\n\n| Claim | Value | Source |\n|---|---|---|\n"
    return out + "".join(f"| {x} | {y} | `{z}` |\n" for x, y, z in rows)


def main() -> None:
    n = numbers()
    img = OUT / "images"
    img.mkdir(parents=True, exist_ok=True)
    slides = [("1_result", s1_result), ("2_worked", s2_worked), ("3_didnt", s3_didnt),
              ("4_heldout", s4_heldout), ("5_cost", s5_cost), ("6_takeaway", s6_takeaway)]
    for name, fn in slides:
        fn(n, img / f"{name}.png")
    from PIL import Image
    pages = [Image.open(img / f"{name}.png").convert("RGB") for name, _ in slides]
    pages[0].save(OUT / "carousel.pdf", save_all=True, append_images=pages[1:], resolution=100)
    alt = alt_texts(n)
    (OUT / "3_alt_text.md").write_text("# Alt text\n\nPost the slides in this order. Each is 1200×675; carousel.pdf is the same six as one document.\n\n"
                                       + "\n".join(f"## {k}.png\n\n{v}\n" for k, v in alt.items()))
    (OUT / "numbers.json").write_text(json.dumps(n, indent=2, default=str))
    (OUT / "4_numbers_and_sources.md").write_text(claims_table(n))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
