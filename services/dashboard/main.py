#!/usr/bin/env python3
"""
FraudGuard Dashboard Service with simple login and protected UI.
- Healthz endpoint
- Login form with default admin/admin (overridable via env)
- Session cookie auth (unsigned, demo-only). No PII in logs.
- Renders dashboard pulling data from MCP Gateway; grid layout optimized.
"""
import os
import json
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Form, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

APP_PORT = int(os.getenv("PORT", "8080"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "info")
EXPLAIN_AGENT_URL = os.getenv("EXPLAIN_AGENT_URL", "http://explain-agent.fraudguard.svc.cluster.local:8080")
ACTION_ORCHESTRATOR_URL = os.getenv("ACTION_ORCHESTRATOR_URL", "http://action-orchestrator.fraudguard.svc.cluster.local:8080")
MCP_GATEWAY_URL = os.getenv("MCP_GATEWAY_URL", "http://mcp-gateway.fraudguard.svc.cluster.local:8080")
REFRESH_INTERVAL_SECONDS = int(os.getenv("REFRESH_INTERVAL_SECONDS", "10"))
DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "admin")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin")
SESSION_COOKIE = "fgdash_session"

app = FastAPI(title="FraudGuard Dashboard", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _log(event: str, **fields):
    payload = {"event": event, "timestamp": datetime.now(timezone.utc).isoformat(), **fields}
    print(json.dumps(payload))


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "dashboard", "timestamp": datetime.now(timezone.utc).isoformat()}


def _is_authed(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    return token == "ok"


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _is_authed(request):
        return RedirectResponse("/", status_code=302)
    html = f"""
    <html><head><title>FraudGuard Login</title>
    <style>
      body {{ font-family: Inter, Arial, sans-serif; background:#0b1320; color:#e6edf3; margin:0; display:grid; place-items:center; height:100vh; }}
      .card {{ background:#111a2b; padding:32px; border-radius:12px; width:320px; box-shadow:0 10px 30px rgba(0,0,0,.4); }}
      input {{ width:100%; padding:10px 12px; border-radius:8px; border:1px solid #2b3a55; background:#0b1320; color:#e6edf3; }}
      label {{ font-size:12px; color:#90a4c9; }}
      button {{ width:100%; padding:10px 12px; border:0; border-radius:8px; background:#3b82f6; color:white; cursor:pointer; }}
    </style></head>
    <body>
      <div class="card">
        <h2>FraudGuard</h2>
        <form method="post" action="/login">
          <label>Username</label>
          <input name="username" autocomplete="username" />
          <div style="height:8px"></div>
          <label>Password</label>
          <input type="password" name="password" autocomplete="current-password" />
          <div style="height:16px"></div>
          <button>Login</button>
        </form>
      </div>
    </body></html>
    """
    return HTMLResponse(html)


@app.post("/login")
async def do_login(username: str = Form(...), password: str = Form(...)):
    if username == DASHBOARD_USERNAME and password == DASHBOARD_PASSWORD:
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie(SESSION_COOKIE, "ok", httponly=True, samesite="Lax")
        _log("login_success")
        return resp
    _log("login_failed")
    return RedirectResponse("/login", status_code=302)


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


async def _fetch_recent(limit: int = 30) -> list:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{MCP_GATEWAY_URL}/api/recent-transactions", params={"limit": limit})
            if r.status_code == 200:
                return (r.json() or {}).get("transactions", [])
    except Exception as e:
        _log("fetch_recent_failed", error=str(e))
    return []


def _render_dashboard(transactions: list) -> str:
    # Group by risk level
    high = [t for t in transactions if (t.get("risk_level") or "").lower() == "high"]
    med = [t for t in transactions if (t.get("risk_level") or "").lower() == "medium"]
    low = [t for t in transactions if (t.get("risk_level") or "").lower() == "low"]

    def _card(title, items, color):
        rows = "".join(
            f"<div class='row'><div>{t.get('timestamp','')}</div><div>${t.get('amount',0)}</div><div>{t.get('merchant','')}</div></div>"
            for t in items[:10]
        )
        return f"""
        <div class="panel" style="border-color:{color}">
          <div class="panel-title">{title}</div>
          <div class="rows">{rows or '<div class=\"row\">No items</div>'}</div>
        </div>
        """

    html = f"""
    <html><head><title>FraudGuard Dashboard</title>
    <meta http-equiv="refresh" content="{REFRESH_INTERVAL_SECONDS}">
    <style>
      body {{ font-family: Inter, Arial, sans-serif; background:#0b1320; color:#e6edf3; margin:0; }}
      header {{ padding:16px 24px; display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid #1d2a44; }}
      .grid {{ display:grid; grid-template-columns: 1fr 1fr 1fr; gap:16px; padding:16px; }}
      /* Low risk panel gets flexible width on large screens to utilize space */
      @media (min-width: 1400px) {{ .grid {{ grid-template-columns: 1fr 1fr 1.5fr; }} }}
      .panel {{ border:1px solid #24324d; border-radius:10px; padding:12px; background:#0f1a2c; }}
      .panel-title {{ font-weight:600; margin-bottom:8px; opacity:.9; }}
      .rows {{ display:flex; flex-direction:column; gap:6px; }}
      .row {{ display:grid; grid-template-columns: 1.4fr .6fr 1fr; gap:8px; font-size:13px; opacity:.9; }}
      .pill {{ padding:6px 10px; border-radius:999px; font-size:12px; }}
    </style></head>
    <body>
      <header>
        <div>FraudGuard</div>
        <div>
          <span class="pill" style="background:#3a1a1c;color:#ff6b6b">🔴 High Risk: {len(high)}</span>
          <span class="pill" style="background:#3a2f1a;color:#ffd166">⚠️ Medium Risk: {len(med)}</span>
          <span class="pill" style="background:#1f2f1a;color:#95d47b">⚡ Low Risk: {len(low)}</span>
          <a href="/logout" class="pill" style="background:#1d2a44;color:#c7d2fe;text-decoration:none;margin-left:8px;">Logout</a>
        </div>
      </header>
      <div class="grid">
        {_card('🔴 High Risk', high, '#ff6b6b')}
        {_card('⚠️ Medium Risk', med, '#ffd166')}
        {_card('⚡ Low Risk', low, '#95d47b')}
      </div>
    </body>
    </html>
    """
    return html


@app.get("/")
async def root(request: Request):
    if not _is_authed(request):
        return RedirectResponse("/login", status_code=302)
    tx = await _fetch_recent(limit=60)
    return HTMLResponse(_render_dashboard(tx))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT)

