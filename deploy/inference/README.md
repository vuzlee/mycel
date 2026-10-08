# Local inference (planned, off)

vLLM serving a small model for high-volume, short-output work. Off by default.

```bash
docker compose --profile local-llm up -d vllm
```

To use it, add it to `config/litellm/models.yaml` (see the commented `qwen3-4b` entry) and
set an agent's `model_spec` to `local:<model_name>`. Every model goes through the gateway,
so nothing else changes.

Dev machine limits (GTX 1660 Ti, 6 GB, Turing): `--dtype float16`, a 4-bit 3B model
(`Qwen/Qwen2.5-3B-Instruct-AWQ`), short context, few concurrent requests.
