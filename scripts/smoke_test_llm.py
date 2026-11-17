"""Smoke test for the self-hosted vLLM server (OpenAI-compatible API). Standard library only.

Checks: the server responds, a plain chat completion works, streaming works (prints time to first
token and tokens per second), and a tool-calling request returns a valid structured tool call.
Thinking is expected to be OFF, so it also flags any reasoning text.

Usage: python scripts/smoke_test_llm.py [--base-url http://127.0.0.1:8001/v1] [--runs 5]
"""

import argparse
import json
import statistics
import sys
import time
import urllib.request

MODEL = "qwen3.6-35b-a3b"
SYSTEM = "You are a phone support agent. Reply in one or two short spoken sentences."

TOOL = {
    "type": "function",
    "function": {
        "name": "verify_customer",
        "description": "Verify the caller using the last four digits of the phone number on the order.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order number, e.g. ORD-48213."},
                "last_four_phone_digits": {"type": "string", "description": "The four digits the caller said."},
            },
            "required": ["order_id", "last_four_phone_digits"],
        },
    },
}


def post(base: str, body: dict, stream: bool = False):
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps({"model": MODEL, **body}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"},
    )
    return urllib.request.urlopen(req, timeout=120)


def chat(base: str, body: dict) -> dict:
    with post(base, body) as r:
        return json.load(r)


def stream_once(base: str, messages: list, max_tokens: int = 120) -> dict:
    """One streamed completion. Returns time to first content token, total time and tokens/second."""
    t0 = time.perf_counter()
    first = None
    chunks, usage, reasoning = 0, None, False
    with post(base, {"messages": messages, "max_tokens": max_tokens, "stream": True,
                     "stream_options": {"include_usage": True}}) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            ev = json.loads(line[5:])
            if ev.get("usage"):
                usage = ev["usage"]
            for ch in ev.get("choices", []):
                d = ch.get("delta", {})
                if d.get("reasoning_content") or d.get("reasoning"):
                    reasoning = True
                if d.get("content"):
                    chunks += 1
                    if first is None:
                        first = time.perf_counter() - t0
    total = time.perf_counter() - t0
    tokens = (usage or {}).get("completion_tokens", chunks)
    decode = total - (first or 0)
    return {"ttft": first, "total": total, "tokens": tokens,
            "tps": tokens / decode if decode > 0 and tokens > 1 else None, "reasoning": reasoning}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8001/v1")
    ap.add_argument("--runs", type=int, default=5)
    base = ap.parse_args().base_url.rstrip("/")
    runs = ap.parse_args().runs
    failed = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
        if not ok:
            failed.append(name)

    # 1. server responds
    try:
        with urllib.request.urlopen(f"{base}/models", timeout=10) as r:
            models = [m["id"] for m in json.load(r)["data"]]
        check("server responds", MODEL in models, f"models={models}")
    except Exception as e:  # noqa: BLE001
        check("server responds", False, repr(e))
        return 1

    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Hi, my package hasn't arrived yet. Can you help?"}]

    # 2. plain chat completion
    t0 = time.perf_counter()
    out = chat(base, {"messages": msgs, "max_tokens": 120})
    msg = out["choices"][0]["message"]
    check("plain chat completion", bool(msg.get("content")), f"{time.perf_counter() - t0:.2f}s -> {msg.get('content')!r}")
    check("no hidden reasoning (thinking off)", not (msg.get("reasoning_content") or msg.get("reasoning")))

    # 3. streaming: first run is a warm-up and is reported separately
    results = [stream_once(base, msgs) for _ in range(runs + 1)]
    cold, warm = results[0], results[1:]
    check("streaming works", all(r["ttft"] is not None for r in results))
    check("streaming has no reasoning tokens", not any(r["reasoning"] for r in results))
    ttfts = [r["ttft"] * 1000 for r in warm if r["ttft"] is not None]
    tps = [r["tps"] for r in warm if r["tps"]]
    print(f"       first request (cold): TTFT {cold['ttft'] * 1000:.0f} ms")
    if ttfts:
        print(f"       warm TTFT over {len(ttfts)} runs: median {statistics.median(ttfts):.0f} ms, "
              f"min {min(ttfts):.0f} ms, max {max(ttfts):.0f} ms")
    if tps:
        print(f"       decode speed: median {statistics.median(tps):.1f} tokens/s "
              f"({statistics.median(r['tokens'] for r in warm):.0f} tokens per reply)")

    # 4. tool call
    tool_msgs = [
        {"role": "system", "content": "You are a phone support agent. Use tools when needed."},
        {"role": "user", "content": "My order is O R D 4 8 2 1 3 and the last four digits of my phone are 0 1 7 7."},
    ]
    out = chat(base, {"messages": tool_msgs, "tools": [TOOL], "tool_choice": "auto", "max_tokens": 200})
    m = out["choices"][0]["message"]
    calls = m.get("tool_calls") or []
    ok, detail = False, f"no tool call; content={m.get('content')!r}"
    if calls:
        fn = calls[0]["function"]
        try:
            args = json.loads(fn["arguments"])
            ok = (fn["name"] == "verify_customer"
                  and "48213" in args.get("order_id", "").replace("-", "").replace(" ", "")
                  and args.get("last_four_phone_digits", "").replace(" ", "") == "0177")
            detail = f"{fn['name']}({args})"
        except json.JSONDecodeError:
            detail = f"invalid JSON arguments: {fn['arguments']!r}"
    check("tool call returns valid structured call", ok, detail)

    print("\nAll checks passed." if not failed else f"\nFAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
