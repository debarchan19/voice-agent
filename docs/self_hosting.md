# Self-hosting the LLM (Qwen3.6-35B-A3B on a DGX Spark)

Runs `nvidia/Qwen3.6-35B-A3B-NVFP4` in Docker with vLLM's OpenAI-compatible API, so the voice
agent can use it instead of the Claude API. Claude stays the default and the fallback.

## Tested on

| | |
|---|---|
| Machine | DGX Spark, GB10, 121 GiB unified memory, aarch64, Ubuntu 24.04 |
| Driver / CUDA | 580.178.04 / 13.0 |
| Image | `vllm/vllm-openai:v0.28.0@sha256:61fc8a896b0a4fbbbdc063bc4b0dbc25ce98e02b5050c24aeb7830ac02039b14` (arm64, CUDA 13.0.2, vLLM 0.28.0) |
| Model | `nvidia/Qwen3.6-35B-A3B-NVFP4`, 23.5 GB, Apache-2.0, no Hugging Face login needed |
| Recipe | <https://recipes.vllm.ai/Qwen/Qwen3.6-35B-A3B> (DGX Spark GB10 profile, "verified") |

## Prerequisites

- Docker, and your user in the `docker` group (`sudo usermod -aG docker $USER`, then log in again).
- NVIDIA Container Toolkit with CDI: `nvidia-ctk cdi list` should show `nvidia.com/gpu=all`.
- About 33 GB of disk (9.7 GB image, 23.5 GB model). Pre-download the model if you like:
  `hf download nvidia/Qwen3.6-35B-A3B-NVFP4` (it lands in `~/.cache/huggingface`, which the
  container mounts).

## Start, check, stop

Port 8001 is used because the voice agent's token server runs on 8000.

```bash
scripts/start_llm.sh                      # tool parser qwen3_coder (default)
TOOL_PARSER=qwen3_xml scripts/start_llm.sh   # alternative tool parser
docker logs -f vllm-qwen36                # watch the load
python scripts/smoke_test_llm.py          # server, chat, streaming TTFT, tool call
scripts/stop_llm.sh                       # stop and remove the container
```

The server listens on `127.0.0.1:8001` only. Set `LLM_BIND=0.0.0.0` to expose it on the network
(there is no authentication, so do that only on a trusted network). `HF_TOKEN` is read from the
environment if set; nothing secret is stored in the scripts. The container restarts
automatically (`--restart unless-stopped`) until you run `stop_llm.sh`.

## Why each flag

| Flag | Reason |
|---|---|
| `--device nvidia.com/gpu=all` | GPU via CDI; no NVIDIA Docker runtime is registered on this box |
| `--ipc=host` | shared memory, as the recipe does |
| `-p 127.0.0.1:8001:8000` | localhost only |
| `--served-model-name qwen3.6-35b-a3b` | short stable name for clients |
| `--language-model-only` | skip the vision encoder (text-only agent) |
| `--kv-cache-dtype fp8`, `--attention-backend flashinfer`, `--moe-backend marlin` | the recipe's GB10 profile |
| `--gpu-memory-utilization 0.5` | recipe cap for unified memory (leaves room for the OS and other work) |
| `--max-model-len 32768` | recipe uses 262144; our prompts are ~3k tokens |
| `--max-num-seqs 8`, `--max-num-batched-tokens 8192`, `--enable-chunked-prefill`, `--async-scheduling` | recipe GB10 profile |
| `--enable-prefix-caching` | every turn resends the same long system prompt |
| `--load-format fastsafetensors` | faster weight loading |
| `--speculative-config {"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}` | the model's own multi-token-prediction head drafts 3 tokens per step |
| `--enable-auto-tool-choice --tool-call-parser qwen3_coder` | structured tool calls (see the parser note below) |
| `--reasoning-parser qwen3` | safety net: any thinking text goes to a separate field, never into the spoken `content` |
| `--default-chat-template-kwargs {"enable_thinking": false}` | thinking OFF: the chat template inserts an empty think block, so the first spoken token isn't delayed |

Dropped from the recipe on purpose: `--privileged` (not needed) and `--trust-remote-code`
(this checkpoint ships no custom code).

## Measured on this machine (first run)

| | |
|---|---|
| Time from `start_llm.sh` to ready | 190 s (weights 27.8 s; the rest is kernel autotuning, CUDA graphs and warm-up; image and model already local) |
| Model weights in memory | 21.15 GiB |
| KV cache | 13.4 GiB (628,934 tokens) |
| Memory budget used | 44.1 GiB of the 60.8 GiB allowed (weights + non-torch), plus 3.3 GiB peak activations |
| Time to first token, short prompt, warm | median 89 ms (5 runs) |
| Decode speed, short reply | median 108 tokens/s (single caller, MTP on) |

The time to first token is for a ~40-token prompt with a repeated prefix, so prefix caching helps.
The agent's real prompts are longer; see `eval/compare_llm.py` for realistic numbers.

## Troubleshooting

- **`permission denied` on the Docker socket:** add yourself to the `docker` group and log in again.
- **Out of memory or a CUDA graph / Mamba cache error:** lower `--max-cudagraph-capture-size`
  (vLLM PR #34571) or `--gpu-memory-utilization`.
- **Prefix caching on this architecture is "experimental" per the recipe.** If answers look
  inconsistent, remove `--enable-prefix-caching` and compare.
- **Change a flag:** edit `scripts/start_llm.sh` and run it again (it replaces the container).

## Findings from testing (2026-11-17)

- **Tool parser:** `qwen3_coder` (default) beat `qwen3_xml`. Five scripted reschedule calls each:
  `qwen3_coder` completed 3 of 5; `qwen3_xml` completed 0 of 5 and leaked tool-call text into speech.
- **Temperature:** the server default (1.0) completed 0 of 4 scripted calls; 0.2 completes about 3 of 5.
  The local backend now defaults to 0.2 (`LOCAL_LLM_TEMPERATURE`).
- **Latency:** with the agent's real prompt size (~1,200 tokens) the server's time to first token is
  about 300 ms (median), not the ~90 ms a tiny prompt gives. That is prefill time. The first request
  after a start was 1.7 s (GPU kernels compile on first use); `start_llm.sh` now warms the server up.
- **Prefix caching does nothing here:** vLLM sets the attention block size to 2144 tokens and our
  prompts are shorter than one block, so there were 0 cache hits. Turning it off changed nothing
  (`PREFIX_CACHE=0 scripts/start_llm.sh`), so the recipe default is kept.
- **Known failure modes of the model in this agent:** the greeter sometimes never hands off after the
  order number is confirmed, and sometimes answers an unverified caller with made-up order details
  instead of calling `verify_customer`.
