# selfhosted-llm-gateway

[![CI](https://github.com/MelihTuerk/selfhosted-llm-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/MelihTuerk/selfhosted-llm-gateway/actions/workflows/ci.yml)

Self-hosted LLM inference stack: llama.cpp behind an OpenAI-compatible gateway
with API-key auth, rate limiting and Prometheus/Grafana monitoring.

> **Status:** work in progress. The CPU profile runs end to end (llama.cpp,
> gateway, Prometheus, Grafana). The GPU profile, benchmarks and full
> documentation are not done yet.

## What runs today

- **Gateway** (FastAPI): proxies `/v1/models` and `/v1/chat/completions`
  (including streaming) to llama.cpp, works with the official `openai` SDK
- API-key auth (`Authorization: Bearer`) and a per-key rate limit (token bucket)
- Prometheus metrics on `/metrics`: requests, latency, time to first token,
  tokens/s, tokens per key (keys are hashed in labels)
- llama.cpp is only reachable on an internal Docker network; the gateway is
  the single entry point
- Grafana dashboard provisioned from the repo
- CI: lint, tests, image build and an end-to-end smoke test of the CPU stack

## Quickstart (CPU)

```bash
cp .env.example .env                 # then set GATEWAY_API_KEYS and GRAFANA_ADMIN_PASSWORD
scripts/download-model.sh            # Qwen2.5-0.5B-Instruct Q4_K_M, ~490 MB
docker compose --profile cpu up -d --build --wait

KEY=<one of the keys from GATEWAY_API_KEYS>
curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Hello!"}],"stream":true}'
```

- Grafana: http://127.0.0.1:3000 (user `admin`, password from `.env`)
- Prometheus: http://127.0.0.1:9090

All ports are bound to `127.0.0.1` only.

## License

MIT
