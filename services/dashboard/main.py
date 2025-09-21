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
    <html><head><title>FraudGuard for Bank of Anthos - Login</title>
    <style>
      body {{ font-family: Inter, Arial, sans-serif; background:linear-gradient(135deg,#eef2ff,#fef3c7); color:#111827; margin:0; }}
      .wrapper {{ display:grid; place-items:center; min-height:100vh; padding:24px; }}
      .card {{ background:#ffffff; padding:32px; border-radius:14px; width:360px; box-shadow:0 20px 40px rgba(2,6,23,.10); border:1px solid #e5e7eb; }}
      h2 {{ margin:0 0 6px 0; font-size:20px; }}
      .muted {{ color:#6b7280; font-size:12px; margin-bottom:16px; }}
      input {{ width:100%; padding:12px 14px; border-radius:10px; border:1px solid #d1d5db; background:#ffffff; color:#111827; }}
      input:focus {{ outline:none; border-color:#6366f1; box-shadow:0 0 0 3px rgba(99,102,241,.15); }}
      label {{ font-size:12px; color:#374151; display:block; margin-bottom:6px; }}
      button {{ width:100%; padding:12px 14px; border:0; border-radius:10px; background:linear-gradient(135deg,#0ea5e9,#6366f1); color:white; cursor:pointer; font-weight:600; box-shadow:0 10px 18px rgba(99,102,241,.25); }}
      button:hover {{ filter:brightness(1.03); }}
    </style></head>
    <body>
      <div class="wrapper">
        <div class="card">
          <h2>FraudGuard for Bank of Anthos</h2>
          <div class="muted">Sign in to continue</div>
          <form method="post" action="/login">
            <label>Username</label>
            <input name="username" autocomplete="username" />
            <div style="height:10px"></div>
            <label>Password</label>
            <input type="password" name="password" autocomplete="current-password" />
            <div style="height:16px"></div>
            <button>Login</button>
          </form>
        </div>
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

@app.post("/api/manual-sync")
async def dash_manual_sync(request: Request):
    if not _is_authed(request):
        return RedirectResponse("/login", status_code=302)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{MCP_GATEWAY_URL}/api/manual-sync")
            return PlainTextResponse(await resp.aread(), status_code=resp.status_code, media_type="application/json")
    except Exception as e:
        _log("manual_sync_proxy_failed", error=str(e))
        return PlainTextResponse('{"error":"manual sync failed"}', status_code=502, media_type="application/json")



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

    def _parse_dt_fallback(tx: dict) -> Optional[datetime]:
        # Prefer transaction timestamp; fallback to created_at if missing
        ts = tx.get("timestamp")
        dt = _p_ts(ts) if ts else None
        if dt:
            return dt
        ca = tx.get("created_at")
        return _p_ts(ca) if ca else None

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

    # Sort by true datetime (timestamp), with created_at as a fallback
    sorted_tx = sorted(transactions, key=lambda t: (_parse_dt_fallback(t) or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    rows = "".join(
        (
            (lambda dt: (
                (lambda analysis, esc_expl: (
                    f"<tr data-risk='{(t.get('risk_level') or '').lower()}' data-ts='{int((_p_ts(t.get('timestamp','')) or dt).timestamp())}' data-amt='{float(t.get('amount',0) or 0):.2f}'>"
                    f"<td class='col-date'>{_fmt_date(dt)}</td>"
                    f"<td class='col-time'>{_fmt_time(dt)}</td>"
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
    <html><head><title>FraudGuard for Bank of Anthos</title>
    <meta http-equiv=\"refresh\" content=\"{REFRESH_INTERVAL_SECONDS}\">
    <style>
      :root {{ --muted:#6b7280; --surface:#ffffff; --line:#e5e7eb; --bg:#f8fafc; }}
      * {{ box-sizing: border-box; }}
      body {{ font-family: Inter, Arial, sans-serif; background:var(--bg); color:#111827; margin:0; font-size:16px; }}
      a {{ color:inherit; }}
      .container {{ max-width: 1200px; margin: 0 auto; padding: 0 24px; }}

      header {{ position:sticky; top:0; z-index:10; background:linear-gradient(135deg,#0ea5e9,#6366f1); color:#ffffff; box-shadow:0 2px 8px rgba(0,0,0,.1); }}
      .header-inner {{ display:flex; align-items:center; justify-content:space-between; padding:16px 0; }}
      .brand {{ font-weight:700; font-size:18px; letter-spacing:.3px; }}
      .pill {{ padding:6px 10px; border-radius:999px; font-size:12px; margin-left:6px; display:inline-block; }}

      .stats {{ display:grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap:16px; margin:20px 0; }}
      .stat-card {{ background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:16px; display:flex; align-items:center; gap:12px; box-shadow:0 6px 18px rgba(0,0,0,.04); }}
      .stat-icon {{ width:36px; height:36px; display:grid; place-items:center; border-radius:10px; font-size:18px; }}
      .stat-high .stat-icon {{ background:#fee2e2; color:#b91c1c; }}
      .stat-med .stat-icon {{ background:#fef3c7; color:#92400e; }}
      .stat-low .stat-icon {{ background:#dcfce7; color:#166534; }}
      .stat-value {{ font-size:22px; font-weight:700; }}
      .stat-label {{ color:var(--muted); font-size:12px; }}

      .table-wrapper {{ background:var(--surface); border:1px solid var(--line); border-radius:12px; margin:20px 0; overflow:auto; box-shadow:0 10px 24px rgba(0,0,0,.05); }}
      .table {{ width:100%; border-collapse:separate; border-spacing:0; }}
      .table th, .table td {{ padding:12px 14px; font-size:14px; }}
      .table thead th {{ position:sticky; top:0; background:#f9fafb; border-bottom:1px solid var(--line); text-align:left; font-weight:600; }}
      .table tbody tr:nth-child(even) {{ background:#fcfdff; }}
      .table tbody tr:hover {{ background:#f5f7ff; }}

      .badge {{ padding:4px 8px; border-radius:999px; font-size:12px; font-weight:600; }}
      .badge-high {{ background:#fee2e2; color:#b91c1c; }}
      .badge-med {{ background:#fef3c7; color:#92400e; }}
      .badge-low {{ background:#dcfce7; color:#166534; }}

      .btn {{ padding:8px 12px; border:1px solid #d1d5db; background:#ffffff; color:#111827; border-radius:8px; cursor:pointer; }}
      .btn:hover {{ background:#f3f4f6; }}
      .btn-outline {{ padding:8px 12px; border:1px solid rgba(255,255,255,.7); background:transparent; color:#ffffff; border-radius:8px; cursor:pointer; }}
      .btn-outline:hover {{ background:rgba(255,255,255,.12); }}

      /* Controls & chips */
      .controls {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin:16px 0; }}
      .chip {{ padding:6px 10px; border-radius:999px; border:1px solid var(--line); background:var(--surface); cursor:pointer; font-size:12px; }}
      .chip.active {{ background:#e0e7ff; border-color:#c7d2fe; }}
      .date-group .custom-range input {{ padding:6px 8px; border:1px solid var(--line); border-radius:8px; background:var(--surface); color:inherit; }}
      .toggle-label {{ font-size:12px; color:var(--muted); }}

      /* Table columns */
      .col-date {{ white-space:nowrap; min-width:110px; }}
      .col-time {{ white-space:nowrap; min-width:72px; }}
      th.sortable {{ cursor:pointer; user-select:none; }}

      /* Dark mode */
      body.dark {{ --bg:#0b1220; --surface:#0f172a; --line:#1f2a44; color:#e5e7eb; }}
      body.dark .table thead th {{ background:#0f1b2e; border-bottom:1px solid var(--line); }}
      body.dark .table tbody tr:nth-child(even) {{ background:#0e1626; }}
      body.dark .table tbody tr:hover {{ background:#12203a; }}

    </style></head>
    <body>
      <header>
        <div class=\"header-inner container\">
          <div class=\"brand\">FraudGuard for Bank of Anthos</div>
          <div>
            <span class=\"pill\" style=\"background:#fee2e2;color:#b91c1c\">🔴 High Risk: {len(high)}</span>
            <span class=\"pill\" style=\"background:#fef3c7;color:#92400e\">⚠️ Medium Risk: {len(med)}</span>
            <span class=\"pill\" style=\"background:#dcfce7;color:#166534\">⚡ Low Risk: {len(low)}</span>
            <a href=\"/logout\" class=\"btn-outline\" style=\"margin-left:8px;text-decoration:none;\">Logout</a>
          </div>
        </div>
      </header>
      <main class=\"container\">
        <section class=\"stats\">
          <div class=\"stat-card stat-high\">
            <div class=\"stat-icon\">🔴</div>
            <div>
              <div class=\"stat-value\">{len(high)}</div>
              <div class=\"stat-label\">High Risk</div>
            </div>
          </div>
          <div class=\"stat-card stat-med\">
            <div class=\"stat-icon\">⚠️</div>
            <div>
              <div class=\"stat-value\">{len(med)}</div>
              <div class=\"stat-label\">Medium Risk</div>
            </div>
          </div>
          <div class=\"stat-card stat-low\">
            <div class=\"stat-icon\">⚡</div>
            <div>
              <div class=\"stat-value\">{len(low)}</div>
              <div class=\"stat-label\">Low Risk</div>
            </div>
          </div>
        </section>
        <section class="controls">
          <div class="chip-group" id="riskChips">
            <button class="chip active" data-risk="high">High</button>
            <button class="chip active" data-risk="medium">Medium</button>
            <button class="chip active" data-risk="low">Low</button>
          </div>
          <div class="date-group">
            <button class="chip" data-range="today">Today</button>
            <button class="chip" data-range="7">Last 7 days</button>
            <button class="chip" data-range="30">Last 30 days</button>
            <span class="custom-range">
              <input type="date" id="startDate">
              <span style="color:var(--muted);">to</span>
              <input type="date" id="endDate">
              <button class="btn" id="applyRange">Apply</button>
            </span>
          </div>
          <div style="flex:1"></div>
          <div class="toggle">
            <button class="btn" id="manualSyncBtn">Manual Sync</button>
            <label class="toggle-label" style="margin-left:8px;"><input type="checkbox" id="darkToggle"> Dark mode</label>
          </div>
        </section>
        <div class=\"table-wrapper\">
          <table class=\"table\">
            <thead><tr><th class="sortable" data-sort="date">Date (UTC)</th><th class="sortable" data-sort="time">Time</th><th class="sortable" data-sort="amount">Amount</th><th>Merchant/Account</th><th class="sortable" data-sort="risk">Risk</th><th>AI Analysis</th><th>Action</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
      </main>
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

        async function manualSync() {{
          try {{
            const res = await fetch('/api/manual-sync', {{ method: 'POST' }});
            const data = await res.json();
            const f = data.transactions_forwarded ?? data.forwarded ?? 0;
            const n = data.transactions_found ?? data.found ?? 0;
            alert('Manual sync: forwarded ' + f + '/' + n + ' (status ' + (data.upstream_status ?? res.status) + ')');
            location.reload();
          }} catch (e) {{
            alert('Manual sync failed');
          }}
        }}

        (function() {{
          const msBtn = document.getElementById('manualSyncBtn');
          if (msBtn) msBtn.addEventListener('click', manualSync);

          const tbody = document.querySelector('tbody');
          const rows = Array.from(tbody.querySelectorAll('tr'));
          let activeRisks = new Set(['high','medium','low']);
          let range = {{ min: -Infinity, max: Infinity }};
          let sort = {{ key: 'date', dir: 'desc' }}; // default

          function intAttr(el, name) {{ return parseInt(el.dataset[name], 10) || 0; }}
          function riskRank(r) {{ return r==='high'?3:(r==='medium'?2:1); }}

          function applyFilters() {{
            rows.forEach(tr => {{
              const risk = (tr.dataset.risk||'').toLowerCase();
              const ts = intAttr(tr, 'ts');
              const show = activeRisks.has(risk) && ts >= range.min && ts <= range.max;
              tr.style.display = show ? '' : 'none';
            }});
          }}

          function applySort() {{
            const key = sort.key; const dir = sort.dir==='asc'?1:-1;
            const visible = rows.filter(tr => tr.style.display !== 'none');
            visible.sort((a,b) => {{
              if (key==='amount') return (parseFloat(a.dataset.amt)-parseFloat(b.dataset.amt))*dir;
              if (key==='date' || key==='time') return (intAttr(a,'ts')-intAttr(b,'ts'))*dir;
              if (key==='risk') return (riskRank(a.dataset.risk)-riskRank(b.dataset.risk))*dir;
              return 0;
            }});
            visible.forEach(tr => tbody.appendChild(tr));
          }}

          function refresh() {{ applyFilters(); applySort(); }}

          // Risk chips
          document.querySelectorAll('.chip-group [data-risk]').forEach(btn => {{
            btn.addEventListener('click', () => {{
              btn.classList.toggle('active');
              const r = btn.dataset.risk;
              if (btn.classList.contains('active')) activeRisks.add(r); else activeRisks.delete(r);
              if (activeRisks.size===0) {{
                document.querySelectorAll('.chip-group [data-risk]').forEach(b => b.classList.add('active'));
                activeRisks = new Set(['high','medium','low']);
              }}
              refresh();
            }});
          }});

          // Date quick ranges
          function setRangeDays(days) {{
            const now = new Date();
            const max = Math.floor(now.getTime()/1000);
            const min = (days===0)
              ? Math.floor(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())/1000)
              : max - (days*24*3600);
            range = {{ min, max }};
            refresh();
          }}
          document.querySelectorAll('[data-range]').forEach(btn => {{
            btn.addEventListener('click', () => {{
              const v = btn.dataset.range;
              if (v==='today') setRangeDays(0); else setRangeDays(parseInt(v,10));
            }});
          }});
          const applyBtn = document.getElementById('applyRange');
          if (applyBtn) {{
            applyBtn.addEventListener('click', () => {{
              const s = document.getElementById('startDate').value;
              const e = document.getElementById('endDate').value;
              if (s) {{ const sd = new Date(s+'T00:00:00Z'); range.min = Math.floor(sd.getTime()/1000); }}
              if (e) {{ const ed = new Date(e+'T23:59:59Z'); range.max = Math.floor(ed.getTime()/1000); }}
              refresh();
            }});
          }}

          // Sorting
          document.querySelectorAll('th.sortable').forEach(th => {{
            th.addEventListener('click', () => {{
              const key = th.dataset.sort;
              if (sort.key === key) sort.dir = (sort.dir==='asc'?'desc':'asc'); else {{ sort.key = key; sort.dir = 'asc'; }}
              // indicators
              document.querySelectorAll('th.sortable').forEach(x => x.textContent = x.textContent.replace(/[▲▼]$/, ''));
              th.textContent = th.textContent.replace(/[▲▼]$/, '') + (sort.dir==='asc'?' ▲':' ▼');
              applySort();
            }});
          }});

          // Dark mode
          const darkToggle = document.getElementById('darkToggle');
          if (darkToggle) {{
            darkToggle.addEventListener('change', () => {{
              document.body.classList.toggle('dark', darkToggle.checked);
            }});
          }}

          // initial apply (keeps default order)
          applyFilters();
        }})();
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

