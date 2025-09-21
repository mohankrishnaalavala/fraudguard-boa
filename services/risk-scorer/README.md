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

- NEW_RECIPIENT_HIGH_AMOUNT_THRESHOLD: dollar amount above which a first-time recipient is escalated (default: 999)
- NEW_RECIPIENT_MIN_SCORE: minimum risk_score to enforce when rule triggers (default: 0.8)


Additional Vertex Vector Search (optional):
- USE_VERTEX_MATCHING: enable neighbor retrieval for context (default: true via values)
- ENABLE_VECTOR_UPSERTS: when true, each analyzed txn is embedded (allowed fields only) and upserted to the index
- VERTEX_EMBED_MODEL: text-embedding-004 (default)
- VERTEX_ME_INDEX_ENDPOINT: projects/.../indexEndpoints/ENDPOINT_ID (for neighbor queries)
- VERTEX_ME_INDEX_DEPLOYED_ID: deployed index ID (for neighbor queries)
- VERTEX_ME_INDEX: projects/.../indexes/INDEX_ID (required for upserts)
- RAG_HISTORY_LIMIT: number of recent txns to include in history summary (default: 50)

Logging (JSON, no PII):
- pattern_signals: known_recipient, amount_deviation_flag, off_hours, velocity_15m/60m, velocity_flag
- ai_invoke: model selection and RAG size (no sensitive fields)

Security & Compliance:
- No PII in logs
- GET /healthz present


