"""ARQON API: AI case officer for RBI digital-fraud compensation claims."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agents, llm, store
from .rules_engine import RULES, evaluate

app = FastAPI(title="ARQON", version="1.0")
STATIC = Path(__file__).resolve().parent / "static"
_cache: dict[str, dict] = {}


@app.get("/api/health")
def health():
    return {"ok": True, "llm_mode": llm.mode(), "model": llm.MODEL, "data_source": store.data_source(),
            "decision_store": store.decision_store()}


@app.get("/api/rules")
def rules():
    return RULES


@app.get("/api/cases")
def cases():
    out = []
    for c in store.list_cases():
        txns = [e for e in c["events"] if e["type"] == "TXN" and e["attrs"].get("disputed")]
        received = date.fromisoformat(c["received_on"])
        days_left = 45 - (date.fromisoformat(c["as_of"]) - received).days
        decided = store.get_decisions(c["case_id"])
        status = decided[-1]["action"].upper() if decided else ("ANALYSED" if c["case_id"] in _cache else "NEW")
        out.append({"case_id": c["case_id"], "customer": c["customer"], "segment": c["segment"],
                    "amount": sum(t["attrs"]["amount"] for t in txns), "received_on": c["received_on"],
                    "days_left": days_left, "status": status, "story": c["story"],
                    "outcome": _cache.get(c["case_id"], {}).get("decision", {}).get("outcome")})
    return out


@app.get("/api/cases/{case_id}")
def case(case_id: str):
    c = store.get_case(case_id)
    if not c:
        raise HTTPException(404, "Case not found")
    return {k: v for k, v in c.items() if k != "expected"}


@app.post("/api/cases/{case_id}/analyze")
def analyze(case_id: str, refresh: bool = False):
    if case_id in _cache and not refresh:
        return {**_cache[case_id], "cached": True, "decisions": store.get_decisions(case_id)}
    c = store.get_case(case_id)
    if not c:
        raise HTTPException(404, "Case not found")
    result = agents.run(c)
    result["case"] = {k: v for k, v in c.items() if k not in ("events", "expected")}
    _cache[case_id] = result
    return {**result, "cached": False, "decisions": store.get_decisions(case_id)}


class DecisionIn(BaseModel):
    action: str                 # approve | override | request_info
    officer: str = "Officer"
    outcome: str | None = None  # required for override
    note: str = ""
    letter: str = ""
    resolved_items: list[str] = []  # missing-information items the officer marked received or waived


@app.post("/api/cases/{case_id}/decision")
def decide(case_id: str, body: DecisionIn):
    if case_id not in _cache:
        raise HTTPException(400, "Analyse the case first")
    if body.action not in ("approve", "override", "request_info"):
        raise HTTPException(400, "Unknown action")
    if body.action == "override" and (not body.outcome or not body.note.strip()):
        raise HTTPException(400, "Override needs a new outcome and a reason")
    ai = _cache[case_id]
    open_items = [m["item"] for m in ai["decision"]["missing"] if m["item"] not in body.resolved_items]
    if body.action == "approve" and open_items:
        raise HTTPException(400, "Resolve or waive all missing information before approving: " + "; ".join(open_items))
    rec = store.save_decision(case_id, {
        "action": body.action, "officer": body.officer, "note": body.note, "resolved_items": body.resolved_items,
        "ai_outcome": ai["decision"]["outcome"], "final_outcome": body.outcome or ai["decision"]["outcome"],
        "letter": body.letter or ai["letter"]["text"],
    })
    return {"saved": rec, "decisions": store.get_decisions(case_id)}


@app.get("/api/evals")
def evals(live: bool = False):
    """Score the pipeline against the 8 labelled cases. live=true re-runs Gemini; default uses cached runs."""
    rows = []
    for c in store.list_cases():
        cid = c["case_id"]
        res = _cache.get(cid) if not live else None
        if res is None:
            res = agents.run(store.get_case(cid))
            res["case"] = {k: v for k, v in c.items() if k not in ("events", "expected")}
            _cache[cid] = res
        exp, d = c["expected"], res["decision"]
        amt_ok = (exp["bank_pays"] == d["amounts"]["bank_pays"]) and (exp["compensation"] == d["amounts"]["compensation"])
        rows.append({
            "case_id": cid, "story": c["story"],
            "expected": exp, "got": {"classification": d["classification"], "outcome": d["outcome"],
                                      "bank_pays": d["amounts"]["bank_pays"], "compensation": d["amounts"]["compensation"]},
            "outcome_correct": exp["outcome"] == d["outcome"] and exp["classification"] == d["classification"],
            "amount_correct": amt_ok,
            "ai_agrees": res["verification"]["agreement"],
            "ai_classification_correct": (res["evidence"]["data"].get("proposed_classification") == exp["classification"])
                                         if res["evidence"]["source"] == "gemini" else None,
            "citations_valid": res["verification"]["citations_valid"], "citations_checked": res["verification"]["citations_checked"],
            "intake_source": res["intake"]["source"], "evidence_source": res["evidence"]["source"],
        })
    n = len(rows)
    ai_rows = [r for r in rows if r["ai_classification_correct"] is not None]
    cit_total = sum(r["citations_checked"] for r in rows) or 1
    return {
        "llm_mode": llm.mode(), "cases": n,
        "decision_accuracy": sum(r["outcome_correct"] and r["amount_correct"] for r in rows) / n,
        "ai_classification_accuracy": (sum(bool(r["ai_classification_correct"]) for r in ai_rows) / len(ai_rows)) if ai_rows else None,
        "gemini_runs": len(ai_rows),
        "citation_validity": sum(r["citations_valid"] for r in rows) / cit_total,
        "rows": rows,
    }


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
