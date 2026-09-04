"""The write-up fill-in page. Single file, no CDNs, no network, no dependencies.

Kept separate from writeup_fill.py so the parser and the server logic stay readable.
The page is served as one string; nothing is fetched from the internet.

WHAT THIS PAGE CONTAINS, BY CONSTRUCTION
  * no draft prose, no suggested wording, no autocomplete, no model call of any kind
  * every word of every answer is typed by Ebin into a plain textarea
  * everything else on screen is a FACT read out of a committed file: the template's
    own facts block beside the slot, and the reference files in the right rail

The one-slot-at-a-time layout is the point. The template is 42 slots long and every
slot has its own numbers; showing them all at once is how a number ends up in the
wrong paragraph.
"""

PAGE = r"""<!doctype html>
<meta charset="utf-8">
<title>Write-up fill-in — WRITEUP_TEMPLATE.md</title>
<style>
 :root{--bg:#11131a;--fg:#e8e9ee;--dim:#9aa0b4;--line:#2a2e3c;--acc:#7aa2f7;
       --ok:#9ece6a;--warn:#e0af68;--bad:#f7768e;--card:#171a24;--card2:#12151d}
 *{box-sizing:border-box}
 body{margin:0;height:100vh;display:flex;flex-direction:column;background:var(--bg);
      color:var(--fg);font:14px/1.55 ui-sans-serif,system-ui,Segoe UI,sans-serif}
 header{display:flex;gap:12px;align-items:center;padding:9px 14px;
        border-bottom:1px solid var(--line);flex:0 0 auto}
 header b{font-size:15px}
 .sp{flex:1}
 button{background:#222736;color:var(--fg);border:1px solid var(--line);
        border-radius:6px;padding:6px 11px;cursor:pointer;font-size:13px}
 button:hover{border-color:var(--acc)}
 button.primary{background:var(--acc);color:#0b0d13;border-color:var(--acc);font-weight:600}
 button:disabled{opacity:.4;cursor:not-allowed}
 input[type=text]{background:var(--card2);color:var(--fg);border:1px solid var(--line);
        border-radius:6px;padding:5px 9px;font:13px/1.4 inherit}
 .pill{background:#1b1f2b;border:1px solid var(--line);border-radius:20px;
       padding:3px 10px;font-size:12px;color:var(--dim);white-space:nowrap}
 .pill.warn{color:var(--warn);border-color:#3a3122}
 .pill.ok{color:var(--ok)}
 .pill.bad{color:var(--bad);border-color:#4a2733}
 .bar{width:150px;height:7px;background:#1b1f2b;border:1px solid var(--line);
      border-radius:20px;overflow:hidden}
 .bar i{display:block;height:100%;background:var(--acc);width:0}

 #rules{flex:0 0 auto;border-bottom:1px solid var(--line);background:#141721;
        padding:7px 14px;font-size:12px;color:var(--dim)}
 #rules ol{margin:0;padding:0 0 0 4px;list-style:none;display:flex;flex-wrap:wrap;gap:6px}
 #rules li{background:#1b1f2b;border:1px solid var(--line);border-radius:5px;
           padding:2px 8px;max-width:100%}
 #rules li b{color:var(--fg)}
 #rules .qs{margin:6px 0 0;display:flex;flex-wrap:wrap;gap:10px}
 #rules .qs span{font-style:italic}
 #rules.short li{max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 #rules.short .qs span{max-width:300px;overflow:hidden;text-overflow:ellipsis;
                       white-space:nowrap}

 main{flex:1;display:flex;min-height:0}
 #rail{flex:0 0 236px;overflow:auto;border-right:1px solid var(--line);padding:8px 0}
 #rail .sec{padding:6px 12px;cursor:pointer;border-left:3px solid transparent}
 #rail .sec:hover{background:#161923}
 #rail .sec.on{background:#1a1f2e;border-left-color:var(--acc)}
 #rail .sec.done .n{color:var(--ok)}
 #rail .sec .t{display:block;font-size:12.5px}
 #rail .sec .n{float:right;font-size:11px;color:var(--dim);margin-left:6px}
 #rail .sec.noslot{opacity:.45;cursor:default}
 #rail .sec.exec .t:after{content:" · last";color:var(--warn);font-size:11px}

 #mid{flex:1;min-width:0;display:flex;flex-direction:column;overflow:auto;padding:14px 18px}
 #crumb{font-size:12px;color:var(--dim);margin-bottom:2px}
 #crumb b{color:var(--fg);font-size:15px}
 #lock{background:#241c15;border:1px solid #4a3a22;color:var(--warn);border-radius:8px;
       padding:9px 12px;margin:8px 0}
 #restore{background:#1b2418;border:1px solid #35502a;color:var(--ok);border-radius:8px;
          padding:8px 12px;margin:8px 0;font-size:13px}
 /* flex:0 0 auto matters: in a column flex box the facts panel would otherwise be
    the item that shrinks, and the numbers are the whole point of the page */
 #facts{flex:0 0 auto;background:var(--card);border:1px solid var(--line);
        border-radius:8px;padding:2px 14px 10px;margin:10px 0;max-height:44vh;
        overflow:auto}
 #facts h2,#facts h3,#facts h4,#facts h5,#facts h6{font-size:13px;color:var(--acc);
        margin:12px 0 4px;text-transform:none}
 #facts p{margin:7px 0}
 #facts ul,#facts ol{margin:6px 0;padding-left:20px}
 #facts li{margin:3px 0}
 #facts code{background:#0e1017;border:1px solid var(--line);border-radius:4px;
             padding:0 4px;font:12px/1.4 ui-monospace,Consolas,monospace}
 #facts pre{background:#0e1017;border:1px solid var(--line);border-radius:6px;padding:8px;
            overflow:auto}
 #facts blockquote{margin:7px 0;padding:2px 10px;border-left:3px solid var(--line);
                   color:var(--dim)}
 #facts hr{border:0;border-top:1px solid var(--line);margin:10px 0}
 .tw{overflow:auto;margin:8px 0}
 .tw table{border-collapse:collapse;font-size:12.5px;min-width:100%}
 .tw th,.tw td{border:1px solid var(--line);padding:4px 7px;text-align:left;
               vertical-align:top}
 .tw th{background:#1b1f2b;color:var(--dim);font-weight:600}
 .factbar{display:flex;gap:8px;align-items:center;font-size:12px;color:var(--dim);
          margin-top:8px}
 #prompt{font-size:13px;color:var(--warn);margin:2px 0 6px}
 #ta{width:100%;min-height:200px;flex:1 1 auto;background:var(--card2);color:var(--fg);
     border:1px solid var(--line);border-radius:8px;padding:11px 13px;resize:vertical;
     font:15px/1.65 ui-sans-serif,system-ui,Segoe UI,sans-serif}
 #ta:focus{outline:none;border-color:var(--acc)}
 #ta:disabled{opacity:.55}
 #ctl{display:flex;gap:8px;align-items:center;padding:9px 0 2px;flex-wrap:wrap}

 #ref{flex:0 0 430px;min-width:0;border-left:1px solid var(--line);display:flex;
      flex-direction:column}
 #tabs{display:flex;flex-wrap:wrap;gap:4px;padding:8px 10px 6px;
       border-bottom:1px solid var(--line)}
 #tabs button{padding:3px 8px;font-size:12px}
 #tabs button.on{background:var(--acc);color:#0b0d13;border-color:var(--acc)}
 #reftools{display:flex;gap:6px;align-items:center;padding:7px 10px;
           border-bottom:1px solid var(--line)}
 #reftools input{flex:1;min-width:0}
 #reftools input#dec{flex:0 0 74px}
 #refbody{flex:1;overflow:auto;padding:6px 12px 24px;font-size:12.5px}
 #refbody h2,#refbody h3,#refbody h4,#refbody h5,#refbody h6{color:var(--acc);
        font-size:13px;margin:12px 0 4px}
 #refbody p{margin:6px 0}
 #refbody code{background:#0e1017;border:1px solid var(--line);border-radius:4px;
               padding:0 3px;font:11.5px/1.4 ui-monospace,Consolas,monospace}
 #refbody pre{background:#0e1017;border:1px solid var(--line);border-radius:6px;padding:7px;
              overflow:auto}
 #refbody img{max-width:100%;border:1px solid var(--line);border-radius:6px;
              background:#fff;margin:6px 0}
 #refbody blockquote{margin:6px 0;padding:2px 9px;border-left:3px solid var(--line);
                     color:var(--dim)}
 #refbody .note{color:var(--dim);font-style:italic;margin:6px 0}
 #refbody tr.hit{outline:2px solid var(--warn)}
 mark{background:#e0af68;color:#0b0d13;border-radius:2px}

 #modal{position:fixed;inset:0;background:#0009;display:flex;align-items:center;
        justify-content:center;z-index:9}
 #modal .box{background:var(--card);border:1px solid var(--line);border-radius:10px;
             padding:14px;width:min(880px,92vw);max-height:86vh;display:flex;
             flex-direction:column;gap:9px}
 #modal textarea{flex:1;min-height:380px;background:var(--card2);color:var(--fg);
                 border:1px solid var(--line);border-radius:6px;padding:9px;
                 font:12.5px/1.5 ui-monospace,Consolas,monospace;resize:vertical}
 [hidden]{display:none!important}
</style>

<header>
  <b>Write-up fill-in</b>
  <span class="pill" id="prog">—</span>
  <div class="bar"><i id="barfill"></i></div>
  <span class="sp"></span>
  <span class="pill warn">no draft text · no model calls · you type every word</span>
  <span class="pill" id="saved">—</span>
  <button id="tglrules">rules ▾</button>
</header>

<div id="rules" class="short">
  <ol id="rulelist"></ol>
  <div class="qs" id="qlist"></div>
</div>

<main>
  <nav id="rail"></nav>

  <section id="mid">
    <div id="crumb"></div>
    <div id="lock" hidden></div>
    <div id="restore" hidden></div>
    <div id="facts"></div>
    <div class="factbar">
      <span class="pill" id="slotid">—</span>
      <span class="pill" id="srcline">—</span>
      <span class="sp"></span>
      <button id="copysec">copy section for check</button>
    </div>
    <div id="prompt"></div>
    <textarea id="ta" spellcheck="true"
      placeholder="your words only — the tool has no draft text to offer"></textarea>
    <div id="ctl">
      <button class="primary" id="save">Save</button>
      <button class="primary" id="savenext">Save &amp; next</button>
      <button id="prev">← prev</button>
      <button id="next">next →</button>
      <button id="unfilled">next unfilled</button>
      <span class="sp"></span>
      <span class="pill" id="wc">0 words</span>
      <span class="pill" id="seccap" hidden>—</span>
    </div>
  </section>

  <aside id="ref">
    <div id="tabs"></div>
    <div id="reftools">
      <input type="text" id="q" placeholder="search this tab">
      <span class="pill" id="qn">—</span>
      <input type="text" id="dec" placeholder="#N" hidden>
    </div>
    <div id="refbody"><div class="note">pick a tab — nothing is loaded until you do</div></div>
  </aside>
</main>

<div id="modal" hidden><div class="box">
  <b id="mtitle">section export</b>
  <textarea id="mtext" readonly></textarea>
  <div style="display:flex;gap:8px">
    <button class="primary" id="mcopy">copy to clipboard</button>
    <button id="mclose">close</button>
    <span class="sp"></span><span class="pill" id="mnote">plain text, for a numbers check</span>
  </div>
</div></div>

<script>
let IDX=null, SLOTS=[], POS=0, CUR=null, DIRTY=false, EXEC_OK=null, TAB=null, RAW="";

const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const words=s=>(s.trim().match(/\S+/g)||[]).length;
const key=id=>'writeup_fill:'+id;

async function jget(u){const r=await fetch(u); if(!r.ok) throw new Error(u+' -> '+r.status);
  return await r.json();}

/* ------------------------------------------------------------------ boot */
async function boot(){
  IDX=await jget('/api/index');
  $('rulelist').innerHTML=IDX.style.rules.map((r,i)=>
    '<li><b>'+(i+1)+'.</b> '+r+'</li>').join('');
  $('qlist').innerHTML=IDX.style.questions.map(q=>'<span>'+q+'</span>').join('');
  $('tabs').innerHTML=IDX.references.map(t=>
    '<button data-tab="'+esc(t.name)+'">'+esc(t.title)+'</button>').join('');
  document.querySelectorAll('#tabs button').forEach(b=>
    b.onclick=()=>loadRef(b.dataset.tab));
  SLOTS=IDX.slots;
  POS=Math.max(0,SLOTS.findIndex(s=>!s.filled));
  if(POS<0)POS=0;
  paintRail(); await load();
}

function paintRail(){
  $('rail').innerHTML=IDX.sections.map(s=>{
    const cur=CUR&&CUR.section_index===s.index;
    const cls=['sec']; if(cur)cls.push('on');
    if(!s.n_slots)cls.push('noslot');
    else if(s.n_filled===s.n_slots)cls.push('done');
    if(s.is_exec)cls.push('exec');
    return '<div class="'+cls.join(' ')+'" data-sec="'+s.index+'">'
      +'<span class="n">'+(s.n_slots?s.n_filled+'/'+s.n_slots:'—')+'</span>'
      +'<span class="t">'+esc(s.title)+'</span></div>';}).join('');
  document.querySelectorAll('#rail .sec').forEach(d=>d.onclick=()=>{
    const i=SLOTS.findIndex(s=>s.section_index===+d.dataset.sec);
    if(i>=0)go(i);});
  const f=IDX.totals.filled, n=IDX.totals.slots;
  $('prog').textContent=f+' / '+n+' slots filled';
  $('barfill').style.width=(n?100*f/n:0)+'%';
}

/* ------------------------------------------------------------------ slot */
async function load(){
  const s=SLOTS[POS];
  CUR=await jget('/api/slot/'+encodeURIComponent(s.id));
  $('crumb').innerHTML='<b>'+esc(CUR.section_title)+'</b><br>'+esc(CUR.label)
    +' — slot '+(CUR.index_in_section)+' of '+CUR.section_slots;
  $('slotid').textContent=CUR.id;
  $('srcline').textContent='template line '+CUR.template_line;
  $('facts').innerHTML=CUR.facts_html||'<p class="note">no facts block above this slot</p>';
  $('facts').scrollTop=0;
  $('prompt').innerHTML=CUR.prompt_html||'';
  $('ta').value=CUR.text||'';
  DIRTY=false; EXEC_OK=null;
  paintLock(); paintWc(); paintRail(); restoreOffer();
  $('saved').textContent=CUR.updated_utc?('saved '+CUR.updated_utc):'never saved';
  if(!$('ta').disabled)$('ta').focus();
}

function paintLock(){
  const L=CUR.exec_lock;
  if(!CUR.is_exec||!L.locked){$('lock').hidden=true;$('ta').disabled=false;return;}
  $('lock').hidden=false;
  if(EXEC_OK===CUR.section_index){$('ta').disabled=false;
    $('lock').innerHTML='<b>write this last</b> — '+L.others_unfilled
      +' other slots are still empty. Editing unlocked for this section.';
    return;}
  $('ta').disabled=true;
  $('lock').innerHTML='<b>write this last</b> — '+L.others_unfilled
    +' other slots are still empty. The executive summary is written inside the +2h '
    +'window, after every other section is finished and numbers-checked. '
    +'<button id="unlock">edit anyway</button>';
  $('unlock').onclick=()=>{EXEC_OK=CUR.section_index;paintLock();$('ta').focus();};
}

function paintWc(){
  const w=words($('ta').value);
  $('wc').textContent=w+(w===1?' word':' words');
  if(!CUR.is_exec){$('seccap').hidden=true;return;}
  const other=CUR.section_words-CUR.word_count;
  const tot=other+w;
  $('seccap').hidden=false;
  $('seccap').textContent='section '+tot+' / '+CUR.exec_limit+' words';
  $('seccap').className='pill '+(tot>CUR.exec_limit?'bad':'ok');
}

function restoreOffer(){
  let stash=null;
  try{stash=localStorage.getItem(key(CUR.id));}catch(e){}
  if(stash!==null&&stash!==(CUR.text||'')&&stash.trim()){
    $('restore').hidden=false;
    $('restore').innerHTML='unsaved text from this browser is different from the saved '
      +'copy ('+words(stash)+' words vs '+words(CUR.text||'')+'). '
      +'<button id="dorestore">put it back in the box</button> '
      +'<button id="dropstash">discard it</button>';
    $('dorestore').onclick=()=>{$('ta').value=stash;DIRTY=true;paintWc();
      $('restore').hidden=true;};
    $('dropstash').onclick=()=>{try{localStorage.removeItem(key(CUR.id));}catch(e){}
      $('restore').hidden=true;};
  }else{$('restore').hidden=true;}
}

$('ta').oninput=()=>{DIRTY=true;paintWc();
  try{localStorage.setItem(key(CUR.id),$('ta').value);}catch(e){}};

async function save(){
  const body={slot_id:CUR.id,text:$('ta').value};
  const r=await fetch('/api/save',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!r.ok){$('saved').textContent='SAVE FAILED';$('saved').className='pill bad';return false;}
  const d=await r.json();
  IDX.sections=d.sections; IDX.totals=d.totals; SLOTS=d.slots;
  CUR.text=body.text; CUR.word_count=d.slot.word_count;
  CUR.section_words=d.section_words; CUR.updated_utc=d.slot.updated_utc;
  CUR.exec_lock=d.exec_lock;
  DIRTY=false;
  try{localStorage.removeItem(key(CUR.id));}catch(e){}
  $('saved').textContent='saved '+d.slot.updated_utc; $('saved').className='pill ok';
  $('restore').hidden=true;
  paintRail(); paintWc();
  return true;
}

async function go(i){
  if(DIRTY&&!confirm('This slot has unsaved changes. Leave without saving?'))return;
  POS=Math.max(0,Math.min(SLOTS.length-1,i)); await load();
}

$('save').onclick=save;
$('savenext').onclick=async()=>{if(await save()&&POS<SLOTS.length-1){POS++;await load();}};
$('prev').onclick=()=>go(POS-1);
$('next').onclick=()=>go(POS+1);
$('unfilled').onclick=()=>{const i=SLOTS.findIndex(s=>!s.filled);
  if(i<0){$('saved').textContent='every slot has text';return;}go(i);};
$('tglrules').onclick=()=>$('rules').classList.toggle('short');
window.addEventListener('beforeunload',e=>{if(DIRTY){e.preventDefault();e.returnValue='';}});
document.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&e.key==='s'){e.preventDefault();save();}
  if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();$('savenext').click();}});

/* ------------------------------------------------------------- reference */
async function loadRef(name){
  TAB=name;
  document.querySelectorAll('#tabs button').forEach(b=>
    b.classList.toggle('on',b.dataset.tab===name));
  $('dec').hidden=(name!=='decisions');
  $('refbody').innerHTML='<div class="note">loading…</div>';
  let d;
  try{d=await jget('/api/reference?tab='+encodeURIComponent(name)
      +'&slot='+encodeURIComponent(CUR?CUR.id:''));}
  catch(err){$('refbody').innerHTML='<div class="note">'+esc(String(err))+'</div>';return;}
  RAW=(d.note?'<div class="note">'+esc(d.note)+'</div>':'')+d.html;
  $('refbody').innerHTML=RAW;
  $('refbody').scrollTop=0;
  if(name==='decisions')tagDecisions();
  if($('q').value.trim())runSearch();
  else $('qn').textContent=d.path||'—';
}

function tagDecisions(){
  $('refbody').querySelectorAll('table tr').forEach(tr=>{
    const c=tr.querySelector('td'); if(!c)return;
    const m=(c.textContent||'').trim().match(/^(\d+)$/);
    if(m)tr.id='dec-'+m[1];});
}
$('dec').onkeydown=e=>{
  if(e.key!=='Enter')return;
  const n=($('dec').value||'').replace(/[^0-9]/g,'');
  if(!n)return;
  const rows=$('refbody').querySelectorAll('#dec-'+n);
  $('refbody').querySelectorAll('tr.hit').forEach(t=>t.classList.remove('hit'));
  if(!rows.length){$('qn').textContent='no row '+n;return;}
  rows.forEach(t=>t.classList.add('hit'));
  rows[0].scrollIntoView({block:'center'});
  $('qn').textContent='row '+n;
};

function clearMarks(){$('refbody').innerHTML=RAW; if(TAB==='decisions')tagDecisions();}
function runSearch(){
  const q=$('q').value.trim();
  clearMarks();
  if(!q){$('qn').textContent='—';return;}
  const root=$('refbody'), needle=q.toLowerCase();
  const walk=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
  const targets=[]; let node;
  while((node=walk.nextNode())){
    if(node.parentElement.closest('script,style'))continue;
    if(node.nodeValue.toLowerCase().includes(needle))targets.push(node);}
  let n=0, first=null;
  targets.forEach(t=>{
    const parts=t.nodeValue.split(new RegExp('('+q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','ig'));
    const frag=document.createDocumentFragment();
    parts.forEach(p=>{
      if(p.toLowerCase()===needle){const m=document.createElement('mark');
        m.textContent=p;frag.appendChild(m);n++;if(!first)first=m;}
      else frag.appendChild(document.createTextNode(p));});
    t.parentNode.replaceChild(frag,t);});
  $('qn').textContent=n+' hit'+(n===1?'':'s');
  if(first)first.scrollIntoView({block:'center'});
}
let qt=null;
$('q').oninput=()=>{clearTimeout(qt);qt=setTimeout(runSearch,180);};

/* ---------------------------------------------------------------- export */
$('copysec').onclick=async()=>{
  const d=await jget('/api/export?section='+CUR.section_index);
  $('mtitle').textContent='section '+CUR.section_index+' — '+CUR.section_title;
  $('mtext').value=d.text; $('modal').hidden=false;
  $('mtext').focus(); $('mtext').select();
};
$('mclose').onclick=()=>{$('modal').hidden=true;};
$('mcopy').onclick=async()=>{
  try{await navigator.clipboard.writeText($('mtext').value);$('mnote').textContent='copied';}
  catch(e){$('mtext').select();document.execCommand&&document.execCommand('copy');
    $('mnote').textContent='select-all + Ctrl-C';}
};
document.addEventListener('keydown',e=>{if(e.key==='Escape')$('modal').hidden=true;});

boot();
</script>
"""
