# Risk Scorer Service

Enhanced AI risk analysis with RAG and structured pattern signals.

What’s new (hackathon enhancements):
- Rich RAG summary: known recipients (count, typical amount, last_seen), common hours, weekday/weekend split, velocity windows (15m/60m)
- Derived pattern signals per transaction: new/known recipient, amount deviation flag, off-hours, weekend bias, velocity flags
- Prompt now includes Context + Signals for better AI grounding
- Structured JSON logs (no PII): pattern_signals, ai_invoke, ai_result_received
- Lightweight A2A endpoint for demo orchestration

HTTP endpoints:
- POST /analyze: Analyze a transaction and return { risk_score, rationale }
- POST /a2a/route: { target: "explain-agent"|"risk-scorer", message: {...} } → forwards to explain-agent/process
- GET /healthz: health check

Environment:
- EXPLAIN_AGENT_URL: base URL for explain-agent
- MCP_GATEWAY_URL: for history retrieval

Logging (JSON, no PII):
- pattern_signals: known_recipient, amount_deviation_flag, off_hours, velocity_15m/60m, velocity_flag
- ai_invoke: model selection and RAG size (no sensitive fields)

Security & Compliance:
- No PII in logs
- GET /healthz present


