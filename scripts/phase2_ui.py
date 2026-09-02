"""HTML for the Phase-2 grading UI. Kept separate so phase2_grade.py stays readable."""

PAGE = r"""<!doctype html>
<meta charset="utf-8">
<title>Phase 2 grading</title>
<style>
 :root{--bg:#fbfaf8;--fg:#1a1a1a;--mut:#6b6b6b;--line:#dcd8d2;--card:#fff;
       --warn:#8a3b00;--warnbg:#fff4e8;--ok:#0a6b3d;--bad:#a11}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--fg);
      font:15px/1.6 -apple-system,Segoe UI,Roboto,sans-serif}
 header{position:sticky;top:0;background:var(--warnbg);border-bottom:2px solid var(--warn);
        padding:8px 16px;z-index:10}
 header b{color:var(--warn)}
 .wrap{max-width:1180px;margin:0 auto;padding:16px}
 .cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
 @media(max-width:980px){.cols{grid-template-columns:1fr}}
 .card{background:var(--card);border:1px solid var(--line);border-radius:8px;
       padding:14px 16px;margin-bottom:14px}
 h2{font-size:14px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);
    margin:0 0 10px}
 pre{white-space:pre-wrap;word-wrap:break-word;background:#f6f4f1;padding:10px;
     border-radius:6px;font:13px/1.55 ui-monospace,Consolas,monospace;margin:6px 0}
 .q{border-left:3px solid #b9b2a8;padding-left:10px;margin:8px 0;color:#333;
    white-space:pre-wrap;word-wrap:break-word}
 .qlab{font-weight:700;color:#6b6b6b;font-size:12px;text-transform:uppercase;
       letter-spacing:.04em}
 label{display:block;margin:10px 0 4px;font-weight:600;font-size:13px}
 textarea{width:100%;min-height:70px;font:14px/1.5 inherit;padding:8px;
          border:1px solid var(--line);border-radius:6px;background:#fff}
 .grades{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
 .grades button{padding:7px 13px;border:1px solid var(--line);background:#fff;
                border-radius:999px;cursor:pointer;font-size:13px}
 .grades button.on{background:#1a1a1a;color:#fff;border-color:#1a1a1a}
 .grades button:disabled{opacity:.4;cursor:not-allowed}
 .row{display:flex;gap:8px;align-items:center;margin:6px 0;flex-wrap:wrap}
 .row button{padding:6px 11px;border:1px solid var(--line);background:#fff;
             border-radius:6px;cursor:pointer;font-size:13px}
 .row button.on{background:#1a1a1a;color:#fff;border-color:#1a1a1a}
 .nav{display:flex;gap:8px;align-items:center;margin:14px 0}
 .nav button{padding:9px 16px;border-radius:6px;border:1px solid var(--line);
             background:#fff;cursor:pointer;font-size:14px}
 .nav .save{background:#0a6b3d;color:#fff;border-color:#0a6b3d;font-weight:600}
 .muted{color:var(--mut);font-size:13px}
 .chk{background:#f6f4f1;border-radius:6px;padding:10px;font-size:13px}
 .chk li{margin:4px 0}
 .locked{background:#eee;border:1px dashed #bbb;padding:8px;border-radius:6px;
         font-size:13px;color:#555}
 .disagree{background:#fff4e8;border:1px solid var(--warn);border-radius:6px;padding:10px}
 .g-h{color:var(--ok);font-weight:700}.g-j{color:var(--bad);font-weight:700}
 .done{opacity:.55}
</style>
<header>
  <b>UNSEALED — PHASE 2.</b> <span id="mapline"></span>
  &nbsp;·&nbsp; <span id="progress"></span>
  &nbsp;·&nbsp; <span class="muted">grades append to results/phase2_grades.jsonl</span>
</header>
<div class="wrap">
  <div class="nav">
    <button onclick="go(-1)">&larr; prev</button>
    <button onclick="go(1)">next &rarr;</button>
    <span id="rid" class="muted"></span>
    <span style="flex:1"></span>
    <button onclick="jumpNext()">next ungraded</button>
  </div>
  <div id="body"></div>
</div>
<script>
let RUNS=[], i=0, cur=null, ADJ=false;

function esc(s){return (s==null?'':String(s)).replace(/[&<>]/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}

async function boot(){
  const m=await (await fetch('/api/meta')).json();
  ADJ=m.adjudicate;
  document.getElementById('mapline').textContent='map: '+m.map;
  RUNS=m.runs; i=0;
  const firstUngraded=RUNS.findIndex(r=>!r.done);
  if(firstUngraded>=0) i=firstUngraded;
  await load();
}
function prog(){
  const d=RUNS.filter(r=>r.done).length;
  document.getElementById('progress').textContent=`${d}/${RUNS.length} graded`;
}
async function load(){
  if(!RUNS.length){document.getElementById('body').innerHTML='<div class="card">No runs to grade.</div>';return;}
  i=Math.max(0,Math.min(i,RUNS.length-1));
  cur=await (await fetch('/api/run/'+encodeURIComponent(RUNS[i].run_id))).json();
  document.getElementById('rid').textContent=`${i+1} of ${RUNS.length} · ${cur.run_id} · ${cur.rung} · ${cur.condition||'?'}`;
  render(); prog();
}
function go(d){i+=d;load();}
function jumpNext(){const n=RUNS.findIndex((r,k)=>k>i&&!r.done);
  if(n>=0){i=n;load();}else{alert('No ungraded runs after this one.');}}

function gradeBtns(){
  const allowed=cur.allowed_grades;
  return allowed.map(g=>`<button ${cur.locked?'disabled':''} class="${cur.human_grade===g?'on':''}"
    onclick="pick('${g}')">${g}</button>`).join('');
}
function triBtn(field,val,label){
  return `<button class="${cur.decomposition[field]===val?'on':''}"
    onclick="setDec('${field}',${JSON.stringify(val)})">${label}</button>`;
}
function render(){
  const c=cur;
  let claim='';
  for(const [k,v] of c.claim_fields){
    let body;
    if(Array.isArray(v)){
      // Each entry is {label,text}, flattened server-side. Never String()-coerce an
      // entry: a record would render as "[object Object]" and the grader would see
      // no evidence at all.
      body=v.map(x=>{
        const lab=(x&&x.label)?`<span class="qlab">${esc(x.label)}</span> · `:'';
        const txt=esc(x&&x.text!==undefined?x.text:x);
        return `<div class="q">${lab}${txt}</div>`;
      }).join('');
    } else {
      body=`<pre>${esc(v)}</pre>`;
    }
    claim+=`<div><b>${esc(k)}</b>${body}</div>`;
  }
  let adj='';
  if(ADJ){
    adj=`<div class="card disagree"><h2>Adjudication — human vs judge</h2>
      <div class="row"><span class="g-h">human: ${esc(c.human_grade)}</span>
      <span class="g-j">judge: ${esc(c.judge_grade)}</span></div>
      <pre>human reason: ${esc(c.human_reason)}\n\njudge reason: ${esc(c.judge_reason)}</pre>
      <label>Final adjudicated grade</label>
      <div class="grades">${c.allowed_grades.map(g=>
        `<button class="${c.adjudicated_grade===g?'on':''}" onclick="pickAdj('${g}')">${g}</button>`).join('')}</div>
      <label>Why (required — this enters the disagreement ledger)</label>
      <textarea id="adjreason">${esc(c.adjudication_reason||'')}</textarea></div>`;
  }
  document.getElementById('body').innerHTML=`
  <div class="cols">
    <div>
      <div class="card"><h2>Phase-1 claim summary (verbatim, as recorded)</h2>${claim}</div>
    </div>
    <div>
      <div class="card"><h2>What was actually planted — ${esc(c.rung)}</h2>
        <pre>${esc(c.planted)}</pre>
        ${c.side_channel?`<div class="q"><b>Disclosed side-channel:</b> ${esc(c.side_channel)}</div>`:''}
        ${c.grading_note?`<div class="q"><b>Grading note:</b> ${esc(c.grading_note)}</div>`:''}
      </div>
      <div class="card"><h2>Addendum A — adjudication checklist</h2>
        <ul class="chk">${c.checklist.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>
    </div>
  </div>
  ${adj}
  <div class="card">
    <h2>Grade</h2>
    ${c.locked?`<div class="locked">Locked: this run is <b>${esc(c.human_grade)}</b>,
       derived from run status (${esc(c.status)}), not a judgement.</div>`
      :`<div class="grades">${gradeBtns()}</div>`}
    <label>Reason (required)</label>
    <textarea id="reason">${esc(c.human_reason||'')}</textarea>
    ${c.is_l2?`<div class="row"><b>L2 side-channel:</b>
      <button class="${c.l2===true?'on':''}" onclick="setL2(true)">quotes DO cite length</button>
      <button class="${c.l2===false?'on':''}" onclick="setL2(false)">they do not</button></div>`:''}
  </div>
  ${c.rung==='L0'?'':`<div class="card"><h2>Addendum D — three-stage decomposition</h2>
    <div class="muted">${esc(c.decomp_help)}</div>
    <div class="row"><b>1 coverage</b> ${triBtn('coverage',true,'yes')} ${triBtn('coverage',false,'no')}</div>
    <div class="row"><b>2 exposure</b> ${triBtn('exposure',true,'yes')} ${triBtn('exposure',false,'no')}</div>
    <div class="row"><b>3 attribution</b> ${['FULL','PARTIAL','MISS'].map(g=>triBtn('attribution',g,g)).join(' ')}</div>
    <label>Why — coverage</label>
    <textarea id="dr_coverage">${esc((c.decomposition_reasons||{}).coverage||'')}</textarea>
    <label>Why — exposure</label>
    <textarea id="dr_exposure">${esc((c.decomposition_reasons||{}).exposure||'')}</textarea>
    <label>Why — attribution</label>
    <textarea id="dr_attribution">${esc((c.decomposition_reasons||{}).attribution||'')}</textarea></div>`}
  <div class="nav"><button class="save" onclick="save()">Save &amp; next</button>
    <span id="msg" class="muted"></span></div>`;
}
function pick(g){cur.human_grade=g;render();}
function pickAdj(g){cur.adjudicated_grade=g;render();}
function setL2(v){cur.l2=v;render();}
function setDec(f,v){cur.decomposition[f]=v;render();}

async function save(){
  const reason=(document.getElementById('reason')||{}).value||'';
  if(!cur.locked && !cur.human_grade){alert('Pick a grade.');return;}
  // Locked refusal rows are exempt: the grade is derived from status, not judged, so
  // the server fills a standard reason. Every other row still needs one.
  if(!cur.locked && !reason.trim()){
    alert('A written reason is required (Addendum A item 7).');return;}
  const drv=f=>{const e=document.getElementById('dr_'+f);return e?e.value:'';};
  const ar=document.getElementById('adjreason');
  if(ADJ && cur.adjudicated_grade && !(ar&&ar.value.trim())){
    alert('An adjudicated grade needs a written reason.');return;}
  const body={run_id:cur.run_id, human_grade:cur.human_grade, human_reason:reason,
    l2_length_side_channel_cited:cur.is_l2?cur.l2:null,
    decomposition:cur.rung==='L0'?null:cur.decomposition,
    decomposition_reasons:cur.rung==='L0'?null:
      {coverage:drv('coverage'),exposure:drv('exposure'),attribution:drv('attribution')},
    adjudicated_grade:ADJ?cur.adjudicated_grade:null,
    adjudication_reason:(ADJ&&ar)?ar.value:null};
  const r=await fetch('/api/save',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const j=await r.json();
  if(!j.ok){alert('Not saved: '+j.error);return;}
  RUNS[i].done=true; document.getElementById('msg').textContent='saved';
  const n=RUNS.findIndex((r2,k)=>k>i&&!r2.done);
  if(n>=0){i=n;load();}else{prog();alert('That was the last ungraded run.');}
}
boot();
</script>
"""
