#!/usr/bin/env bash
# Start the self-hosted Qwen3.6-35B-A3B (NVFP4) vLLM server. See docs/self_hosting.md.
# Usage: scripts/start_llm.sh            (default tool parser qwen3_coder)
#        TOOL_PARSER=qwen3_xml scripts/start_llm.sh
# No secrets here: HF_TOKEN is passed through from the environment only if it is set.
set -euo pipefail

NAME="${LLM_CONTAINER:-vllm-qwen36}"
PORT="${LLM_PORT:-8001}"
BIND="${LLM_BIND:-127.0.0.1}"          # localhost only; set LLM_BIND=0.0.0.0 to expose on the network
TOOL_PARSER="${TOOL_PARSER:-qwen3_coder}"
PREFIX_CACHE="${PREFIX_CACHE:-1}"      # PREFIX_CACHE=0 turns prefix caching off
IMAGE="vllm/vllm-openai:v0.28.0@sha256:61fc8a896b0a4fbbbdc063bc4b0dbc25ce98e02b5050c24aeb7830ac02039b14"
MODEL="nvidia/Qwen3.6-35B-A3B-NVFP4"

docker rm -f "$NAME" >/dev/null 2>&1 || true

docker run -d --name "$NAME" --restart unless-stopped \
  --device nvidia.com/gpu=all --ipc=host \
  -p "$BIND:$PORT:8000" \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  ${HF_TOKEN:+-e HF_TOKEN} \
  -e VLLM_USE_RUST_FRONTEND=1 \
  "$IMAGE" \
  "$MODEL" \
  --served-model-name qwen3.6-35b-a3b \
  --language-model-only \
  --kv-cache-dtype fp8 --attention-backend flashinfer --moe-backend marlin \
  --gpu-memory-utilization 0.5 --max-model-len 32768 \
  --max-num-seqs 8 --max-num-batched-tokens 8192 \
  --enable-chunked-prefill --async-scheduling \
  $([ "$PREFIX_CACHE" = 1 ] && echo --enable-prefix-caching || echo --no-enable-prefix-caching) \
  --load-format fastsafetensors \
  --speculative-config '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}' \
  --enable-auto-tool-choice --tool-call-parser "$TOOL_PARSER" \
  --reasoning-parser qwen3 \
  --default-chat-template-kwargs '{"enable_thinking": false}'

echo "Started $NAME on http://$BIND:$PORT/v1 (tool parser: $TOOL_PARSER)."
[ "${WAIT:-1}" = 1 ] || { echo "Not waiting. Follow the load: docker logs -f $NAME"; exit 0; }

# Wait until the server is ready, then warm it up. The first requests after a start trigger GPU
# kernel compilation (about 1.5 s each); doing it here keeps that off the first real call.
URL="http://$BIND:$PORT/v1"
echo -n "Waiting for the model to load (about 3 minutes)"
for _ in $(seq 1 120); do
  curl -sf "$URL/models" >/dev/null && break
  [ "$(docker inspect -f '{{.State.Status}}' "$NAME")" = running ] || { echo; echo "Container stopped: docker logs $NAME"; exit 1; }
  echo -n "."; sleep 5
done
echo " ready."
FILLER=$(printf 'You are a phone support agent for an online shop and you help callers with late deliveries. %.0s' $(seq 1 14))
for q in "Hi" "My order number is ORD-48213 and the last four digits are 0142." "Where is my package?"; do
  curl -sf "$URL/chat/completions" -H 'Content-Type: application/json' -d "$(cat <<JSON
{"model":"qwen3.6-35b-a3b","max_tokens":40,"temperature":0.2,
 "messages":[{"role":"system","content":"$FILLER"},{"role":"user","content":"$q"}],
 "tools":[{"type":"function","function":{"name":"verify_customer","description":"Verify the caller.",
   "parameters":{"type":"object","properties":{"order_id":{"type":"string"},"last_four_phone_digits":{"type":"string"}},
   "required":["order_id","last_four_phone_digits"]}}}]}
JSON
)" >/dev/null && echo -n "warm-up ok; " || echo -n "warm-up request failed; "
done
echo "done. The model is ready for calls."
