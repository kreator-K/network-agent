# Signal Scoring Configuration

`signal_scoring_config` is immutable and versioned. Exactly one version is active. Historical scored signals retain the configuration version and canonical SHA-256 configuration hash used.

## Default 8c-v1

- Weights: topic relevance `0.23`, audience relevance `0.14`, credibility `0.18`, freshness `0.12`, originality `0.10`, personal angle `0.13`, semantic relevance `0.05`, audience interest `0.03`, humor suitability `0.02`.
- Thresholds: final score at least `55`, credibility at least `45`, factual risk at most `35`, generic-commentary risk at most `65`.
- Freshness: 14-day half-life, maximum age 5 days.
- Limits: 20 signals/run, 5 model-assisted signals/run, 5 opportunities/run, one retry.
- Model-assisted scoring: enabled, with deterministic fallback when validation or provider execution fails.

All component and risk scores are bounded to `0..100`; confidence is `0..1`. Core safety rules are not optional weights. Configuration changes require a future explicit human-approved workflow and must not change the personal-brand profile.
