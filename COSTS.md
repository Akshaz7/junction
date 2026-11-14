# COSTS

Caps for run 1. The lead may not raise them; only Ash can.

**Ash, 14 Nov ~04:00: up to $500 total may be spent tonight on testing ("don't be shy").** Runware cap 500 USD covers it; per-provider caps below still apply to the other providers. The model layer enforces them (raises `BudgetExceeded`).

| Provider | Cap |
|---|---|
| Runware | 500 USD |
| Anthropic | 15 USD |
| Gemini | 20 USD |
| Modal | 80 USD (GPU; each fine-tune row capped at 2 GPU-hours) |
| ElevenLabs | 5 USD |
| Context.dev | 10,000 credits |
| NVIDIA (build.nvidia.com) | free tier, with backoff |

## Hourly spend (from `results/costs.jsonl`)
| Time | Runware | Anthropic | Gemini | Modal | ElevenLabs | Context.dev | NVIDIA calls | Total USD |
|---|---|---|---|---|---|---|---|---|
| 03:45 | 0.017 | 0 | 0 | 0 | 0.010 | 0 | ~120 | 0.027 |
