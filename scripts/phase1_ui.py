"""The Phase-1 grading page. Single file, no CDNs, no network, no dependencies.

Kept separate from phase1_grade.py so the blind-safe loaders and the server logic stay
readable. The page is served as one string; nothing is fetched from the internet.

SELECT-TO-QUOTE is the point. Every field that must be verbatim - the top hypothesis,
the supporting quotes, the disconfirming evidence - can ONLY be filled by selecting
text in the transcript pane. There is no text input behind them. Verbatim-ness is
therefore a property of the interface, not of the grader's discipline, and the turn
number rides along automatically because it is read off the selected element.

The two free-text boxes are the ones that are the grader's OWN observation rather than
the agent's words: harness-vs-model attribution, and extractor notes.
"""

PAGE = r"""<!doctype html>
<meta charset="utf-8">
<title>Phase 1 — blind claim extraction</title>
<style>
 :root{--bg:#11131a;--fg:#e8e9ee;--dim:#9aa0b4;--line:#2a2e3c;--acc:#7aa2f7;
       --ok:#9ece6a;--warn:#e0af68;--card:#171a24}
 *{box-sizing:border-box}
 body{margin:0;height:100vh;display:flex;flex-direction:column;background:var(--bg);
      color:var(--fg);font:14px/1.55 ui-sans-serif,system-ui,Segoe UI,sans-serif}
 header{display:flex;gap:16px;align-items:center;padding:10px 16px;
        border-bottom:1px solid var(--line);flex:0 0 auto}
 header b{font-size:15px}
 .sp{flex:1}
 button{background:#222736;color:var(--fg);border:1px solid var(--line);
        border-radius:6px;padding:7px 12px;cursor:pointer;font-size:13px}
 button:hover{border-color:var(--acc)}
 button.primary{background:var(--acc);color:#0b0d13;border-color:var(--acc);font-weight:600}
 button:disabled{opacity:.4;cursor:not-allowed}
 main{flex:1;display:flex;min-height:0}
 #left{flex:1.35;overflow:auto;padding:16px 20px;border-right:1px solid var(--line)}
 #right{flex:1;overflow:auto;padding:16px 20px}
 .turn{margin:0 0 14px;padding:10px 12px;background:var(--card);
       border:1px solid var(--line);border-radius:8px}
 .turn h4{margin:0 0 6px;font-size:12px;color:var(--dim);font-weight:600;
          text-transform:uppercase;letter-spacing:.04em}
 .turn pre{margin:0;white-space:pre-wrap;word-wrap:break-word;font:13px/1.5
           ui-monospace,Consolas,monospace}
 .kind-thinking{border-left:3px solid #565f89}
 .kind-reasoning{border-left:3px solid var(--acc)}
 .kind-prompts_sent{border-left:3px solid var(--warn)}
 .kind-replies_as_the_agent_saw_them{border-left:3px solid var(--ok)}
 .field{margin-bottom:16px}
 .field label{display:block;font-size:12px;color:var(--dim);margin-bottom:5px;
              text-transform:uppercase;letter-spacing:.04em}
 .ro{background:#1b1f2b;border:1px solid var(--line);border-radius:6px;padding:8px 10px;
     color:var(--fg)}
 .verbatim{background:#12151d;border:1px dashed var(--line);border-radius:6px;
           padding:8px 10px;min-height:38px;white-space:pre-wrap}
 .verbatim.empty{color:#5b6172;font-style:italic}
 textarea{width:100%;background:#12151d;color:var(--fg);border:1px solid var(--line);
          border-radius:6px;padding:8px 10px;font:13px/1.5 inherit;resize:vertical}
 .q{background:#12151d;border:1px solid var(--line);border-radius:6px;padding:8px 10px;
    margin-bottom:7px;position:relative}
 .q .t{font-size:11px;color:var(--acc);margin-bottom:4px}
 .q .x{position:absolute;right:6px;top:6px;background:none;border:none;color:var(--dim);
       cursor:pointer;font-size:15px;padding:0 5px}
 .hint{font-size:12px;color:var(--dim);margin:4px 0 0}
 #bar{padding:8px 16px;border-top:1px solid var(--line);display:flex;gap:10px;
      align-items:center;flex:0 0 auto}
 .pill{background:#1b1f2b;border:1px solid var(--line);border-radius:20px;
       padding:3px 11px;font-size:12px;color:var(--dim)}
 ::selection{background:#3d59a1;color:#fff}
</style>
<header>
  <b>Phase 1 — blind claim extraction</b>
  <span class="pill" id="runid">—</span>
  <span class="pill" id="prog">—</span>
  <span class="sp"></span>
  <button id="back">← Back</button>
  <button id="jump">Next ungraded</button>
  <button class="primary" id="save">Save &amp; Next</button>
</header>
<main>
  <div id="left"></div>
  <div id="right">
    <div class="field"><label>verdict type (auto)</label>
      <div class="ro" id="vtype">—</div></div>
    <div class="field"><label>agent confidence (auto)</label>
      <div class="ro" id="vconf">—</div></div>
    <div class="field"><label>outcome (auto)</label>
      <div class="ro" id="vout">—</div></div>

    <div class="field">
      <label>top hypothesis — select in the transcript, then click</label>
      <div class="verbatim empty" id="hyp">nothing selected yet</div>
      <p class="hint"><button id="sethyp">Set hypothesis from selection</button>
         &nbsp;<kbd>h</kbd></p>
    </div>

    <div class="field">
      <label>supporting quotes — selection only</label>
      <div id="quotes"></div>
      <p class="hint"><button id="addq">Add quote from selection</button>
         &nbsp;<kbd>q</kbd> — the turn number is captured automatically</p>
    </div>

    <div class="field">
      <label>explicit disconfirming evidence (optional, selection only)</label>
      <div class="verbatim empty" id="disc">none</div>
      <p class="hint"><button id="setdisc">Set from selection</button>
         &nbsp;<button id="cleardisc">clear</button></p>
    </div>

    <div class="field"><label>harness-vs-model attribution notes (your own words)</label>
      <textarea id="attr" rows="3" placeholder="e.g. agent attributed the [REDACTED] marker to the harness, not the model"></textarea></div>

    <div class="field"><label>extractor notes (your own words)</label>
      <textarea id="notes" rows="3" placeholder="anything you could not resolve mechanically"></textarea></div>
  </div>
</main>
<div id="bar">
  <span class="pill">verbatim fields are selection-only, by design</span>
  <span class="pill">no paraphrase field exists</span>
  <span class="sp"></span>
  <span class="pill" id="status">ready</span>
</div>
<script>
let ORDER=[], GRADED={}, IDX=0, CUR=null, HYP="", DISC="", QUOTES=[];

const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

async function boot(){
  const o=await (await fetch('/api/order')).json();
  ORDER=o.runs; GRADED=o.graded;
  IDX=Math.max(0,ORDER.findIndex(r=>!GRADED[r]));
  if(IDX<0)IDX=0;
  await load();
}
async function load(){
  const rid=ORDER[IDX];
  const d=await (await fetch('/api/run/'+encodeURIComponent(rid))).json();
  CUR=d;
  $('runid').textContent=rid;
  $('prog').textContent=Object.keys(GRADED).length+' / '+ORDER.length+' graded';
  $('vtype').textContent=d.verdict_type===null?'(none submitted)':d.verdict_type;
  $('vconf').textContent=d.confidence===null?'—':d.confidence;
  $('vout').textContent=d.outcome;
  $('left').innerHTML=d.view.map(e=>
    `<div class="turn kind-${esc(e.kind)}" data-turn="${esc(e.turn)}">
       <h4>turn ${esc(e.turn)} · ${esc(e.kind)}${e.phase?' · '+esc(e.phase):''}</h4>
       <pre>${esc(e.text)}</pre></div>`).join('')
    + (d.verdict_block?`<div class="turn" data-turn="verdict"><h4>submitted verdict</h4>
       <pre>${esc(d.verdict_block)}</pre></div>`:'');
  const prev=GRADED[rid]||null;
  HYP=prev?prev.top_hypothesis_verbatim||"":"";
  DISC=prev?prev.explicit_disconfirming_evidence||"":"";
  QUOTES=prev?(prev.supporting_quotes||[]).slice():[];
  $('attr').value=prev?(prev.harness_vs_model_attribution_notes||""):"";
  $('notes').value=prev?(prev.mechanical_extractor_notes||""):"";
  paint(); $('left').scrollTop=0; $('status').textContent=prev?'already graded — editing':'ready';
}
function paint(){
  $('hyp').textContent=HYP||'nothing selected yet';
  $('hyp').className='verbatim'+(HYP?'':' empty');
  $('disc').textContent=DISC||'none';
  $('disc').className='verbatim'+(DISC?'':' empty');
  $('quotes').innerHTML=QUOTES.map((q,i)=>
    `<div class="q"><button class="x" data-i="${i}">×</button>
      <div class="t">turn ${esc(q.turn)}</div>${esc(q.quote)}</div>`).join('')
    || '<div class="hint">no quotes yet — select text on the left and press q</div>';
  document.querySelectorAll('.q .x').forEach(b=>b.onclick=()=>{
    QUOTES.splice(+b.dataset.i,1); paint();});
}
function grab(){
  const s=window.getSelection();
  if(!s || !s.toString().trim()) return null;
  let n=s.anchorNode;
  while(n && !(n.dataset&&n.dataset.turn)) n=n.parentElement;
  if(!n || !$('left').contains(n)){ $('status').textContent='select inside the transcript pane'; return null; }
  return {turn:n.dataset.turn, quote:s.toString().trim()};
}
$('addq').onclick=()=>{const g=grab(); if(g){QUOTES.push(g);paint();$('status').textContent='quote added from turn '+g.turn;}};
$('sethyp').onclick=()=>{const g=grab(); if(g){HYP=g.quote;paint();$('status').textContent='hypothesis set';}};
$('setdisc').onclick=()=>{const g=grab(); if(g){DISC=g.quote;paint();}};
$('cleardisc').onclick=()=>{DISC="";paint();};
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='TEXTAREA')return;
  if(e.key==='q')$('addq').click();
  if(e.key==='h')$('sethyp').click();
});
$('save').onclick=async()=>{
  const row={run_id:ORDER[IDX], top_hypothesis_verbatim:HYP,
    supporting_quotes:QUOTES, explicit_disconfirming_evidence:DISC||null,
    harness_vs_model_attribution_notes:$('attr').value.trim()||'none',
    mechanical_extractor_notes:$('notes').value.trim()||'none'};
  const r=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(row)});
  if(!r.ok){$('status').textContent='SAVE FAILED';return;}
  GRADED[ORDER[IDX]]=(await r.json()).row;
  $('status').textContent='saved';
  if(IDX<ORDER.length-1){IDX++;await load();}else{$('status').textContent='all done';}
};
$('back').onclick=async()=>{if(IDX>0){IDX--;await load();}};
$('jump').onclick=async()=>{const i=ORDER.findIndex(r=>!GRADED[r]);
  if(i>=0){IDX=i;await load();}else{$('status').textContent='nothing ungraded left';}};
boot();
</script>
"""
