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
_PENDING_TOOL = None
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
.moneygrid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:700px){.moneygrid{grid-template-columns:1fr}}
.moneyact{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.moneyact .count{display:block;margin-top:2px}
.mout{margin-top:8px;font-size:12px;white-space:pre-wrap;border-top:1px dashed var(--line);padding-top:6px;color:var(--fg)}
.mout.ok{color:var(--green)}.mout.bad{color:var(--red)}
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

<div id="approvalbar" style="display:none;background:rgba(245,185,66,.12);border:1px solid rgba(245,185,66,.5);border-radius:10px;padding:10px 14px;margin-bottom:16px;font-weight:600">
  🔒 <span id="approvalmsg">A critical action awaits your approval.</span>
  <button id="bar_approve" class="compact" style="margin-left:10px">Approve</button>
  <button id="bar_deny" class="deny compact">Deny</button>
</div>

<div class="panel" style="margin-bottom:18px;border-color:rgba(55,212,122,.35)">
  <h2 style="color:var(--green)">Make money ⚡ — live actions on your rails</h2>
  <div class="moneygrid">
    <div class="moneyact">
      <b>Charge a customer</b> <span class="count">real Stripe charge (money in)</span>
      <div style="display:flex;gap:6px;margin-top:6px">
        <input id="mc_amount" type="text" placeholder="amount" style="flex:1;min-width:70px;background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:8px">
        <input id="mc_desc" type="text" placeholder="what for?" style="flex:2;background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:8px">
        <button class="compact" id="mc_run">Charge</button>
      </div>
      <div class="mout" id="mc_out" style="display:none"></div>
    </div>
    <div class="moneyact">
      <b>Record a deposit</b> <span class="count">cash in from a client/sale</span>
      <div style="display:flex;gap:6px;margin-top:6px">
        <input id="md_amount" type="text" placeholder="amount" style="flex:1;min-width:70px;background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:8px">
        <input id="md_source" type="text" placeholder="from whom?" style="flex:2;background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:8px">
        <button class="compact" id="md_run">Deposit</button>
      </div>
      <div class="mout" id="md_out" style="display:none"></div>
    </div>
    <div class="moneyact">
      <b>Collect an invoice</b> <span class="count">move an outstanding invoice into cash</span>
      <div style="display:flex;gap:6px;margin-top:6px">
        <input id="mi_id" type="text" placeholder="invoice id, e.g. INV-1" style="flex:1;background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:8px">
        <button class="compact" id="mi_run">Collect</button>
      </div>
      <div class="mout" id="mi_out" style="display:none"></div>
    </div>
    <div class="moneyact">
      <b>Close a deal</b> <span class="count">mark an opportunity won (needs approval)</span>
      <div style="display:flex;gap:6px;margin-top:6px">
        <input id="co_id" type="text" placeholder="opportunity id, e.g. OPP-1" style="flex:1;background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:8px">
        <select id="co_won" style="background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:8px">
          <option value="won">won</option>
          <option value="lost">lost</option>
        </select>
        <button class="compact" id="co_run">Close</button>
      </div>
      <div class="mout" id="co_out" style="display:none"></div>
    </div>
  </div>
</div>

<div class="metrics" id="metrics"></div>

<div class="grid">
  <div class="panel"><h2>Payments rail</h2><div id="payments"></div></div>
  <div class="panel"><h2>Funding gate</h2><div id="gatedetail"></div></div>
</div>

<div class="grid">
  <div class="panel"><h2>Investment book</h2><table><thead><tr><th>ID</th><th>Idea</th><th>Status</th><th>Amount</th><th>Breakeven</th><th>EPI</th><th>Notes</th></tr></thead><tbody id="investments"></tbody></table></div>
  <div class="panel"><h2>Idea pipeline <span class="count" id="ideacounts"></span></h2><table><thead><tr><th>ID</th><th>Title</th><th>Status</th><th>EPI</th><th>Model</th><th>Cap</th></tr></thead><tbody id="ideas"></tbody></table></div>
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

<div class="grid">
  <div class="panel"><h2>Job runner — fire any cron job now</h2>
    <div class="domains" id="jobbuttons"></div>
    <div class="count" style="margin-top:6px">Runs with this process's autonomy (dashboard approvals are gated here, not via the scheduler).</div>
    <pre id="jobout" style="background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:10px;margin-top:10px;max-height:220px;overflow:auto;font-size:12px;white-space:pre-wrap"></pre>
  </div>
  <div class="panel"><h2>Tool console — run any tool directly</h2>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">
      <select id="tc_domain" style="flex:1;background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:8px"></select>
      <select id="tc_tool" style="flex:1.4;background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:8px"></select>
    </div>
    <input type="text" id="tc_args" placeholder='args as JSON, e.g. {"amount": 100, "recipient": "vendor"}'
      style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:8px 10px;margin-bottom:8px">
    <div id="tc_deco" class="count" style="margin-bottom:8px;font-family:monospace;font-size:12px;white-space:pre-wrap"></div>
    <button id="tc_run">Run</button> <button id="tc_approve" class="deny" style="display:none">Approve</button> <button id="tc_deny" class="deny" style="display:none">Deny</button>
    <div class="msg jarvis" id="tc_out" style="margin-top:10px;display:none"></div>
  </div>
</div>

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
  renderJobs(s.schedule);
  renderToolConsole(s.domains);
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
    const ic=s.idea_counts||{};
    $("ideacounts").textContent="· "+ic.total+" total · "+ic.proposed+" proposed · "+ic.vetted+" vetted · "+ic.funded+" funded · "+ic.implemented+" implemented · "+ic.rejected+" rejected";
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
    if(s.pending)pendingUI(true,s.pending_desc);
  }catch(e){$("clock").textContent="state offline — retrying…";}
}
function out(el,text,bad){el.style.display="block";el.textContent=text;el.className="mout "+(bad?"bad":"ok");}
function pendingUI(show,desc){
  const bar=$("approvalbar");
  $("approvalmsg").textContent=desc||"A critical action awaits your approval.";
  bar.style.display=show?"block":"none";
  $("tc_approve").style.display=show?"":"none";
  $("tc_deny").style.display=show?"":"none";
}
async function doAsk(q){
  const send=$("send");send.disabled=true;
  msg(q,"user");
  const think=msg("JARVIS is thinking…","jarvis");
  const ctrl=new AbortController();const t=setTimeout(()=>ctrl.abort(),150000);
  try{
    const r=await fetch("/api/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({query:q}),signal:ctrl.signal});
    const d=await r.json();
    msgs.pop();/* remove thinking bubble */renderMsgs();
    if(d.approval_required){
      msg("⚠ CRITICAL ACTION REQUIRES YOUR APPROVAL — "+((d.critical||[]).join(", "))||"unspecified action"+". Decision bar is at the top of the page.","pending");
      pendingUI(true,"Critical action: "+((d.critical||[]).join(", "))||"unspecified");
    }else{msg(d.reply||(d.error||"no response"),"jarvis");}
  }catch(e){
    msgs.pop();renderMsgs();
    msg("⚠ "+(e.name==="AbortError"?"JARVIS took too long — try again or use a tool directly.":"Request failed: "+e.message),"pending");
  }finally{clearTimeout(t);$("send").disabled=false;}
}
async function decide(v){
  pendingUI(false);
  const r=await fetch("/api/approve",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({approve:v})});
  const d=await r.json();
  msg(v?"✔ Approved — executing now. ✅":"✖ Denied.","jarvis");
  msg(d.reply||d.error||"done","jarvis");
  refresh();
}
async function invokeMoney(domain,tool,args,outEl){
  out(outEl,"Working…",false);
  try{
    const r=await fetch("/api/tool",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({domain,tool,args})});
    const d=await r.json();
    if(d.approval_required){
      out(outEl,d.reply,false);
      pendingUI(true,"Critical action: "+((d.critical||[]).join(", ")));
    }else{out(outEl,d.reply||d.error||"done",!!(d.error||""));}
  }catch(e){out(outEl,"Request failed: "+e.message,true);}
}
function bus(val){const n=parseFloat(val);return isNaN(n)?null:n;}
$("mc_run").onclick=()=>invokeMoney("payments","charge_customer",
  {amount:bus($("mc_amount").value),description:$("mc_desc").value||"sale"},$("mc_out"));
