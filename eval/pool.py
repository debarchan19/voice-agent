"""Pool several result folders of the SAME configuration into one, for decisions inside the noise floor.

    python eval/pool.py OUT_DIR DIR1 DIR2 ...     # runs are renumbered 1..5, 6..10, ...; then summarized

Used by docs/qwen_fix_log.md (second amendment): a candidate that fails a clause by a margin within the spread seen
between identical configurations gets one replicate, and both sides are compared on 10 pooled runs.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_llm import summarize  # noqa: E402


def pool(out: Path, dirs: list[Path]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    configs = [json.loads((d / "config.json").read_text()) for d in dirs]
    config = dict(configs[0])
    config["runs"] = sum(c["runs"] for c in configs)
    config["pooled_from"] = [str(d) for d in dirs]
    config["git_commit"] = ",".join(c["git_commit"][:10] for c in configs)
    (out / "config.json").write_text(json.dumps(config, indent=2))
    offset = 0
    with open(out / "turns.jsonl", "w") as ft, open(out / "calls.jsonl", "w") as fc, open(out / "power.csv", "w") as fp:
        fp.write("unix_time,gpu_watts\n")
        for d, c in zip(dirs, configs):
            for name, f in (("turns.jsonl", ft), ("calls.jsonl", fc)):
                for line in open(d / name):
                    rec = json.loads(line)
                    rec["run"] += offset
                    f.write(json.dumps(rec) + "\n")
            if (d / "power.csv").exists():
                fp.writelines(list(open(d / "power.csv"))[1:])
            offset += c["runs"]
    summarize(out)


if __name__ == "__main__":
    pool(Path(sys.argv[1]), [Path(x) for x in sys.argv[2:]])
