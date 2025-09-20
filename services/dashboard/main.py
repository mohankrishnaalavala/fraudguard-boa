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

from collections import Counter
from statistics import median
import math

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
      body {{ font-family: Inter, Arial, sans-serif; background:#f8fafc; color:#111827; margin:0; display:grid; place-items:center; height:100vh; }}
      .card {{ background:#ffffff; padding:32px; border-radius:12px; width:320px; box-shadow:0 10px 30px rgba(0,0,0,.08); border:1px solid #e5e7eb; }}
      input {{ width:100%; padding:10px 12px; border-radius:8px; border:1px solid #d1d5db; background:#ffffff; color:#111827; }}
      label {{ font-size:12px; color:#374151; }}
      button {{ width:100%; padding:10px 12px; border:0; border-radius:8px; background:#2563eb; color:white; cursor:pointer; }}
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


@app.post("/notify")
async def notify_action(request: Request):
    if not _is_authed(request):
        return RedirectResponse("/login", status_code=302)
    try:
        payload = await request.json()
        body = {
            "transaction_id": payload.get("transaction_id"),
            "risk_score": float(payload.get("risk_score") or 0.0),
            "action": payload.get("action") or "notify",
            "explanation": payload.get("explanation") or ""
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{ACTION_ORCHESTRATOR_URL}/execute", json=body)
            if resp.status_code == 200:
                return resp.json()
            return {"success": False, "message": f"orchestrator returned {resp.status_code}"}
    except Exception as e:
        _log("notify_failed", error=str(e))
        return {"success": False, "message": "notify failed"}


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


async def _fetch_recent(limit: int = 200) -> list:
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


    def _badge(level: Optional[str]) -> str:
        l = (level or "").lower()
        if l == "high":
            return '<span class="badge badge-high">High</span>'
        if l == "medium":
            return '<span class="badge badge-med">Medium</span>'
        if l == "low":
            return '<span class="badge badge-low">Low</span>'
        return '<span class="badge">Pending</span>'

    # Helpers for formatting and analysis
    def _p_ts(s: str):
        try:
            if not s:
                return None
            s2 = s.replace("Z", "+00:00")
            return datetime.fromisoformat(s2)
        except Exception:
            return None

    def _fmt_date(dt: Optional[datetime]) -> str:
        if not dt:
            return ""
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")

    def _fmt_time(dt: Optional[datetime]) -> str:
        if not dt:
            return ""
        return dt.astimezone(timezone.utc).strftime("%H:%M")  # no seconds

    def _fmt_amt(x) -> str:
        try:
            val = float(x or 0)
            return f"${val:,.2f}"
        except Exception:
            return "$0.00"

    # Index history by (account_id, merchant)
    pair_index = {}
    for tx in transactions:
        key = (tx.get("account_id"), tx.get("merchant"))
        pair_index.setdefault(key, []).append(tx)

    def _ai_analysis(tx: dict) -> str:
        key = (tx.get("account_id"), tx.get("merchant"))
        hist = [h for h in pair_index.get(key, []) if h.get("transaction_id") != tx.get("transaction_id")]
        cur_dt = _p_ts(tx.get("timestamp"))
        cur_amt = float(tx.get("amount") or 0)
        rl = (tx.get("risk_level") or "").lower() or "pending"

        amounts = [float(h.get("amount") or 0) for h in hist if h.get("amount") is not None]
        hours = []
        recent_hist = []
        if cur_dt:
            for h in hist:
                ht = _p_ts(h.get("timestamp"))
                if ht:
                    hours.append(ht.hour)
                    # last 30 days window
                    if (cur_dt - ht).days <= 30 and (cur_dt - ht).days >= 0:
                        recent_hist.append(h)

        # Typical amount (median preferred)
        typical_amt = None
        if len(amounts) >= 3:
            try:
                typical_amt = float(median(amounts))
            except Exception:
                typical_amt = sum(amounts) / max(1, len(amounts))
        elif amounts:
            typical_amt = sum(amounts) / len(amounts)

        ratio_txt = ""
        if typical_amt and typical_amt > 0:
            ratio = cur_amt / typical_amt
            if ratio >= 1.2:
                ratio_txt = f"{ratio:.1f}x higher than typical {_fmt_amt(typical_amt)}"
            elif ratio <= 0.8:
                ratio_txt = f"{(typical_amt/cur_amt):.1f}x lower than typical {_fmt_amt(typical_amt)}" if cur_amt > 0 else "well below typical"

        # Frequency
        freq_txt = ""
        if recent_hist:
            freq_txt = f"{len(recent_hist)} in last 30d"

        # Time-of-day pattern
        tod_txt = ""
        if hours:
            from collections import Counter as _C
            mode_hour, mode_count = (0, 0)
            ctr = _C(hours)
            if ctr:
                mode_hour, mode_count = max(ctr.items(), key=lambda kv: kv[1])
            if cur_dt is not None and ctr and mode_count >= 3 and abs((cur_dt.hour - mode_hour)) >= 3:
                tod_txt = f"unusual hour (typical ~{mode_hour:02d}:00)"

        parts = []
        # Start with explicit level
        parts.append(f"{rl.title()} risk")
        parts.append(f"Amount {_fmt_amt(cur_amt)}")
        if ratio_txt:
            parts.append(ratio_txt)
        if freq_txt:
            parts.append(freq_txt)
        if tod_txt:
            parts.append(tod_txt)

        # Fallback/append explanation from backend if present
        bex = (tx.get("risk_explanation") or "").strip()
        if bex:
            parts.append(bex)

        return "; ".join(parts)

    # Build unified table rows (newest first) with required columns
    def _html_escape(s: str) -> str:
        s = s or ""
        return (s.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;")
                 .replace('"', "&quot;")
                 .replace("'", "&#x27;")
                 .replace("`", "&#96;"))

    sorted_tx = sorted(transactions, key=lambda t: t.get("timestamp", ""), reverse=True)
    rows = "".join(
        (
            (lambda dt: (
                (lambda analysis, esc_expl: (
                    f"<tr>"
                    f"<td>{_fmt_date(dt)}</td>"
                    f"<td>{_fmt_time(dt)}</td>"
                    f"<td>{_fmt_amt(t.get('amount',0))}</td>"
                    f"<td>{t.get('merchant','')}</td>"
                    f"<td>{_badge(t.get('risk_level'))}</td>"
                    f"<td>{analysis}</td>"
                    f"<td><button class='btn' onclick=\"notify('{t.get('transaction_id','')}',{float(t.get('risk_score') or 0):.2f},'{esc_expl}')\">Notify</button></td>"
                    f"</tr>"
                ))(_ai_analysis(t), _html_escape(t.get('risk_explanation') or _ai_analysis(t)))
            ))(_p_ts(t.get('timestamp','')))
        )
        for t in sorted_tx[:100]
    )

    def _card(title, items, color):
        rows = "".join(
            f"<div class='row'><div>{t.get('timestamp','')}</div><div>${t.get('amount',0)}</div><div>{t.get('merchant','')}</div></div>"
            for t in items[:10]
        )
        return f"""
        <div class="panel" style="border-color:{color}">
          <div class="panel-title">{title}</div>
          <div class="rows">{rows or '<div class="row">No items</div>'}</div>
        </div>
        """

    html = f"""
    <html><head><title>FraudGuard Dashboard</title>
    <meta http-equiv=\"refresh\" content=\"{REFRESH_INTERVAL_SECONDS}\">
    <style>
      body {{ font-family: Inter, Arial, sans-serif; background:#f8fafc; color:#111827; margin:0; }}
      header {{ padding:16px 24px; display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid #e5e7eb; background:#ffffff; position:sticky; top:0; }}
      .pill {{ padding:6px 10px; border-radius:999px; font-size:12px; }}
      .table {{ width:100%; border-collapse: collapse; margin:16px; }}
      .table th, .table td {{ padding:10px 12px; border-bottom:1px solid #e5e7eb; font-size:13px; }}
      .badge {{ padding:4px 8px; border-radius:999px; font-size:12px; }}
      .badge-high {{ background:#fee2e2; color:#b91c1c; }}
      .badge-med {{ background:#fff3cd; color:#92400e; }}
      .badge-low {{ background:#dcfce7; color:#166534; }}
      .btn {{ padding:6px 10px; border:1px solid #d1d5db; background:#ffffff; color:#111827; border-radius:8px; cursor:pointer; }}
      .btn:hover {{ background:#f3f4f6; }}

    </style></head>
    <body>
      <header>
        <div>FraudGuard</div>
        <div>
          <span class=\"pill\" style=\"background:#fee2e2;color:#b91c1c\">🔴 High Risk: {len(high)}</span>
          <span class=\"pill\" style=\"background:#fff3cd;color:#92400e\">⚠️ Medium Risk: {len(med)}</span>
          <span class=\"pill\" style=\"background:#dcfce7;color:#166534\">⚡ Low Risk: {len(low)}</span>
          <a href=\"/logout\" class=\"pill\" style=\"background:#e5e7eb;color:#374151;text-decoration:none;margin-left:8px;\">Logout</a>
        </div>
      </header>
      <table class=\"table\">
        <thead><tr><th>Date (UTC)</th><th>Time</th><th>Amount</th><th>Merchant/Account</th><th>Risk</th><th>AI Analysis</th><th>Action</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <script>
        async function notify(txId, riskScore, explanation) {{
          try {{
            const res = await fetch('/notify', {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify({{ transaction_id: txId, risk_score: riskScore, action: 'notify', explanation }})
            }});
            const data = await res.json();
            alert(data.message || 'Notification submitted');
          }} catch (e) {{
            alert('Notify failed');
          }}
        }}
      </script>

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