$("md_run").onclick=()=>invokeMoney("finance","receive_funds",
  {amount:bus($("md_amount").value),source:$("md_source").value||"client"},$("md_out"));
$("mi_run").onclick=()=>invokeMoney("finance","collect_invoice",
  {invoice_id:$("mi_id").value},$("mi_out"));
$("co_run").onclick=()=>invokeMoney("crm","close_opportunity",
  {opportunity_id:$("co_id").value,won:($("co_won").value==="won")},$("co_out"));
let toolState={domain:"",tool:"",approval:false};
function renderToolConsole(domains){
  const byTool=[];
  domains.forEach(d=>d.tools.forEach(t=>byTool.push({domain:d.name,tool:t})));
  const selD=$("tc_domain"),selT=$("tc_tool");
  if(selD.options.length!==domains.length||selD.value!==toolState.domain){
    selD.innerHTML=domains.map(d=>'<option>'+d.name+'</option>').join("");
    if(toolState.domain)selD.value=toolState.domain;
  }
  const dname=selD.value;
  const dm=domains.find(d=>d.name===dname);
  const tools=dm?dm.tools:[];
  if(tools.indexOf(toolState.tool)>-1)selT.value=toolState.tool;
  selT.innerHTML=tools.map(t=>'<option>'+t+'</option>').join("");
  if(toolState.tool&&tools.indexOf(toolState.tool)>-1)selT.value=toolState.tool;
  const deco=$("tc_deco");
  if(dm&&dm.tools.length===0&&dname==="consult")deco.textContent="executive seat — ask it in the chat panel instead";
  else deco.textContent="targets: "+tools.join(", ")+"  →  critical tools pause for Approve/Deny";
}
async function runTool(){
  const domain=$("tc_domain").value,tool=$("tc_tool").value;
  let args={};try{args=JSON.parse($("tc_args").value||"{}");}catch(e){showToolOut("Bad JSON args: "+e.message,true);return;}
  if(domain&&tool){
    const r=await fetch("/api/tool",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({domain,tool,args})});
    const d=await r.json();
    toolState={domain,tool,approval:!!d.approval_required};
    showToolOut(d.reply||d.error||"done",!!d.error);
    pendingUI(toolState.approval,"Critical tool: "+tool);
  }
}
async function runJob(name){
  const r=await fetch("/api/job",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({job:name})});
  const d=await r.json();
  $("jobout").textContent=d.ok?(name.toUpperCase()+" →\n"+d.output):("ERROR ("+name+"): "+(d.error||"unknown"));
}
function showToolOut(text,bad){const el=$("tc_out");el.style.display="block";el.textContent=text;el.style.color=bad?"var(--red)":"var(--fg)";}
function renderJobs(sch){
  const names=["reconcile","finance","overdue_invoices","opportunities","portfolio_review","watchdogs"];
  $("jobbuttons").innerHTML=names.map(n=>
    '<button class="compact" data-j="'+n+'">'+n.replace("_"," ")+'</button>').join("");
  $("jobbuttons").querySelectorAll("button").forEach(b=>b.onclick=()=>{b.disabled=true;runJob(b.dataset.j).finally(()=>b.disabled=false);});
}
$("tc_run").onclick=runTool;
$("tc_approve").onclick=()=>decide(true);
$("tc_deny").onclick=()=>decide(false);
$("bar_approve").onclick=()=>decide(true);
$("bar_deny").onclick=()=>decide(false);
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

    idea_counts = {"total": len(data.get("ideas", [])), "proposed": 0, "vetted": 0, "funded": 0, "implemented": 0, "rejected": 0}
    for idea in data.get("ideas", []):
        status = idea.get("status", "")
        if status in idea_counts:
            idea_counts[status] += 1

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
        "idea_counts": idea_counts,
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
        if _PENDING_TOOL is not None:
            return {
                "reply": "A direct tool execution is awaiting your decision. Approve or deny it first.",
                "approval_required": True,
                "critical": [_PENDING_TOOL["name"]],
            }
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

        for _ in _ENGINE.stream(
            {"messages": [("user", query)], "next_agent": "", "approved": False},
            _CONFIG,
            stream_mode="values",
        ):
            pass
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
    """Resume the paused action after the operator approves or denies — either a
    direct tool execution staged by run_tool, or the graph's human_approval gate."""
    global _APPROVAL_PENDING, _PENDING_TOOL
    with _LOCK:
        if _PENDING_TOOL is not None:
            item = _PENDING_TOOL
            _PENDING_TOOL = None
            if not decision:
                return f"Denied — {item['name']} not executed."
            try:
                return str(item["fn"](**item["args"]))
            except Exception as exc:
                return f"Error: {type(exc).__name__}: {exc}"
        if _APPROVAL_PENDING is None or _ENGINE is None:
            return "No action is pending approval."
        _ENGINE.update_state(_CONFIG, {"approved": decision}, as_node="human_approval")
        for _ in _ENGINE.stream(None, _CONFIG, stream_mode="values"):
            pass
        snap = _ENGINE.get_state(_CONFIG)
        _APPROVAL_PENDING = None
        return _final_answer(snap)


