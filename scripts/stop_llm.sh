#!/usr/bin/env bash
# Stop and remove the vLLM container (the model stays cached in ~/.cache/huggingface).
set -euo pipefail
NAME="${LLM_CONTAINER:-vllm-qwen36}"
docker rm -f "$NAME" && echo "Stopped and removed $NAME."
