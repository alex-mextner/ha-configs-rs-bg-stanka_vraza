# LLM Fallback Router — Design Document

## Problem
Current setup uses Ollama locally. Response generation is slow (~5-15s per interaction). Need a fast, reliable fallback chain of external LLM providers with priority by speed and cost.

## Provider Research

| Provider | Speed (typical) | Cost | Free Tier | Reliability | Notes |
|----------|----------------|------|-----------|-------------|-------|
| **Groq** | ~500-1000 TPS, <100ms TTFT | $0.05/$0.08 per 1M tok (Llama 3.1 8B) | 20 req/min | Excellent | LPU inference, fastest available |
| **Gemini (Google)** | ~200-500ms TTFT | $0.00 (free tier 60 RPM) | 60 req/min, 1M tok/day | Good | Quality high, rate limits |
| **HF Inference (Z.ai)** | Variable | $0.00 (HF free tier) | Limited | Medium | Auto-routes to fastest provider |
| **Ollama (local)** | ~2-10s TTFT (GPU) | $0.00 | Unlimited | Depends on load | Slow but private, zero cost |

## Priority Order (fastest first)
1. **Groq** — primary fast provider (Llama 3.1 8B Instant, 128k context)
2. **Gemini** — secondary, good quality, generous free tier
3. **HF Inference** — tertiary, auto-fallback via HuggingFace router
4. **Ollama** — local ultimate fallback

## Architecture

### Option A: Custom Python microservice (recommended)
Deploy `llm-router` as Docker service in compose stack. It exposes OpenAI-compatible `/v1/chat/completions` endpoint.

Home Generative Agent (or any HA integration) points to `llm-router` as Ollama/OpenAI endpoint.

```
HA Assist Pipeline → Home Generative Agent → llm-router
                                      ↓
                           ┌──────────┴──────────┐
                           ↓          ↓          ↓          ↓
                         Groq    Gemini API   HF Router   Ollama
```

### llm-router config (YAML)
```yaml
providers:
  - name: groq
    base_url: https://api.groq.com/openai/v1
    api_key: !secret groq_api_key
    model: llama-3.1-8b-instant
    timeout: 3.0
    priority: 1

  - name: gemini
    base_url: https://generativelanguage.googleapis.com/v1beta/openai
    api_key: !secret gemini_api_key
    model: gemini-1.5-flash-latest
    timeout: 5.0
    priority: 2

  - name: hf
    base_url: https://router.huggingface.co/v1
    api_key: !secret hf_api_key
    model: meta-llama/Meta-Llama-3-8B-Instruct:fastest
    timeout: 8.0
    priority: 3

  - name: ollama
    base_url: http://ollama:11434/v1
    api_key: ""
    model: llama3.1
    timeout: 30.0
    priority: 4
```

### Router logic
1. Try provider by priority.
2. If HTTP timeout or 5xx / 429 — mark provider degraded for 30s, retry next.
3. If all fail — return error to HA (which falls back to local TTS "service unavailable").
4. Expose metrics: `llm_router_latency_ms`, `llm_router_provider`, `llm_router_failures`.

## Secrets
All API keys live in `secrets.yaml`:
```yaml
groq_api_key: gsk_...
gemini_api_key: AIza...
hf_api_key: hf_...
```

## Cost Estimate (typical smart-home usage)
- ~100 interactions/day
- ~200 input + 300 output tokens each = 50k tokens/day
- Groq: 50k * $0.05/1M = **$0.0025/day** (~$0.08/month)
- Gemini free tier: $0 (within 1M tok/day)
- HF free tier: $0 (within limits)
- **Total expected cost: $0-1/month** (essentially free with free tiers)

## Implementation Steps
1. Create `llm-router` Python FastAPI service (OpenAI-compatible proxy)
2. Add to `ha.docker-compose.yaml`
3. Configure Home Generative Agent to use `llm-router` endpoint
4. Add router health sensor to `voice_assist_monitor.yaml`
5. Expose Grafana/Prometheus metrics (optional future)

## Files to create
- `scripts/llm_router/main.py` — FastAPI router
- `scripts/llm_router/config.yaml` — provider chain
- Update `ha.docker-compose.yaml` — add llm-router service
- Update `secrets.yaml` — add API key placeholders
- Update `voice_assist_monitor.yaml` — add router health sensor