def run_job(name: str) -> dict:
    """Run one scheduled job immediately (same functions the scheduler uses)."""
    from src.cron import JOBS

    _ensure_store()
    fn = JOBS.get(name)
    if fn is None:
        return {"ok": False, "error": f"unknown job '{name}'"}
    try:
        return {"ok": True, "output": fn()}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def run_tool(domain: str, name: str, args: dict) -> dict:
    """Execute a single domain tool directly. Critical tools pause for approval
    unless the process runs under full autonomy."""
    global _PENDING_TOOL
    from src.tools import CRITICAL_TOOLS, DOMAIN_TOOLS

    with _LOCK:
        if _APPROVAL_PENDING is not None:
            return {
                "reply": "A critical chat action is awaiting your decision. Approve or deny it first.",
                "approval_required": True,
                "critical": _APPROVAL_PENDING.get("critical", []),
            }
        if not isinstance(args, dict):
            return {"reply": "Error: args must be a JSON object of keyword arguments.", "approval_required": False}
        by_name = {
            getattr(t, "name", t.__name__): t
            for t in (DOMAIN_TOOLS.get(domain) or [])
        }
        fn = by_name.get(name)
        if fn is None:
            return {"reply": f"Error: no tool '{name}' in domain '{domain}'.", "approval_required": False}
        tool_name = getattr(fn, "name", name)
        if tool_name in CRITICAL_TOOLS and Settings.from_env(require_key=False).autonomy != "full":
            _PENDING_TOOL = {"name": tool_name, "fn": fn, "args": args}
            return {
                "reply": f"Critical tool '{tool_name}' requires your approval.",
                "approval_required": True,
                "critical": [tool_name],
            }
        try:
            return {"reply": str(fn(**args)), "approval_required": False}
        except Exception as exc:
            return {"reply": f"Error: {type(exc).__name__}: {exc}", "approval_required": False}


def live_state() -> dict:
    _ensure_store()
    from src.tools import STORE

    settings = Settings.from_env(require_key=False)
    state = state_snapshot(STORE.data, settings)
    with _LOCK:
        if _PENDING_TOOL is not None:
            state["pending"] = True
            state["pending_desc"] = f"Critical tool {_PENDING_TOOL['name']} is staged — Approve to execute it."
        elif _APPROVAL_PENDING is not None:
            state["pending"] = True
            state["pending_desc"] = f"Critical action {(_APPROVAL_PENDING.get('critical') or [])} is staged — Approve to resume it."
        else:
            state["pending"] = False
    return state


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

        if path == "/api/job":
            name = (body.get("job") or "").strip()
            if not name:
                return self._send(400, {"error": "job required"})
            try:
                return self._send(200, run_job(name))
            except Exception as exc:
                return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

        if path == "/api/tool":
            domain, name, args = body.get("domain"), body.get("tool"), body.get("args")
            if not domain or not name:
                return self._send(400, {"error": "domain and tool required"})
            try:
                return self._send(200, run_tool(domain, name, args))
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