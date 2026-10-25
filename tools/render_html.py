"""Stage 4a: self-contained HTML explorer (no CDN, embedded data).

Reads  work/classification.json, work/overlaps.json
Writes output/explorer.html

Usage:  py tools/render_html.py --config migration.config.json [--title "Custom code explorer"]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import base_argparser, load_config, load_taxonomy, log, read_json  # noqa: E402

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--text:#1b1f24;--muted:#5b6470;--line:#dfe3e8;--accent:#1f6feb;--chip:#eef2f7;--ok:#1a7f37;--warn:#b35c00;--bad:#c0392b;--hl:#fff3bf}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1115;--panel:#171a21;--text:#e6e8eb;--muted:#9aa4b2;--line:#2a2f3a;--accent:#4c8dff;--chip:#232834;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--hl:#4a3f10}}
:root[data-theme=dark]{--bg:#0f1115;--panel:#171a21;--text:#e6e8eb;--muted:#9aa4b2;--line:#2a2f3a;--accent:#4c8dff;--chip:#232834;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--hl:#4a3f10}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif}
header{padding:16px;border-bottom:1px solid var(--line);background:var(--panel);position:sticky;top:0;z-index:5}
h1{font-size:18px;margin:0 0 8px}.sub{color:var(--muted);font-size:12px}
.cards{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0}.card{background:var(--chip);border-radius:8px;padding:8px 12px;min-width:120px}
.card b{display:block;font-size:18px}.card span{color:var(--muted);font-size:12px}
.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center}select,input{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 8px;font:inherit}
input[type=search]{min-width:260px;flex:1}button{background:var(--chip);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 10px;cursor:pointer;font:inherit}
main{padding:16px;max-width:1500px;margin:0 auto}
details{border:1px solid var(--line);border-radius:8px;background:var(--panel);margin:6px 0}details>summary{padding:8px 12px;cursor:pointer;list-style:none;display:flex;gap:10px;align-items:center}
summary::-webkit-details-marker{display:none}summary:before{content:"▸";color:var(--muted);width:12px;display:inline-block}details[open]>summary:before{content:"▾"}
.lvl1>summary{font-weight:600;font-size:15px}.lvl2{margin-left:18px}.lvl3{margin-left:36px}.count{color:var(--muted);font-weight:normal;font-size:12px;margin-left:auto}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:5px 8px;border-top:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600;font-size:12px}
.obj{cursor:pointer}.obj:hover{background:var(--hl)}.chip{display:inline-block;background:var(--chip);border-radius:10px;padding:1px 7px;font-size:11px;margin-right:4px;white-space:nowrap}
.sys{background:var(--accent);color:#fff}.conf-hi{color:var(--ok)}.conf-mid{color:var(--warn)}.conf-lo{color:var(--bad)}
.ov-identical{background:var(--ok);color:#fff}.ov-diverged{background:var(--bad);color:#fff}.ov-similar{background:var(--warn);color:#fff}
.detail{display:none;background:var(--bg);padding:10px 14px;font-size:12.5px}.detail.open{display:block}.detail dt{color:var(--muted);margin-top:6px}.detail dd{margin:0 0 2px 0;word-break:break-word}
code{font-family:Consolas,Menlo,monospace;font-size:12px}.hidden{display:none}.mono{font-family:Consolas,Menlo,monospace}
footer{padding:16px;color:var(--muted);font-size:12px;text-align:center}
@media (max-width:700px){input[type=search]{min-width:100%}.lvl2{margin-left:6px}.lvl3{margin-left:12px}td:nth-child(5),th:nth-child(5){display:none}}
</style>
</head>
<body>
<header>
<h1>__TITLE__</h1>
<div class="sub">Generated __GENERATED__ · __NOBJ__ custom objects from __SYSTEMS__ · classification by SAP module / submodule / area</div>
<div class="cards" id="cards"></div>
<div class="filters">
 <input type="search" id="q" placeholder="search name, description, purpose, package, table…">
 <select id="view"><option value="module">group by SAP module</option><option value="process">group by business process</option></select>
 <select id="fProc"><option value="">all processes</option></select>
 <select id="fSys"><option value="">all systems</option></select>
 <select id="fType"><option value="">all object types</option></select>
 <select id="fMod"><option value="">all modules</option></select>
 <select id="fConf"><option value="">any confidence</option><option value="hi">≥ 0.8</option><option value="mid">0.6 – 0.8</option><option value="lo">&lt; 0.6</option></select>
 <select id="fOv"><option value="">any overlap</option><option value="identical">identical across systems</option><option value="diverged">diverged across systems</option><option value="similar">similar candidates</option><option value="none">single system only</option></select>
 <select id="fSrc"><option value="">any source</option><option value="heuristic">heuristic</option><option value="heuristic+propagation">propagation</option><option value="llm">LLM</option><option value="review">review</option><option value="missing">unclassified</option></select>
 <select id="fOut"><option value="">any outcome</option><option value="classified">classified</option><option value="needs_context">needs context</option><option value="shared_technical">shared technical</option><option value="extraction_failed">extraction failed</option><option value="pending">pending</option></select>
 <select id="fRev"><option value="">any review state</option><option value="proposed">proposed</option><option value="reviewed">reviewed</option><option value="rejected">rejected</option></select>
 <button id="expand">expand all</button><button id="collapse">collapse all</button><button id="theme">theme</button>
 <span class="sub" id="shown"></span>
</div>
</header>
<main id="tree"></main>
<footer>Tree: Module › Submodule › Area › Object. Click an object row for evidence, function modules and overlaps. Data embedded; works offline.</footer>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
const D=JSON.parse(document.getElementById('data').textContent);
const T={};D.taxonomy.forEach(n=>T[n.id]=n);
const name=id=>id?(T[id]?T[id].name:id):'';
const objs=D.objects;const ov=D.overlaps||{};
const $=s=>document.querySelector(s);
function fill(sel,vals){vals.forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;sel.appendChild(o)})}
fill($('#fSys'),[...new Set(objs.map(o=>o.system))].sort());
fill($('#fType'),[...new Set(objs.map(o=>o.type))].sort());
fill($('#fMod'),[...new Set(objs.map(o=>o.module))].sort().map(m=>m));
const P=D.processes;const PM={};const PG={};if(P){P.modules.forEach(m=>PM[m.id]=m);P.groups.forEach(g=>PG[g.name]=g.id)}
if(P){const used=[...new Set(objs.flatMap(o=>(o.process||[]).map(p=>p.process)))].sort();used.forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v+' '+(PM[v]?PM[v].name:'');$('#fProc').appendChild(o)})}else{$('#view').disabled=true;$('#fProc').disabled=true}
const plabel=id=>PM[id]?(PM[id].group+' › '+PM[id].name):id;
function confCls(c){return c>=0.8?'conf-hi':c>=0.6?'conf-mid':'conf-lo'}
function ovStatus(o){const x=ov[o.key];return x?x.status:'none'}
function hay(o){return (o.name+' '+(o.description||'')+' '+(o.purpose||'')+' '+o.package+' '+(o.package_desc||'')+' '+(o.tables||[]).join(' ')+' '+(o.children||[]).join(' ')).toLowerCase()}
objs.forEach(o=>o._h=hay(o));
function matches(o,f){
 if(f.q&&!o._h.includes(f.q))return false;
 if(f.sys&&o.system!==f.sys)return false;
 if(f.type&&o.type!==f.type)return false;
 if(f.mod&&o.module!==f.mod)return false;
 if(f.conf==='hi'&&o.confidence<0.8)return false;
 if(f.conf==='mid'&&(o.confidence<0.6||o.confidence>=0.8))return false;
 if(f.conf==='lo'&&o.confidence>=0.6)return false;
 if(f.ov&&ovStatus(o)!==f.ov)return false;
 if(f.src&&o.source!==f.src)return false;
 if(f.out&&o.outcome!==f.out)return false;
 if(f.rev&&o.review_state!==f.rev)return false;
 if(f.proc&&!(o.process||[]).some(p=>p.process===f.proc))return false;
 return true}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function row(o){
 const x=ov[o.key];const ovc=x?`<span class="chip ov-${x.status}">${x.status}${x.systems&&x.systems.length?': '+x.systems.join(','):''}</span>`:'';
 const fm=o.children&&o.children.length?`<span class="chip">${o.children.length} FM</span>`:'';
 return `<tr class="obj" data-k="${esc(o.key)}"><td class="mono">${esc(o.type)}</td><td class="mono"><b>${esc(o.name)}</b> ${fm}${ovc}</td>
 <td>${esc(o.purpose||o.description||'')}</td><td><span class="chip sys">${esc(o.system)}</span><span class="mono">${esc(o.package)}</span></td>
 <td class="${confCls(o.confidence)}">${(o.confidence||0).toFixed(2)}<div class="sub">${esc(o.source)}</div></td></tr>
 <tr class="detailrow hidden" data-d="${esc(o.key)}"><td colspan="5"><div class="detail open">${detail(o)}</div></td></tr>`}
function detail(o){
 const x=ov[o.key];let s='<dl>';
 s+=`<dt>Key</dt><dd class="mono">${esc(o.key)}</dd>`;
 s+=`<dt>Classification</dt><dd>${esc(o.module)} ${esc(name(o.module))} › ${esc(o.submodule||'-')} ${esc(name(o.submodule))} › ${esc(o.area||'-')} ${esc(name(o.area))} &nbsp; (source ${esc(o.source)}${o.model?', '+esc(o.model):''}, confidence ${(o.confidence||0).toFixed(2)})</dd>`;
 if(o.description)s+=`<dt>Description</dt><dd>${esc(o.description)}</dd>`;
 if(o.package_desc)s+=`<dt>Package</dt><dd>${esc(o.package)} – ${esc(o.package_desc)}</dd>`;
 if(o.rationale)s+=`<dt>Rationale</dt><dd>${esc(o.rationale)}</dd>`;
 if(o.flags&&o.flags.length)s+=`<dt>Flags</dt><dd>${o.flags.map(f=>'<span class="chip">'+esc(f)+'</span>').join('')}</dd>`;
 if(o.secondary&&o.secondary.length)s+=`<dt>Also applies to</dt><dd>${o.secondary.map(x=>'<span class="chip">'+esc((x.area||x.submodule||x.module)+' ('+x.role+')')+'</span>'+(x.rationale?' '+esc(x.rationale):'')).join('<br>')}</dd>`;
 if(o.process&&o.process.length)s+=`<dt>Business process</dt><dd>${o.process.map(p=>'<span class="chip">'+esc(p.process+' '+p.role)+'</span> '+esc(plabel(p.process))+' <span class="sub">('+esc(p.basis||'')+(p.rationale?': '+esc(p.rationale):'')+')</span>').join('<br>')}</dd>`;
 s+=`<dt>Outcome / review</dt><dd>${esc(o.outcome)} · ${esc(o.review_state)}${o.reviewed_by?' by '+esc(o.reviewed_by):''}</dd>`;
 if(o.provenance&&(o.provenance.model||o.provenance.prompt_version))s+=`<dt>Provenance</dt><dd class="mono">${esc(o.provenance.model||'')} ${esc(o.provenance.prompt_version||'')} batch ${esc(o.provenance.batch||'-')} taxonomy ${esc(o.provenance.taxonomy_version||'')}</dd>`;
 if(o.heuristic&&o.heuristic.top&&o.heuristic.top.length)s+=`<dt>Heuristic candidates</dt><dd>${o.heuristic.top.map(t=>esc(t[0])+' ('+t[1]+')').join(', ')}${o.heuristic.module&&o.heuristic.module!==o.module?' <span class="chip ov-similar">differs from final</span>':''}</dd>`;
 if(o.evidence&&o.evidence.length)s+=`<dt>Evidence</dt><dd class="mono">${o.evidence.map(esc).join('<br>')}</dd>`;
 if(o.tables&&o.tables.length)s+=`<dt>Tables</dt><dd class="mono">${o.tables.map(esc).join(', ')}</dd>`;
 if(o.functions&&o.functions.length)s+=`<dt>Function calls</dt><dd class="mono">${o.functions.map(esc).join(', ')}</dd>`;
 if(o.children&&o.children.length)s+=`<dt>Function modules</dt><dd class="mono">${o.children.map(esc).join(', ')}</dd>`;
 if(o.uses&&o.uses.length)s+=`<dt>Uses custom objects</dt><dd class="mono">${o.uses.map(esc).join(', ')}</dd>`;
 if(o.used_by&&o.used_by.length)s+=`<dt>Used by custom objects</dt><dd class="mono">${o.used_by.map(esc).join(', ')}</dd>`;
 if(x){s+=`<dt>Overlap</dt><dd>${esc(x.status)}${x.systems&&x.systems.length?' in '+esc(x.systems.join(', ')):''}${x.similarity!=null?' (source similarity '+x.similarity+')':''}${x.similar_to?'<br>similar to: <span class="mono">'+x.similar_to.map(esc).join(', ')+'</span>':''}</dd>`}
 if(o.files&&o.files.length)s+=`<dt>Files</dt><dd class="mono">${o.files.map(esc).join('<br>')}</dd>`;
 return s+'</dl>'}
function render(){
 const f={q:$('#q').value.trim().toLowerCase(),sys:$('#fSys').value,type:$('#fType').value,mod:$('#fMod').value,conf:$('#fConf').value,ov:$('#fOv').value,src:$('#fSrc').value,out:$('#fOut').value,rev:$('#fRev').value,proc:$('#fProc').value};
 const vis=objs.filter(o=>matches(o,f));
 $('#shown').textContent=vis.length+' of '+objs.length+' objects shown';
 const byProcess=$('#view').value==='process'&&P;
 const tree={};
 if(byProcess){
  // group > process module > role ; an object appears once per process assignment
  vis.forEach(o=>{const ps=(o.process&&o.process.length)?o.process:[{process:'_none',role:'direct'}];ps.forEach(p=>{if(f.proc&&p.process!==f.proc)return;const g=p.process==='_none'?'UNASSIGNED':(PM[p.process]?PG[PM[p.process].group]:'?'),m=p.process,r=p.role;((tree[g]=tree[g]||{})[m]=tree[g][m]||{})[r]=(tree[g][m][r]||[]);tree[g][m][r].push(o)})});
 } else {
  vis.forEach(o=>{const m=o.module,s=o.submodule||'_',a=o.area||'_';((tree[m]=tree[m]||{})[s]=tree[m][s]||{})[a]=(tree[m][s][a]||[]);tree[m][s][a].push(o)});
 }
 const cnt=t=>Object.values(t).reduce((n,v)=>n+(Array.isArray(v)?v.length:cnt(v)),0);
 const anyFilter=Object.values(f).some(Boolean);
 const gname=id=>{if(!byProcess)return name(id);const g=(P.groups||[]).find(x=>x.id===id);return g?g.name:(id==='UNASSIGNED'?'no process assigned':'')};
 const sname=id=>byProcess?(PM[id]?PM[id].name:(id==='_none'?'':id)):name(id);
 const aname=id=>byProcess?'':name(id);
 let h='';
 Object.keys(tree).sort((a,b)=>(a==='UNKNOWN'||a==='UNASSIGNED')-(b==='UNKNOWN'||b==='UNASSIGNED')||a.localeCompare(b)).forEach(m=>{
  h+=`<details class="lvl1" ${anyFilter?'open':''}><summary>${esc(m)} <span class="sub">${esc(gname(m))}</span><span class="count">${cnt(tree[m])}</span></summary>`;
  Object.keys(tree[m]).sort((a,b)=>(a==='_')-(b==='_')||a.localeCompare(b)).forEach(s=>{
   const subOpen=anyFilter?'open':'';
   const wrapS=s!=='_';
   if(wrapS)h+=`<details class="lvl2" ${subOpen}><summary>${esc(s)} <span class="sub">${esc(sname(s))}</span><span class="count">${cnt(tree[m][s])}</span></summary>`;
   Object.keys(tree[m][s]).sort((a,b)=>(a==='_')-(b==='_')||(byProcess?['direct','supporting','context'].indexOf(a)-['direct','supporting','context'].indexOf(b):a.localeCompare(b))).forEach(a=>{
    const items=tree[m][s][a].sort((x,y)=>x.type.localeCompare(y.type)||x.name.localeCompare(y.name)||x.system.localeCompare(y.system));
    const wrapA=a!=='_';
    if(wrapA)h+=`<details class="lvl3" ${subOpen||byProcess?'open':''}><summary>${esc(byProcess?'role: '+a:a)} <span class="sub">${esc(aname(a))}</span><span class="count">${items.length}</span></summary>`;
    h+=`<table><thead><tr><th>Type</th><th>Object</th><th>Purpose</th><th>System / package</th><th>Conf.</th></tr></thead><tbody>${items.map(row).join('')}</tbody></table>`;
    if(wrapA)h+='</details>';
   });
   if(wrapS)h+='</details>';
  });
  h+='</details>';
 });
 $('#tree').innerHTML=h||'<p class="sub">No objects match the filters.</p>';
}
function cards(){
 const c=[['Objects',objs.length],['Systems',new Set(objs.map(o=>o.system)).size],['Packages',new Set(objs.map(o=>o.system+'|'+o.package)).size],
 ['Modules',new Set(objs.map(o=>o.module)).size],['Auto / heuristic',objs.filter(o=>o.source&&o.source.startsWith('heuristic')).length],['LLM classified',objs.filter(o=>o.source==='llm').length],
 ['Low confidence',objs.filter(o=>o.confidence<0.6).length],['Unclassified',objs.filter(o=>o.module==='UNKNOWN').length],
 ['Reviewed',objs.filter(o=>o.review_state==='reviewed').length],['Shared technical',objs.filter(o=>o.outcome==='shared_technical').length],
 ['Identical across systems',Object.values(ov).filter(x=>x.status==='identical').length],['Diverged across systems',Object.values(ov).filter(x=>x.status==='diverged').length]];
 $('#cards').innerHTML=c.map(([k,v])=>`<div class="card"><b>${v}</b><span>${k}</span></div>`).join('');
 const bySys={};objs.forEach(o=>bySys[o.system]=(bySys[o.system]||0)+1);
 $('#cards').innerHTML+=Object.entries(bySys).map(([k,v])=>`<div class="card"><b>${v}</b><span>${esc(k)}</span></div>`).join('');
}
document.addEventListener('click',e=>{const tr=e.target.closest('tr.obj');if(!tr)return;const d=document.querySelector(`tr.detailrow[data-d="${tr.dataset.k.replace(/"/g,'\\"')}"]`);if(d)d.classList.toggle('hidden')});
['#q','#view','#fProc','#fSys','#fType','#fMod','#fConf','#fOv','#fSrc','#fOut','#fRev'].forEach(s=>$(s).addEventListener('input',render));
$('#expand').onclick=()=>document.querySelectorAll('details').forEach(d=>d.open=true);
$('#collapse').onclick=()=>document.querySelectorAll('details').forEach(d=>d.open=false);
$('#theme').onclick=()=>{const r=document.documentElement;const cur=r.getAttribute('data-theme');r.setAttribute('data-theme',cur==='dark'?'light':'dark')};
cards();render();
})();
</script>
</body>
</html>
"""


