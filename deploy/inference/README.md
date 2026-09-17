# Local inference

Run a small model on the machine itself to carry the high-volume work: classification,
entity extraction, relevance scoring, per-record summaries. Final synthesis still goes to the
cloud — a 3B model is not good enough to write a report.

## Why only one engine

vLLM and SGLang do the same job (serve an LLM over an OpenAI-compatible HTTP API). Running
both only costs VRAM and adds another thing to maintain. This project picks **vLLM**.

## Hardware constraints

Current dev machine: **GTX 1660 Ti 6GB** (Turing, sm_75).

| Constraint | Consequence |
|---|---|
| Turing has no bf16 | must run `--dtype float16` |
| No FP8, no FlashAttention-2 | default kernels, lower throughput than Ampere |
| 6GB VRAM | a 3B model must be 4-bit quantized (~2GB), leaving ~3.5GB for KV cache |

So context has to stay short and concurrent requests few. This is a real limit of the dev
machine, not a production configuration.

## Running it

```bash
docker compose --profile local-llm up -d vllm
```

Default model: `Qwen/Qwen2.5-3B-Instruct-AWQ` — 4-bit AWQ, fits in 6GB.

Without the profile enabled, every LLM call goes to the cloud. No code changes: both are
OpenAI-compatible endpoints, and `llm/router.py` decides which one to call.
