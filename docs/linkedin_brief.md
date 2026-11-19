# Brief for Claude Desktop: write a LinkedIn post about this comparison

**Attach these files when you start the chat:**
1. `docs/comparison_chart.png`: the one chart for the post
2. `docs/comparison_findings.md`: findings, limits, recommendation
3. `docs/comparison_examples.md`: three side-by-side transcripts
4. `eval/results/20261117-160950/summary.md`: the full results table
5. `docs/linkedin_post.md`: a first draft, to improve on or discard

**Then paste everything below the line.**

---

Write a LinkedIn post from the attached files. I'm an engineer who ran a real test and wants to share what I found, honestly.

**Audience:** developers and technical leads who build with LLMs, and some who decide between an API and self-hosting. They are sceptical of hype.

**What happened:** I built a voice agent for late deliveries (3 agents, 12 tools, a verification gate written in code). I swapped its language model from Claude Sonnet 4.6 (API) to Qwen3.6-35B-A3B (4-bit, vLLM, on an NVIDIA DGX Spark I own) and compared them on 29 scripted scenarios, 36 caller turns, 5 runs each. Prompts, tools and the gate were unchanged.

**Facts you may use** (all from the attached files; don't add numbers):
- Time to first token per model call, median / 90th percentile: Claude 845 / 1,279 ms; Qwen 316 / 682 ms.
- Not the network: the round trip to Anthropic from my machine is about 35 ms with TLS.
- What the caller hears: on plain turns Qwen's first word is at about 290 ms vs Claude's 844 ms. On tool turns Qwen is slower (985 vs 835 ms), because Claude says "One moment" before a tool call and Qwen usually calls the tool silently. At the 90th percentile of the first spoken word, they are nearly level (1,069 vs 1,213 ms).
- Tool-call accuracy (right tool, right arguments): Claude 90/90, Qwen 77/90 (86%). At Qwen's default temperature of 1.0: 63%.
- Failure: Qwen said "I'm opening a lost package ticket now" and made no tool call, 5 of 5 runs. Token probabilities show it chose to end its turn; it was not a parser bug.
- Another failure: Qwen sent the string "None" for an unused argument, and the tool rejected it.
- Safety: neither model leaked order details before verification. Qwen invented an order status for an unverified caller (1 time at temperature 0.2, 4 at 1.0). The code gate can stop tool calls, not false statements.
- Cost per 1,000 caller turns: Claude $9.33 (API, price checked 2026-11-17). Qwen: under $0.01 electricity, assuming $0.15/kWh. Hardware is NOT included.

**Must be said in the post, briefly:** 29 scenarios; text only (no speech recognition or synthesis); fake data; prompts written for Claude and not tuned for Qwen; Claude Sonnet 4.6 was tested because the agent already used it, and newer Claude models were not tested.

**Do not:**
- Say Qwen is "N× cheaper" or "free". Hardware isn't priced.
- Say the result applies to other models, other prompts, or real phone calls.
- Claim a difference where the data shows noise. Qwen at temperature 0.2 vs 1.0 had the same speed (316 vs 308 ms).
- Use hype words ("game-changer", "revolutionary", "blazing").
- Add a number, a claim or a name that isn't in the attached files.

**My conclusion, in my words:** self-host when a failed tool call is cheap to recover from, or when volume or privacy makes the API the problem. For an agent that takes real actions, keep Claude on those turns. Qwen could carry plain conversation behind a check that a tool actually ran before the agent says "done".

**Format:**
- Plain text, about 1,800–2,300 characters, short paragraphs. Hard limit 3,000.
- First line must work as a hook before "see more": the single most interesting result, stated plainly.
- Numbered findings are fine. At most 3 emoji or none. 4–5 hashtags at the end.
- End with one real question to engineers.
- Leave `[link]` where the repo link goes.
- First person, practitioner voice. Plain sentences.

**Also give me:** 3 alternative first lines, a first comment explaining the method, and alt text for the chart. Then tell me any claim in the post that a reader could reasonably challenge.