def main(argv: Optional[List[str]] = None) -> int:
    ap = base_argparser(__doc__)
    ap.add_argument("--title", default="SAP custom code explorer")
    ap.add_argument("--systems", default=None, help="comma-separated system ids to include (default all); output becomes explorer_<ids>.html")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    tax = load_taxonomy(cfg.taxonomy_path)
    cls = read_json(cfg.classification_file)
    overlaps = read_json(cfg.overlaps_file).get("index", {}) if cfg.overlaps_file.exists() else {}
    only = {s.strip().upper() for s in args.systems.split(",") if s.strip()} if args.systems else None
    if only:
        cls["objects"] = [o for o in cls["objects"] if o["system"].upper() in only]
        cls["systems"] = [s for s in cls["systems"] if s["id"].upper() in only]

    objects = []
    for o in cls["objects"]:
        refs = o.get("refs", {}) or {}
        objects.append({
            "key": o["key"], "system": o["system"], "type": o["type"], "name": o["name"], "package": o["package"],
            "package_desc": o.get("package_desc", ""), "description": o.get("description", ""), "purpose": o.get("purpose", ""),
            "module": o["module"], "submodule": o.get("submodule"), "area": o.get("area"), "confidence": o.get("confidence", 0),
            "source": o.get("source", ""), "model": o.get("model", ""), "rationale": o.get("rationale", ""), "flags": o.get("flags", []),
            "secondary": o.get("secondary", []), "process": o.get("process", []), "outcome": o.get("outcome", "classified"),
            "review_state": o.get("review_state", "proposed"), "reviewed_by": o.get("reviewed_by", ""),
            "provenance": o.get("provenance", {}),
            "heuristic": {"module": (o.get("heuristic") or {}).get("module"), "top": (o.get("heuristic") or {}).get("top", [])},
            "evidence": o.get("evidence", [])[:10],
            "tables": list(refs.get("tables", {}))[:20], "functions": list(refs.get("functions", {}))[:15],
            "children": [c["name"] for c in o.get("children", [])][:60],
            "uses": o.get("uses", [])[:20], "used_by": o.get("used_by", [])[:20], "files": o.get("files", [])[:12], "loc": o.get("loc", 0),
        })
    data = {"generated": cls["generated"], "systems": cls["systems"],
            "taxonomy": [{"id": n["id"], "name": n["name"], "parent": n.get("parent")} for n in tax.raw["nodes"]],
            "processes": cls.get("process_catalog") or None,
            "objects": objects, "overlaps": overlaps}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    systems = ", ".join(f"{s['id']} ({s['company']})" if s.get("company") else s["id"] for s in cls["systems"])
    html = (TEMPLATE.replace("__TITLE__", args.title).replace("__GENERATED__", cls["generated"])
            .replace("__NOBJ__", str(len(objects))).replace("__SYSTEMS__", systems).replace("__DATA__", blob))
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.output_dir / ("explorer.html" if not only else f"explorer_{'_'.join(sorted(only))}.html")
    out.write_text(html, encoding="utf-8")
    mods = Counter(o["module"] for o in objects)
    log(f"explorer: {out} ({out.stat().st_size // 1024} KB); modules {dict(mods)}")
    print(f"EXPLORER_OK objects={len(objects)} file={out} size_kb={out.stat().st_size // 1024}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
