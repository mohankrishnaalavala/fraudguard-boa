# MCP Gateway Service

Lightweight MCP-style and API facade for FraudGuard.

What’s new (hackathon enhancements):
- Default per-account history limit raised to 50 for analysis context
- New MCP-style endpoints for demo tooling:
  - GET /mcp/schema: advertises available tools
  - GET /mcp/transactions/{account_id}?limit=50: list recent transactions (max 50)
  - POST /mcp/analyze: forward a transaction to risk-scorer /analyze

Existing endpoints (unchanged):
- GET /accounts/{account_id}/transactions?limit=50: recent transactions for account
- GET /api/recent-transactions?limit=20: recent transactions across all accounts (dashboard)
- POST /api/transactions: create + store transaction
- GET /healthz: health check

Notes:
- All logs are JSON and avoid PII
- Rate-limiting and basic input clamping applied
- These MCP endpoints are a lightweight showcase, not a full MCP server implementation

