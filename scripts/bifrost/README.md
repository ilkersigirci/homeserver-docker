# Bifrost vLLM Cost Estimation

Runpod bills vLLM pods by the hour. Bifrost tracks model cost by input and
output token price. Use this helper to convert an hourly pod price into rough
Bifrost pricing override values.

## Measure Tokens Per Hour

For representative requests, sum input tokens, output tokens, and elapsed
seconds:

```text
input_tokens_per_hour = total_input_tokens / total_seconds * 3600
output_tokens_per_hour = total_output_tokens / total_seconds * 3600
```

Use active request latency for model-throughput cost tracking. Use pod wall-clock
runtime only if you want to spread idle Runpod cost into token prices.

## Convert Hourly Price

```text
input_cost_per_token = hourly_usd / (input_tokens_per_hour + output_multiplier * output_tokens_per_hour)
output_cost_per_token = input_cost_per_token * output_multiplier
```

`output_multiplier` defaults to `2`, because generated tokens usually cost more
compute than prompt tokens.

## Helper

```bash
scripts/estimate-bifrost-vllm-pricing.sh \
  --hourly-usd 0.89 \
  --input-tokens-per-hour 1358516 \
  --output-tokens-per-hour 317147 \
  --output-multiplier 2
```

Example output:

```text
input_cost_per_token=0.000000446606
output_cost_per_token=0.000000893211
input_cost_per_1m_tokens=0.446606
output_cost_per_1m_tokens=0.893211
```

Re-estimate when the GPU, Runpod price, vLLM settings, quantization, batching, or
workload shape changes.
