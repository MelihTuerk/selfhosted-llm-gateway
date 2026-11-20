# selfhosted-llm-gateway

Self-hosted LLM inference stack: llama.cpp behind an OpenAI-compatible gateway
with API-key auth, rate limiting and Prometheus/Grafana monitoring.

> **Status:** work in progress. So far only the llama.cpp server runs (CPU
> profile); the gateway and monitoring are not built yet.

## Quickstart (CPU)

```bash
cp .env.example .env
scripts/download-model.sh            # Qwen2.5-0.5B-Instruct Q4_K_M, ~490 MB
docker compose --profile cpu up -d
curl http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Hello!"}]}'
```
