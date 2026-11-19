# LinkedIn post: Claude vs self-hosted Qwen

Attach: `docs/comparison_chart.png` (1200×675). Every number below is from `eval/results/20261117-160950/`.

---

## The post

I swapped Claude for a model I host myself on a desk-sized NVIDIA DGX Spark, then measured what changed.

The app is a voice agent for late deliveries: three agents, 12 tools, and a verification gate written in code, so no tool can touch order data until the caller proves who they are. Same prompts, same tools, same scripted callers. Only the model changed.

Claude Sonnet 4.6 vs Qwen3.6-35B-A3B (4-bit, served with vLLM). 36 caller turns, 5 runs each.

Three things I learned:

1. Faster, with a catch.
Time to first token was 316 ms vs 845 ms. It isn't the network: the round trip to Anthropic is about 35 ms. But when a turn needs a tool, Claude says "One moment" first. Qwen goes silent, so the caller hears about a second of nothing. At the 90th percentile of what callers actually hear, the two are almost level (1,069 vs 1,213 ms).

2. Reliability is where it cost.
Right tool, right arguments: Claude 90/90, Qwen 77/90 (86%).
The failure I didn't expect: Qwen says "I'm opening your ticket now" and stops. No tool call, no ticket. It did this in 5 of 5 runs. I checked the model's token probabilities: it chose to end its turn, so it isn't a parser bug.
Sampling temperature mattered more than anything else. At the server's default (1.0), only 63% of tool calls were right.

3. The gate held. Honesty is a different problem.
Neither model leaked order details before verification. But Qwen sometimes made up an order status for an unverified caller ("out for delivery"). A gate in code can stop a tool call. It can't stop a model from saying something false.

Cost: $9.33 per 1,000 caller turns on Claude's API, against under $0.01 of electricity for Qwen. Hardware isn't included, so it isn't free.

Limits: 29 scenarios, text only (no speech), fake data, and prompts written for Claude and not tuned for Qwen. I tested Sonnet 4.6, the model the agent already used. Newer Claude models exist and I didn't test them.

My takeaway: self-host when a failed tool call is cheap to recover from, or when volume or privacy makes the API the problem. For an agent that takes real actions, I'm keeping Claude on those turns. Qwen could carry the plain conversation, behind a check that a tool actually ran before the agent says "done".

The scenarios, raw results and scoring code are in the repo: [link]

If you run tool-calling agents on self-hosted models, how do you handle "says it did it, didn't"?

#LLM #AIEngineering #VoiceAI #SelfHosting #vLLM

---

## Other opening lines (pick one, put it first)

- "My self-hosted LLM answered 2.7× faster than Claude, and I'm still not switching. Here's the data."
- "I tested a model that says 'I've opened your ticket' and doesn't open the ticket."
- "Faster, cheaper, and worse at doing what it says it did. A week of testing Qwen against Claude."

## First comment (post it right after)

How I measured it: same fake-data scenarios through the same agent graph for both models, arms interleaved so API latency drift hits both, time to first token measured identically from request sent to first streamed token. Claude ran at its default temperature because the current API version won't accept one. Qwen ran at 0.2 (and at 1.0, the 63% result). Full method and every scoring change I made after first looking at results are in docs/comparison_findings.md.

## Image alt text

Bar chart. Time to first token per model call. Claude Sonnet 4.6: median 845 ms, 90th percentile 1,279 ms. Qwen3.6-35B-A3B on a DGX Spark: median 316 ms, 90th percentile 682 ms. Tool calls right: Claude 100%, Qwen 86%. Cost per 1,000 turns: Claude $9.33 API, Qwen under $0.01 electricity, hardware excluded.

## Before you post

- Replace `[link]` with the repo link. The eval code, results and docs aren't committed yet, so commit and push them first. Check the repo is public.
- Read it once for your own voice. Cut anything you wouldn't say out loud.
- If someone asks "why Sonnet 4.6?": it's the model the agent already used. Don't claim the result holds for newer Claude models.
- Don't write "Qwen is X× cheaper". Hardware isn't priced here.
