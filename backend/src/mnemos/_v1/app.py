"""FastAPI surface + a self-contained localhost inspector UI.

The UI is the point of this module. `EXPLAIN` output is the project's central
artifact, and a JSON blob in a terminal does not communicate it. The page puts the
naive prompt and the compiled bundle side by side and shows, for the same question,
what each one actually hands to the model.

No CDN, no build step: the HTML/CSS/JS is inline so `mnemosctl serve` works offline.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .baseline import NaiveContextBuilder
from .bench import (
    SYSTEM_PROMPT,
    _acl_leaked,
    _duplicate_waste,
    _outdated_present,
    _stale_present,
    build_corpus,
    demo_principal,
)
from .compiler import Budgets, ContextCompiler, ContextRequest, SectionSpec
from .core import Settings
from .dataset import MEMORY_QUESTION, ORG_ID, QUESTIONS
from .retrieval import RetrievalEngine

# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------


class _State:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store, self.embedder, self.tokenizer = build_corpus(settings)
        self.engine = RetrievalEngine(self.store, self.embedder, self.tokenizer)
        self.compiler = ContextCompiler(
            self.engine, self.embedder, self.tokenizer, settings
        )
        self.naive = NaiveContextBuilder(self.store, self.embedder, self.tokenizer)
        self.principal = demo_principal()


_state: _State | None = None


def get_state() -> _State:
    if _state is None:
        raise HTTPException(status_code=503, detail="corpus not initialised")
    return _state


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CompareRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    token_budget: int = Field(default=800, ge=100, le=32000)
    k: int = Field(default=12, ge=1, le=50)
    variant: str = Field(default="naive_prefilter")


class MemoryWrite(BaseModel):
    subject_id: str
    predicate: str
    object_text: str
    kind: str = "semantic"


def _metrics(prompt: str, tokens: int, budget: int) -> dict[str, Any]:
    return {
        "tokens": tokens,
        "budget": budget,
        "within_budget": tokens <= budget,
        "duplicate_waste": round(_duplicate_waste(prompt), 4),
        "acl_leak": _acl_leaked(prompt),
        "stale_memory": _stale_present(prompt),
        "outdated_document": _outdated_present(prompt),
    }


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def create_app(settings: Settings | None = None) -> FastAPI:
    global _state
    _state = _State(settings or Settings())

    app = FastAPI(
        title="Mnemos",
        version="0.1.0",
        description="Context is a compiled artifact, not a concatenated string.",
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, Any]:
        st = get_state()
        chunks, _ = st.store.all_chunks(ORG_ID)
        return {
            "status": "ok",
            "embedder": st.embedder.name,
            "chunks": len(chunks),
            "claims": len(st.store.naive_all_claims(ORG_ID)),
        }

    @app.get("/v1/questions")
    def questions() -> dict[str, Any]:
        return {
            "questions": [
                {"qid": q.qid, "query": q.query, "answer_key": q.answer_key}
                for q in [*QUESTIONS, MEMORY_QUESTION]
            ]
        }

    @app.get("/v1/memory")
    def memory() -> dict[str, Any]:
        """All claims, with belief state visible.

        Retracted claims are returned deliberately: the UI shows them struck
        through, which is what makes supersession legible rather than magical.
        """
        st = get_state()
        rows = st.store.naive_all_claims(ORG_ID)
        return {
            "claims": [
                {
                    "id": c.id,
                    "kind": str(c.kind),
                    "subject_id": c.subject_id,
                    "predicate": c.predicate,
                    "object_text": c.object_text,
                    "valid_from": c.valid_from.isoformat(),
                    "recorded_at": c.recorded_at.isoformat(),
                    "retracted_at": c.retracted_at.isoformat() if c.retracted_at else None,
                    "asserted": c.retracted_at is None,
                }
                for c in sorted(rows, key=lambda x: (x.predicate, x.valid_from))
            ]
        }

    @app.post("/v1/memory")
    def write_memory(body: MemoryWrite) -> dict[str, Any]:
        from .core import MemoryKind

        st = get_state()
        vec = st.embedder.encode([f"{body.predicate} {body.object_text}"])[0]
        result = st.store.write_claim(
            org_id=ORG_ID,
            kind=MemoryKind(body.kind),
            subject_id=body.subject_id,
            predicate=body.predicate,
            object_text=body.object_text,
            vector=vec,
            workspace_id="ws-platform",
        )
        return {
            "id": result.claim.id,
            "outcome": result.outcome,
            "superseded": result.superseded,
        }

    @app.post("/v1/context:compile")
    def compile_context(body: CompareRequest) -> JSONResponse:
        st = get_state()
        req = ContextRequest(
            principal=st.principal,
            query=body.query,
            budgets=Budgets(tokens=body.token_budget),
            sections=[
                SectionSpec("memory", floor_tokens=60,
                            ceil_tokens=max(200, body.token_budget // 5), priority=10),
                SectionSpec("documents", floor_tokens=0,
                            ceil_tokens=body.token_budget, priority=5),
            ],
            system_prompt=SYSTEM_PROMPT,
        )
        return JSONResponse(st.compiler.compile(req).to_dict())

    @app.post("/v1/compare")
    def compare(body: CompareRequest) -> dict[str, Any]:
        """Run both arms on one question and return prompts + metrics side by side."""
        st = get_state()

        naive = st.naive.build(
            principal=st.principal, query=body.query,
            token_budget=body.token_budget, k=body.k,
            system_prompt=SYSTEM_PROMPT, variant=body.variant,
        )
        req = ContextRequest(
            principal=st.principal,
            query=body.query,
            budgets=Budgets(tokens=body.token_budget),
            sections=[
                SectionSpec("memory", floor_tokens=60,
                            ceil_tokens=max(200, body.token_budget // 5), priority=10),
                SectionSpec("documents", floor_tokens=0,
                            ceil_tokens=body.token_budget, priority=5),
            ],
            system_prompt=SYSTEM_PROMPT,
        )
        bundle = st.compiler.compile(req)

        return {
            "query": body.query,
            "budget": body.token_budget,
            "naive": {
                "variant": naive.variant,
                "prompt": naive.prompt,
                "latency_ms": round(naive.latency_ms, 2),
                "truncated": naive.truncated,
                "metrics": _metrics(naive.prompt, naive.tokens_consumed, body.token_budget),
                "provenance": None,
            },
            "compiled": {
                "digest": bundle.digest,
                "prompt": bundle.prompt,
                "latency_ms": round(bundle.latency_ms, 2),
                "metrics": _metrics(bundle.prompt, bundle.tokens_consumed, body.token_budget),
                "manifest": [asdict(i) for i in bundle.manifest],
                "budget_report": bundle.budget_report,
                "explain": bundle.explain,
                "degradations": bundle.degradations,
            },
        }

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _INDEX_HTML

    return app


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

_INDEX_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mnemos — context compiler inspector</title>
<style>
:root{--bg:#0d1117;--panel:#161b22;--border:#30363d;--fg:#e6edf3;--muted:#8b949e;
--good:#3fb950;--bad:#f85149;--warn:#d29922;--accent:#58a6ff;--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
@media(prefers-color-scheme:light){:root{--bg:#fff;--panel:#f6f8fa;--border:#d0d7de;
--fg:#1f2328;--muted:#656d76;--good:#1a7f37;--bad:#cf222e;--warn:#9a6700;--accent:#0969da}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,sans-serif}
header{padding:18px 22px;border-bottom:1px solid var(--border)}
h1{margin:0;font-size:17px;letter-spacing:-.01em}
h1 span{color:var(--muted);font-weight:400}
.sub{color:var(--muted);font-size:12.5px;margin-top:4px}
main{padding:18px 22px;max-width:1500px}
.controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:16px}
input,select,button{background:var(--panel);color:var(--fg);border:1px solid var(--border);
border-radius:6px;padding:8px 11px;font-size:13.5px;font-family:inherit}
input[type=text]{flex:1;min-width:320px}
button{cursor:pointer;background:var(--accent);color:#fff;border-color:transparent;font-weight:600}
button:hover{filter:brightness(1.1)} button:disabled{opacity:.6;cursor:wait}
.presets{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px}
.presets button{background:var(--panel);color:var(--fg);border:1px solid var(--border);
font-weight:400;font-size:12px;padding:5px 9px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:1000px){.grid{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--border);border-radius:8px;overflow:hidden}
.card>h2{margin:0;padding:11px 14px;font-size:13px;border-bottom:1px solid var(--border);
display:flex;justify-content:space-between;align-items:center}
.card>h2 small{color:var(--muted);font-weight:400}
.body{padding:12px 14px}
pre{margin:0;font-family:var(--mono);font-size:11.5px;line-height:1.55;white-space:pre-wrap;
word-break:break-word;max-height:440px;overflow:auto}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.chip{font-size:11px;padding:3px 8px;border-radius:20px;border:1px solid var(--border);white-space:nowrap}
.chip.ok{color:var(--good);border-color:var(--good)}
.chip.bad{color:var(--bad);border-color:var(--bad)}
.chip.neutral{color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:11.5px}
th,td{text-align:left;padding:5px 7px;border-bottom:1px solid var(--border);vertical-align:top}
th{color:var(--muted);font-weight:600}
td.mono,th.mono{font-family:var(--mono)}
details{margin-top:10px} summary{cursor:pointer;color:var(--accent);font-size:12.5px;padding:4px 0}
mark{background:rgba(248,81,73,.22);color:inherit;border-bottom:1px solid var(--bad);padding:0 1px}
mark.good{background:rgba(63,185,80,.22);border-bottom-color:var(--good)}
.err{color:var(--bad);font-family:var(--mono);font-size:12px}
.legend{color:var(--muted);font-size:11.5px;margin-top:8px}
</style></head><body>
<header>
  <h1>Mnemos <span>— context is a compiled artifact, not a concatenated string</span></h1>
  <div class="sub">Same question, same corpus, same budget. Left: string concatenation. Right: compiled context bundle.</div>
</header>
<main>
  <div class="controls">
    <input type="text" id="q" placeholder="Ask something about the Northwind corpus…"
           value="How many days of unused leave can I carry over to next year?">
    <label style="color:var(--muted);font-size:12.5px">budget
      <input type="number" id="budget" value="800" min="100" max="32000" step="100" style="width:90px;min-width:0">
    </label>
    <label style="color:var(--muted);font-size:12.5px">k
      <input type="number" id="k" value="12" min="1" max="50" style="width:62px;min-width:0">
    </label>
    <select id="variant">
      <option value="naive_prefilter">naive + prefilter ACL</option>
      <option value="naive_postfilter">naive + postfilter ACL</option>
      <option value="naive">naive, no ACL</option>
    </select>
    <button id="run">Compile</button>
  </div>
  <div class="presets" id="presets"></div>
  <div id="err" class="err"></div>
  <div class="grid">
    <div class="card"><h2>Naive concatenated prompt <small id="nlat"></small></h2>
      <div class="body"><div class="chips" id="nchips"></div><pre id="nout"></pre></div></div>
    <div class="card"><h2>Compiled ContextBundle <small id="clat"></small></h2>
      <div class="body"><div class="chips" id="cchips"></div><pre id="cout"></pre>
        <div class="legend">Highlighted: <mark>obsolete / restricted / superseded</mark> content.</div>
        <details open><summary>Provenance manifest — every item, its source and the rule that admitted it</summary>
          <div id="manifest"></div></details>
        <details><summary>EXPLAIN — plan, allocator decisions, evictions</summary>
          <pre id="explain" style="max-height:420px"></pre></details>
      </div></div>
  </div>
</main>
<script>
const $=id=>document.getElementById(id);
let BAD=[];

fetch('/v1/questions').then(r=>r.json()).then(d=>{
  $('presets').innerHTML = d.questions.slice(0,10).map(q=>
    `<button data-q="${q.query.replace(/"/g,'&quot;')}">${q.qid}</button>`).join('');
  document.querySelectorAll('#presets button').forEach(b=>
    b.onclick=()=>{$('q').value=b.dataset.q; run();});
});

function esc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}

// Highlight the phrases that make a prompt wrong: obsolete policy figures,
// restricted payroll data, and the superseded memory value.
const MARKERS=["capped at ten working days","forfeited on 31 March",
 "after six continuous years of service","minimum of twelve days per calendar month",
 "home office allowance of 500 EUR","within thirty days of the date the expense was incurred",
 "internal Northwind rate of 0.30 EUR","green soak period of ten minutes",
 "maximum shift length of twenty four hours","one hour per page acknowledged",
 "exceeding two thousand lines may be declined","118,000 to 146,000 EUR",
 "149,000 to 188,000 EUR","us-west-2","Ignore all previous instructions"];

function hl(text){
  let out=esc(text);
  for(const m of MARKERS){
    const pat=esc(m).replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&').replace(/\\s+/g,'\\\\s+');
    out=out.replace(new RegExp(pat,'gi'),x=>`<mark>${x}</mark>`);
  }
  return out;
}

function chips(m,el){
  const c=[];
  c.push(`<span class="chip ${m.within_budget?'ok':'bad'}">${m.tokens}/${m.budget} tokens ${m.within_budget?'✓':'OVER'}</span>`);
  c.push(`<span class="chip ${m.duplicate_waste>0.05?'bad':'ok'}">dup ${(m.duplicate_waste*100).toFixed(1)}%</span>`);
  c.push(`<span class="chip ${m.outdated_document?'bad':'ok'}">${m.outdated_document?'obsolete policy present':'no obsolete policy'}</span>`);
  c.push(`<span class="chip ${m.stale_memory?'bad':'ok'}">${m.stale_memory?'superseded memory':'memory current'}</span>`);
  c.push(`<span class="chip ${m.acl_leak?'bad':'ok'}">${m.acl_leak?'RESTRICTED LEAK':'no ACL leak'}</span>`);
  el.innerHTML=c.join('');
}

async function run(){
  const btn=$('run'); btn.disabled=true; btn.textContent='Compiling…'; $('err').textContent='';
  try{
    const r=await fetch('/v1/compare',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({query:$('q').value,token_budget:+$('budget').value,
        k:+$('k').value,variant:$('variant').value})});
    if(!r.ok) throw new Error(await r.text());
    const d=await r.json();

    $('nout').innerHTML=hl(d.naive.prompt);
    $('cout').innerHTML=hl(d.compiled.prompt);
    $('nlat').textContent=d.naive.latency_ms+' ms · no manifest';
    $('clat').textContent=d.compiled.latency_ms+' ms · '+d.compiled.digest.slice(0,19);
    chips(d.naive.metrics,$('nchips'));
    chips(d.compiled.metrics,$('cchips'));

    const rows=d.compiled.manifest.map(i=>`<tr>
      <td>${i.section}</td><td class="mono">${i.source_kind}:${String(i.source_id).slice(0,8)}</td>
      <td>${esc(String((i.metadata&&i.metadata.document_title)||'memory'))}</td>
      <td class="mono">${i.operator_id}</td><td>${i.token_count}</td>
      <td>${i.trust_tier}</td><td class="mono">${i.acl_rule_id}</td></tr>`).join('');
    $('manifest').innerHTML=`<table><thead><tr><th>section</th><th>source</th><th>document</th>
      <th>operator</th><th>tok</th><th>tier</th><th>admitted by</th></tr></thead><tbody>${rows}</tbody></table>`;
    $('explain').textContent=JSON.stringify(d.compiled.explain,null,2);
  }catch(e){ $('err').textContent='Error: '+e.message; }
  finally{ btn.disabled=false; btn.textContent='Compile'; }
}
$('run').onclick=run;
$('q').addEventListener('keydown',e=>{if(e.key==='Enter')run();});
run();
</script></body></html>
"""
