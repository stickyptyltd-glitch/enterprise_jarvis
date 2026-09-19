"""JARVIS web dashboard.

Dependency-light by design: this is pure ``http.server`` + vanilla JS, so it
runs on any box without installing a framework. It binds to localhost by
default and talks to the same store, engines, and payment rail as the console.

Usage:
    python -m src.webui                 start dashboard (:8610)
    python -m src.webui --port 9000     custom port
    python -m src.webui --host 0.0.0.0  (not recommended — localhost only!)

Endpoints:
    GET  /               dashboard page
    GET  /api/state      live snapshot (treasury, portfolio, payments, schedule...)
    POST /api/ask        {"query": "..."}          run a JARVIS query
    POST /api/approve    {"approve": true|false}   decide pending critical action
"""

import argparse
import json
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from src.config.settings import Settings

_ENGINE = None
_CONFIG = None
_STORE_READY = False
_APPROVAL_PENDING = None
_LOCK = threading.RLock()

PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JARVIS — enterprise dashboard</title>
<style>
:root{--bg:#0b0f14;--panel:#131a22;--panel2:#182230;--line:#223042;--fg:#d9e2ec;--mut:#7c8ba0;
--green:#37d47a;--amber:#f5b942;--red:#f36d6d;--blue:#5aa9ff;--violet:#b48aff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,"Segoe UI",Roboto,Ubuntu,sans-serif;padding:20px}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:20px;letter-spacing:.5px}
h1 span{color:var(--green)}
h2{font-size:13px;letter-spacing:1.2px;text-transform:uppercase;color:var(--mut);margin-bottom:10px}
.top{display:flex;flex-wrap:wrap;align-items:center;gap:14px;margin-bottom:18px}
.treasury{font-size:26px;font-weight:700}
.sub{color:var(--mut);font-size:12px;margin-top:2px}
.badge{padding:4px 10px;border-radius:999px;font-size:12px;font-weight:600;letter-spacing:.4px}
.real{background:rgba(55,212,122,.14);color:var(--green);border:1px solid rgba(55,212,122,.4)}
.sim{background:rgba(124,139,160,.14);color:var(--mut);border:1px solid rgba(124,139,160,.4)}
.spin{animation:sp 1s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}
.metrics{display:grid;grid-template-columns:repeat(auto-fill,minmax(158px,1fr));gap:10px;margin-bottom:18px}
.mcard{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
.mcard .label{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.6px}
.mcard .value{font-size:20px;font-weight:700;margin-top:4px}
.mcard .hint{color:var(--mut);font-size:11px;margin-top:2px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:18px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--mut);text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.6px;padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:6px 8px;border-bottom:1px solid #1a2636;vertical-align:top}
tr:last-child td{border-bottom:none}
.chip{display:inline-block;background:var(--panel2);border:1px solid var(--line);border-radius:999px;padding:2px 9px;margin:2px;font-size:11px;color:var(--fg)}
.chip b{color:var(--blue)}
.st-open{color:var(--amber)}.st-overdue{color:var(--red)}.st-paid{color:var(--green)}
.st-active{color:var(--green)}.st-vetted{color:var(--blue)}.st-implemented{color:var(--green)}
.st-proposed{color:var(--mut)}.st-rejected{color:var(--red)}.st-matured{color:var(--violet)}.st-written_off{color:var(--red)}
.chat{display:grid;grid-template-columns:1fr;gap:10px}
.msgs{max-height:300px;overflow:auto;display:flex;flex-direction:column;gap:8px;padding-right:4px}
.msg{max-width:88%;padding:8px 12px;border-radius:12px;white-space:pre-wrap;font-size:13px}
.msg.user{align-self:flex-end;background:var(--blue);color:#06121f}
.msg.jarvis{align-self:flex-start;background:var(--panel2);border:1px solid var(--line)}
.msg.pending{align-self:flex-start;background:rgba(245,185,66,.12);border:1px solid rgba(245,185,66,.5);color:var(--amber);font-weight:600}
.queryrow{display:flex;gap:8px}
input[type=text]{flex:1;background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:10px 12px;font-size:14px}
input[type=text]:focus{outline:none;border-color:var(--green)}
button{background:var(--green);color:#04130a;border:none;border-radius:8px;padding:10px 16px;font-weight:700;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
button.deny{background:var(--red);color:#180203}
button.compact{padding:6px 12px;margin-top:4px}
.domains{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:4px}
.sched td:first-child{font-weight:600}
.count{color:var(--mut)}
.foot{color:var(--mut);font-size:11px;margin-top:18px;text-align:center}
a{color:var(--blue)}
</style></head>
<body><div class="wrap">
<div class="top">
  <h1>JARVIS <span>▸</span> enterprise dashboard</h1>
  <div class="treasury" id="treasury">—</div>
  <span class="badge sim" id="mode">…</span>
  <span class="badge sim" id="gate">…</span>
  <span class="badge sim" id="payprov">…</span>
  <div style="margin-left:auto;color:var(--mut);font-size:12px" id="clock"></div>
</div>

<div class="metrics" id="metrics"></div>

<div class="grid">
  <div class="panel"><h2>Payments rail</h2><div id="payments"></div></div>
  <div class="panel"><h2>Funding gate</h2><div id="gatedetail"></div></div>
</div>

<div class="grid">
  <div class="panel"><h2>Investment book</h2><table><thead><tr><th>ID</th><th>Idea</th><th>Status</th><th>Amount</th><th>Breakeven</th><th>EPI</th><th>Notes</th></tr></thead><tbody id="investments"></tbody></table></div>
  <div class="panel"><h2>Idea pipeline</h2><table><thead><tr><th>ID</th><th>Title</th><th>Status</th><th>EPI</th><th>Model</th><th>Cap</th></tr></thead><tbody id="ideas"></tbody></table></div>
</div>

<div class="grid">
  <div class="panel"><h2>Receivables</h2><table><thead><tr><th>ID</th><th>Client</th><th>Amount</th><th>Status</th><th>Due</th></tr></thead><tbody id="invoices"></tbody></table></div>
  <div class="panel"><h2>Recent ledger</h2><table><thead><tr><th>At</th><th>Type</th><th>Amount</th><th>Ref</th></tr></thead><tbody id="ledger"></tbody></table></div>
</div>

<div class="grid">
  <div class="panel"><h2>Watchdogs &amp; notifications</h2><div id="notifications"></div></div>
  <div class="panel"><h2>Schedule</h2><table><thead><tr><th>Job</th><th>Time</th><th>Next run</th></tr></thead><tbody id="schedule"></tbody></table></div>
</div>

<div class="panel" style="margin-bottom:18px"><h2>Domains &amp; tools</h2><div id="domains"></div></div>

<div class="panel chat">
  <h2>Ask JARVIS</h2>
  <div class="msgs" id="msgs"></div>
  <div class="queryrow">
    <input type="text" id="query" placeholder="e.g. cash runway, fund IV-00x, list overdue invoices, payment_status…" autocomplete="off">
    <button id="send">Send</button>
  </div>
</div>

<div class="foot">JARVIS engine · local dashboard · no secrets are transmitted by this page</div>
</div>
<script>
const $=id=>document.getElementById(id);
const money=n=>"$"+new Intl.NumberFormat("en-US",{minimumFractionDigits:2,maximumFractionDigits:2}).format(n);
let msgs=[];
function msg(text,cls){msgs.push({text,cls});renderMsgs();}
function renderMsgs(){
  $("msgs").innerHTML=msgs.map(m=>'<div class="msg '+m.cls+'"></div>').join("");
  msgs.forEach((m,i)=>{const el=$("msgs").children[i];el.textContent=m.text;});
  $("msgs").scrollTop=$("msgs").scrollHeight;
}
function esc(s){const d=document.createElement("div");d.textContent=s;return d.innerHTML;}
function statusCls(x){return "st-"+String(x).toLowerCase();}
function render(s){
  $("clock").textContent=new Date().toLocaleString();
  $("treasury").textContent=money(s.company.balance)+" "+s.company.currency;
  const p=s.payments;
  const m=$("mode");m.textContent="PAYMENTS: "+p.mode.toUpperCase();m.className="badge "+(p.mode==="real"?"real":"sim");
  $("payprov").textContent="providers: "+(p.providers.length?p.providers.join(", "):"none");
  const g=$("gate");g.textContent=s.gate&&s.gate.paused?"GATE: PAUSED":"GATE: OPEN";g.className="badge "+(s.gate&&s.gate.paused?"deny":"real");
  renderMetrics(s.metrics);
  $("payments").innerHTML=
    "Mode <b>"+p.mode+"</b> · burn-wallet cap <b>"+money(p.cap)+"</b> · providers <b>"+(p.providers.length?p.providers.join(", "):"none")+"</b>"+
    (p.spend_cap_enforced?' <span class="count">— outbound moves capped</span>':"");
  $("gatedetail").innerHTML=s.gate?
    ("Paused: <b>"+String(s.gate.paused)+"</b><br>Since: "+(s.gate.at||"—")+"<br>Reason: <b>"+esc(s.gate.reason||"—")+"</b>")
    :"Not triggered — autopilot gate never closed.";
  $("investments").innerHTML=s.investments.map(i=>
    "<tr><td>"+i.id+'</td><td><span class="'+statusCls(i.status)+'">'+i.status+"</span> ("+i.idea_id+")</td><td>"+money(i.amount)+
    "</td><td>"+i.breakeven+"</td><td>"+i.epi+"</td><td>"+i.progress+"</td></tr>").join("");
  $("ideas").innerHTML=s.ideas.map(i=>
    "<tr><td>"+i.id+'</td><td>'+esc(i.title)+'</td><td><span class="'+statusCls(i.status)+'">'+i.status+'</span></td><td>'+
    (i.epi?"<b>"+i.epi+"</b>":"—")+"</td><td>"+i.revenue_model+"</td><td>"+(i.required_capital?money(i.required_capital):"—")+"</td></tr>").join("");
  $("invoices").innerHTML=s.invoices.map(i=>
    "<tr><td>"+i.id+"</td><td>"+esc(i.client)+"</td><td>"+money(i.amount)+"</td><td><span class='"+statusCls(i.status)+"'>"+i.status+"</span></td><td>"+i.due+"</td></tr>").join("");
  $("ledger").innerHTML=s.ledger.map(l=>
    "<tr><td>"+l.at+'</td><td>'+l.type+'</td><td style="color:'+(l.amount<0?"var(--red)":"var(--green)")+'">'+money(l.amount)+'</td><td class="count">'+esc(l.ref)+"</td></tr>").join("");
  $("notifications").innerHTML=s.notifications.length? s.notifications.map(n=>"<div style='margin:4px 0'><span class='count'>"+n.at+"</span> — "+esc(n.message)+"</div>").join("")
    :"<span class='count'>No alerts. Watchdogs clear.</span>";
  $("schedule").innerHTML=s.schedule.jobs.map(j=>
    "<tr><td>"+j.name+'</td><td>'+j.time+'</td><td class="count">'+j.next+"</td></tr>").join("")+
    "<tr><td>watchdog sweep</td><td>every "+s.schedule.interval+" min</td><td class='count'>rolling</td></tr>";
  $("domains").innerHTML=s.domains.map(d=>
    '<div class="domains" style="margin-top:8px"><h2 style="margin:0 4px 0 0">'+d.name+'</h2><span class="count">'+d.tools.length+' tools</span></div>'+
    '<div class="domains">'+(d.tools.length?d.tools.map(t=>'<span class="chip">'+esc(t)+'</span>').join(""):'<span class="count">live executive seat — ask by name</span>')+"</div>").join("");
}
function renderMetrics(m){
  const cards=[["Treasury",money(m.bank_balance),""],["Open receivables",money(m.open_receivables),""],
    ["Overdue invoices",m.overdue_invoice_count,m.overdue_invoice_count?"past due":"clear"],
    ["Pipeline (weighted)",money(m.weighted_pipeline),m.open_opportunity_count+" opportunities"],
    ["Portfolio deployed",money(m.portfolio_deployed),m.active_investments+" active"],
    ["At risk / matured",m.investments_at_risk+"/"+m.investments_matured,"written off "+m.investments_written_off],
    ["Payroll / active",money(m.monthly_payroll)+" / "+m.monthly_payroll_employees,""],
    ["Active projects",m.active_projects,"budget > spend"]];
  $("metrics").innerHTML=cards.map(c=>'<div class="mcard"><div class="label">'+c[0]+'</div><div class="value">'+c[1]+'</div><div class="hint">'+c[2]+"</div></div>").join("");
}
async function refresh(){
  try{
    const r=await fetch("/api/state");const s=await r.json();
    sessionStorage.lastState||(sessionStorage.lastState="x");
    render(s);
  }catch(e){$("clock").textContent="state offline — retrying…";}
}
async function doAsk(q){
  const send=$("send");send.disabled=true;
  msg(q,"user");
  const r=await fetch("/api/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({query:q})});
  const d=await r.json();
  if(d.approval_required){
    msg("⚠ CRITICAL ACTION REQUIRES YOUR APPROVAL — tools: "+(d.critical||[]).join(", ")+". Approve or deny below.","pending");
    msg("Pending approval.","jarvis");
  }else{msg(d.reply||(d.error||"no response"),"jarvis");}
  $("send").disabled=false;
}
async function decide(v){
  const r=await fetch("/api/approve",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({approve:v})});
  const d=await r.json();
  msg(v?"✔ Approved — executing now. ✅":"✖ Denied.","jarvis");
  msg(d.reply||d.error||"done","jarvis");
  refresh();
}
function onSend(){
  const q=$("query").value.trim();if(!q)return;$("query").value="";doAsk(q);
}
$("send").onclick=onSend;
$("query").addEventListener("keydown",e=>{if(e.key==="Enter")onSend();});
refresh();setInterval(refresh,10000);
</script></body></html>
"""


def _ensure_store():
    global _STORE_READY
    from src.store import BusinessStore
    from src.tools import set_store

    if not _STORE_READY:
        settings = Settings.from_env(require_key=False)
        set_store(BusinessStore(settings.data_file))
        _STORE_READY = True


def _next_run(hour: int, minute: int) -> str:
    now = datetime.now()
    when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if when <= now:
        when += timedelta(days=1)
    return when.isoformat(timespec="minutes")


def state_snapshot(data: dict, settings: Settings) -> dict:
    """Pure state projection — testable without touching the global store."""
    from src.cron import SCHEDULE, WATCHDOG_SWEEP_MINUTES
    from src.payments import providers, resolve_mode
    from src.tools.watch import WATCHDOG_METRICS

    metrics = {}
    for name, fn in WATCHDOG_METRICS.items():
        try:
            value = fn(data)
            metrics[name] = round(float(value), 2) if isinstance(value, (int, float)) else value
        except Exception:
            metrics[name] = None
    metrics["monthly_payroll_employees"] = metrics.get("active_employees", 0)

    gate = data.get("funding_gate")
    gate = gate if isinstance(gate, dict) else {}

    ledger = [
        {"at": e.get("at", ""), "type": e.get("type", ""), "amount": e.get("amount", 0),
         "ref": e.get("ref", "")}
        for e in data.get("ledger", [])
    ][-12:][::-1]

    ideas = [
        {
            "id": i.get("id"),
            "title": i.get("title"),
            "status": i.get("status"),
            "category": i.get("category"),
            "revenue_model": i.get("revenue_model"),
            "epi": round(float((i.get("assessment") or {}).get("epi", 0)), 1) or None,
            "required_capital": i.get("required_capital"),
        }
        for i in data.get("ideas", [])
    ][::-1]

    investments = [
        {
            "id": i.get("id"),
            "idea_id": i.get("idea_id"),
            "amount": i.get("amount"),
            "status": i.get("status"),
            "breakeven": (f"{i['breakeven_months']:.1f} mo"
                          if isinstance(i.get("breakeven_months"), (int, float)) else "n/a"),
            "epi": i.get("epi_at_funding"),
            "progress": len(i.get("notes", []) or []),
        }
        for i in data.get("investments", [])
    ]

    invoices = [
        {"id": i.get("id"), "client": i.get("client"), "amount": i.get("amount"),
         "status": i.get("status"), "due": i.get("due")}
        for i in data.get("invoices", [])
    ][::-1]

    notifications = [
        {"at": n.get("at", ""), "message": n.get("message", "")}
        for n in data.get("notifications", [])
    ][-8:][::-1]

    schedule = {
        "interval": WATCHDOG_SWEEP_MINUTES,
        "jobs": [
            {"name": name, "time": f"{h:02d}:{m:02d}", "next": _next_run(h, m)}
            for name, (h, m) in SCHEDULE
        ],
    }

    domains = []
    try:
        from src.agents.core import DOMAIN_AGENTS
        from src.tools import DOMAIN_TOOLS

        for agent in DOMAIN_AGENTS:
            tools = DOMAIN_TOOLS.get(agent) or []
            domains.append({
                "name": agent,
                "tools": [getattr(t, "name", t.__name__) for t in tools],
            })
    except Exception:
        domains = []

    return {
        "company": {
            "name": data.get("company", {}).get("name", "—"),
            "currency": data.get("company", {}).get("currency", "USD"),
            "balance": data.get("company", {}).get("bank_balance", 0),
        },
        "payments": {
            "mode": settings.real_money or resolve_mode(),
            "cap": settings.real_spend_cap or 0,
            "providers": providers(),
            "spend_cap_enforced": bool(
                (settings.real_money or resolve_mode()) == "real" and settings.real_spend_cap
            ),
        },
        "gate": {
            "paused": bool(gate.get("paused")),
            "at": gate.get("at"),
            "reason": gate.get("reason", "no reason recorded"),
        },
        "metrics": metrics,
        "ledger": ledger,
        "ideas": ideas,
        "investments": investments,
        "invoices": invoices,
        "notifications": notifications,
        "schedule": schedule,
        "domains": domains,
    }


def _final_answer(state) -> str:
    messages = getattr(state, "values", state).get("messages", [])
    for message in reversed(messages):
        content = getattr(message, "content", "")
        if content and getattr(message, "type", "") in ("ai", "human"):
            return str(content)
    return "No response produced."


def run_query(query: str) -> dict:
    """Run a query through the JARVIS graph. Critical actions pause for approval
    instead of prompting on stdin, so the dashboard can ask the operator."""
    global _ENGINE, _CONFIG, _APPROVAL_PENDING
    from src.tools import CRITICAL_TOOLS

    with _LOCK:
        if _APPROVAL_PENDING is not None:
            return {
                "reply": "A critical action is awaiting your decision. Approve or deny it first.",
                "approval_required": True,
                "critical": _APPROVAL_PENDING.get("critical", []),
            }
        _ensure_store()
        if _ENGINE is None:
            from src.agents.core import build_jarvis_graph

            settings = Settings.from_env()
            _ENGINE = build_jarvis_graph(settings)
            _CONFIG = {"configurable": {"thread_id": "web_admin_session"}}

        _ENGINE.stream(
            {"messages": [("user", query)], "next_agent": "", "approved": False},
            _CONFIG,
            stream_mode="values",
        )
        snap = _ENGINE.get_state(_CONFIG)
        if "human_approval" in snap.next:
            last = snap.values["messages"][-1]
            critical = sorted({
                tc.get("name") for tc in getattr(last, "tool_calls", [])
                if tc.get("name") in CRITICAL_TOOLS
            })
            _APPROVAL_PENDING = {"critical": critical}
            return {"reply": "Critical action requires your approval.", "approval_required": True, "critical": critical}
        return {"reply": _final_answer(snap), "approval_required": False}


def approve_resume(decision: bool) -> str:
    """Resume the paused graph after the operator approves or denies."""
    global _APPROVAL_PENDING
    with _LOCK:
        if _APPROVAL_PENDING is None or _ENGINE is None:
            return "No action is pending approval."
        _ENGINE.update_state(_CONFIG, {"approved": decision}, as_node="human_approval")
        _ENGINE.stream(None, _CONFIG, stream_mode="values")
        snap = _ENGINE.get_state(_CONFIG)
        _APPROVAL_PENDING = None
        return _final_answer(snap)


def live_state() -> dict:
    _ensure_store()
    from src.tools import STORE

    settings = Settings.from_env(require_key=False)
    return state_snapshot(STORE.data, settings)


class Handler(BaseHTTPRequestHandler):
    server_version = "JARVIS/1"

    def _send(self, code: int, payload, ctype: str = "application/json; charset=utf-8") -> None:
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        elif isinstance(payload, str):
            payload = payload.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args) -> None:
        pass

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if path == "/api/state":
            return self._send(200, live_state())
        if path in ("/favicon.ico", "/favicon.svg"):
            return self._send(204, b"")
        return self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}

        if path == "/api/ask":
            query = (body.get("query") or "").strip()
            if not query:
                return self._send(400, {"error": "query required"})
            try:
                return self._send(200, run_query(query))
            except Exception as exc:
                return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

        if path == "/api/approve":
            try:
                return self._send(200, {"reply": approve_resume(bool(body.get("approve"))), "approval_required": False})
            except Exception as exc:
                return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

        return self._send(404, {"error": "not found"})


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS web dashboard")
    parser.add_argument("--host", default=None, help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="port (default 8610)")
    args = parser.parse_args()

    settings = Settings.from_env(require_key=False)
    host = args.host or settings.webui_bind
    port = args.port or settings.webui_port
    if host not in ("127.0.0.1", "localhost"):
        print(f"\033[91mwarning: binding {host} exposes JARVIS tool power on the network\033[0m")

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"\033[92mJARVIS dashboard → http://{host}:{port}\033[0m")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


if __name__ == "__main__":
    main()