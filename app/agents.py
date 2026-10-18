"""The ARQON agent pipeline.

  1. Intake agent     (Gemini)  complaint text -> structured facts
  2. Evidence agent   (Gemini)  timeline -> break point, proposed classification, reasoning with evidence IDs
  3. Rules engine     (code)    facts + evidence -> liability, amounts, rules, missing information
  4. Verifier agent   (code)    checks every cited ID exists and that AI and rules agree
  5. Drafter agent    (Gemini)  decision -> customer letter with evidence annex
  6. Officer          (human)   approves or overrides (see main.py)

Every Gemini step has a deterministic fallback so the demo never breaks.
"""
from __future__ import annotations

import json
import re
import time
from typing import Literal

from pydantic import BaseModel, Field

from . import llm, timeline as tl
from .rules_engine import RULES, evaluate, rule_text

CLASS_ENUM = Literal["BANK_NEGLIGENCE", "THIRD_PARTY_BREACH", "CUSTOMER_NEGLIGENCE", "NOT_FRAUD", "UNDETERMINED"]


# ---------------------------------------------------------------- schemas
class IntakeOut(BaseModel):
    amount_claimed: int = Field(description="Total amount the customer says was lost, in rupees")
    fraud_date: str = Field(description="Date of the fraud as YYYY-MM-DD if stated, else empty")
    reported_to_1930: bool = Field(description="Customer says they reported to 1930 or cybercrime.gov.in")
    ncrp_reference: str = Field(description="1930/NCRP reference if given, else empty")
    shared_credentials: bool = Field(description="Customer admits sharing or entering OTP/PIN/password with a third party or fake page")
    installed_remote_app: bool = Field(description="Customer installed a screen-sharing or remote access app at someone's request")
    clicked_phishing_link: bool = Field(description="Customer opened a suspicious link and entered details")
    denies_sharing: bool = Field(description="Customer explicitly denies sharing any credentials")
    summary: str = Field(description="One-sentence neutral summary of the complaint")


class EvidenceOut(BaseModel):
    break_point_event_id: str
    proposed_classification: CLASS_ENUM
    reasoning: str = Field(description="3-5 sentences; every factual claim must cite an event ID in square brackets")
    key_evidence_ids: list[str]
    red_flags: list[str]
    questions_for_officer: list[str]
    response_to_officer: str = Field(default="", description="Only when an officer challenge is given: 1-3 sentences answering it directly, with citations")


# ---------------------------------------------------------------- 1. intake
INTAKE_SYS = (
    "You are the intake agent of a bank's fraud-claims desk in India. Extract facts from a customer's complaint. "
    "Do not infer anything the customer did not say. Return JSON only."
)


def _intake_fallback(text: str) -> dict:
    t = text.lower()
    amounts = [int(x.replace(",", "")) for x in re.findall(r"rs\.?\s*([\d,]{4,})", t)]
    ref = re.search(r"(ncrp-[\w-]+|1930-[\w-]+)", text, re.I)
    return {
        "amount_claimed": sum(amounts) if amounts else 0,
        "fraud_date": "",
        "reported_to_1930": bool(re.search(r"1930|cybercrime|cyber crime portal|ncrp", t)) and "not filed" not in t,
        "ncrp_reference": ref.group(1) if ref else "",
        "shared_credentials": bool(re.search(r"read out the otp|told .* otp|shared (the|my) otp|entered the otp", t)),
        "installed_remote_app": bool(re.search(r"install(ed)? an app|screen.?shar|anydesk|remote", t)),
        "clicked_phishing_link": bool(re.search(r"opened the link|clicked|link and", t)),
        "denies_sharing": bool(re.search(r"never shared|did not share|not share any", t)),
        "summary": text[:160] + ("..." if len(text) > 160 else ""),
    }


def intake(case: dict) -> dict:
    prompt = f"Complaint received {case['received_on']} from {case['customer']}:\n\"\"\"{case['complaint_text']}\"\"\""
    try:
        data, meta = llm.generate_json(INTAKE_SYS, prompt, IntakeOut)
        return {"data": data, "source": "gemini", "meta": meta}
    except Exception as exc:
        print(f"[agents] Gemini call failed, using fallback: {exc!r}"[:600])
        return {"data": _intake_fallback(case["complaint_text"]), "source": "fallback", "meta": {"reason": str(exc)[:120]}}


# ---------------------------------------------------------------- 2. evidence
EVIDENCE_SYS = (
    "You are a senior fraud investigator at an Indian bank. You are given a chronological evidence timeline for a "
    "disputed digital transaction, the customer's extracted statements, and the RBI liability categories. "
    "Identify the break point (the first event where the customer lost control or the system failed), propose a "
    "liability category, and explain your reasoning. Cite event IDs in square brackets for every factual claim, "
    "e.g. [C1001-E02]. Never invent an event ID. If evidence is missing or contradictory, say so and propose UNDETERMINED. "
    "Categories: BANK_NEGLIGENCE (bank system or process failure), THIRD_PARTY_BREACH (telecom, payment aggregator or "
    "other third party compromised, customer not at fault), CUSTOMER_NEGLIGENCE (customer shared credentials, installed "
    "remote-access app, used phishing page, ignored warnings), NOT_FRAUD (customer's own genuine transaction), UNDETERMINED."
)


def _compact_timeline(t: dict) -> list[dict]:
    return [{"id": e["event_id"], "ts": e["ts"], "type": e["type"], "source": e["source"],
             "summary": e["summary"], "attrs": e["attrs"]} for e in t["events"]]


CHALLENGE_SYS = (
    " A human case officer has challenged your previous analysis (given as previous_analysis and officer_challenge). "
    "Answer the challenge directly in response_to_officer. Change your conclusion only if the evidence supports it; "
    "do not agree just because the officer asked. Cite event IDs for every claim."
)


def evidence(case: dict, timeline: dict, facts: dict, challenge: dict | None = None) -> dict:
    payload = {
        "case_id": case["case_id"], "account_type": case["account_type"],
        "customer_statements": facts, "timeline": _compact_timeline(timeline),
    }
    if challenge:
        payload["previous_analysis"] = challenge.get("previous")
        payload["officer_challenge"] = challenge.get("question")
    prompt = json.dumps(payload, ensure_ascii=False, default=str)
    try:
        data, meta = llm.generate_json(EVIDENCE_SYS + (CHALLENGE_SYS if challenge else ""), prompt, EvidenceOut)
        return {"data": data, "source": "gemini", "meta": meta}
    except Exception as exc:
        print(f"[agents] Gemini call failed, using fallback: {exc!r}"[:600])
        engine_cls = evaluate(case, facts).classification
        bp = timeline.get("break_point") or {}
        ids = [e["event_id"] for e in timeline["events"] if e["severity"] in ("anomaly", "disputed")]
        reasoning = (f"Break point: {bp.get('summary', 'not identified')} [{bp.get('event_id', '')}], "
                     f"{bp.get('minutes_before_first_txn', '?')} minutes before the first disputed transaction "
                     f"[{bp.get('first_txn_id', '')}]." if bp else "No clear break point in the evidence.")
        return {"data": {"break_point_event_id": bp.get("event_id", ""), "proposed_classification": engine_cls,
                         "reasoning": reasoning, "key_evidence_ids": ids, "red_flags": [], "questions_for_officer": [],
                         "response_to_officer": ("Gemini is unavailable, so this could not be re-investigated. The rules engine "
                                                 "re-applied the same evidence and reached the same result.") if challenge else ""},
                "source": "fallback", "meta": {"reason": str(exc)[:120]}}


# ---------------------------------------------------------------- 4. verifier
def verify(case: dict, ev_out: dict, decision: dict) -> dict:
    ids = {e["event_id"] for e in case["events"]}
    text = ev_out["data"].get("reasoning", "")
    cited = set(re.findall(r"\[([A-Z]\d{4}-E\d{2})\]", text)) | set(ev_out["data"].get("key_evidence_ids", []))
    invalid = sorted(c for c in cited if c not in ids)
    agree = ev_out["data"].get("proposed_classification") == decision["classification"]
    issues = []
    if invalid:
        issues.append(f"AI cited {len(invalid)} event ID(s) that do not exist: {', '.join(invalid)}. Removed from the case file.")
    if not agree:
        issues.append(f"AI proposed {ev_out['data'].get('proposed_classification')} but the rules engine found "
                      f"{decision['classification']}. Officer review required.")
    valid_cited = sorted(c for c in cited if c in ids)
    return {
        "citations_checked": len(cited), "citations_valid": len(valid_cited), "invalid_ids": invalid,
        "agreement": agree, "issues": issues,
        "status": "verified" if (agree and not invalid) else "needs_review",
    }


# ---------------------------------------------------------------- 5. drafter
DRAFT_SYS = (
    "You draft formal, plain-English decision letters from an Indian bank to a customer about a digital fraud complaint. "
    "Use only the facts given. Quote the outcome and amounts exactly. Mention the applicable rule titles. "
    "List the evidence relied on by event ID in an 'Evidence annex' section. If information is missing, ask for it clearly. "
    "Keep it under 250 words. No markdown headings except 'Evidence annex'. Sign off as 'Grievance Redressal Cell'."
)

OUTCOME_LINES = {
    "ZERO_LIABILITY_REFUND": "We have accepted your claim in full. ₹{bank_pays:,} will be credited to your account, value-dated to the transaction date.",
    "COMPENSATION": "You are eligible for compensation of ₹{compensation:,} under the small-value fraud scheme. It will be paid within 5 calendar days.",
    "CUSTOMER_LIABLE": "Based on the evidence, the loss before you reported the fraud arose from customer negligence and is not reimbursable. ₹{bank_pays:,} debited after your report will be credited to you.",
    "BANK_POLICY_REVIEW": "The fraud was reported after the 5-day zero-liability window, so your claim will be decided under the bank's board-approved policy. An officer will contact you.",
    "PENDING_CUSTOMER_ACTION": "You may be eligible for compensation of ₹{compensation:,}. To complete your claim, please file a complaint on 1930 or cybercrime.gov.in by {by} and share the reference with us.",
    "INCOMPLETE_EVIDENCE": "We are still examining your complaint. We have not assigned any liability to you and will write again once our review is complete.",
    "REJECT_NOT_FRAUD": "Our records show the transaction was authorised from your registered device with biometric verification and a passed liveness check. We are therefore unable to treat it as fraudulent.",
}


def _template_letter(case, decision) -> str:
    a = decision["amounts"]
    by = decision["deadline"].get("customer_action", {}).get("by", "")
    line = OUTCOME_LINES[decision["outcome"]].format(bank_pays=a.get("bank_pays") or 0, compensation=a.get("compensation") or 0, by=by)
    rules = "; ".join(rule_text(r)["title"] for r in decision["rules_applied"])
    ev_ids = sorted({i for f in decision["findings"] for i in f["evidence"]})
    return (f"Dear {case['customer']},\n\nRe: Your complaint received on {case['received_on']} (Case {case['case_id']})\n\n"
            f"{line}\n\nRules applied: {rules}.\n\nEvidence annex: {', '.join(ev_ids)}\n\n"
            f"If you are not satisfied, you may approach the RBI Ombudsman via cms.rbi.org.in.\n\nGrievance Redressal Cell")


def draft(case: dict, decision: dict, instruction: str = "") -> dict:
    payload = {
        "customer": case["customer"], "case_id": case["case_id"], "received_on": case["received_on"],
        "outcome": decision["outcome"], "amounts": decision["amounts"], "deadline": decision["deadline"],
        "rules": [rule_text(r)["title"] for r in decision["rules_applied"]],
        "findings": [{"check": f["check"], "result": f["result"], "detail": f["detail"], "evidence": f["evidence"]} for f in decision["findings"]],
        "missing": decision["missing"], "required_outcome_sentence": OUTCOME_LINES[decision["outcome"]],
    }
    if instruction:
        payload["officer_instruction"] = instruction + " (Follow it unless it changes the outcome or amounts, which are fixed.)"
    try:
        text, meta = llm.generate_text(DRAFT_SYS, json.dumps(payload, ensure_ascii=False, default=str))
        return {"text": text, "source": "gemini", "meta": meta}
    except Exception as exc:
        print(f"[agents] Gemini call failed, using fallback: {exc!r}"[:600])
        return {"text": _template_letter(case, decision), "source": "fallback", "meta": {"reason": str(exc)[:120]}}


# ---------------------------------------------------------------- officer challenge
def recheck(case: dict, result: dict, step: str, question: str) -> dict:
    """Officer asks an AI step to look again. The AI can change its analysis or wording, never the money:
    amounts always come from the deterministic rules engine."""
    if step == "letter":
        before = result["letter"]["text"]
        result["letter"] = draft(case, result["decision"], instruction=question)
        changed = result["letter"]["text"].strip() != before.strip()
        answer = ("Gemini redrafted the letter." if result["letter"]["source"] == "gemini"
                  else "Gemini is unavailable; the template letter was regenerated unchanged.")
        return {"answer": answer, "changed": changed, "source": result["letter"]["source"]}
    prev = result["evidence"]["data"]
    ev = evidence(case, result["timeline"], result["intake"]["data"],
                  challenge={"previous": {k: prev.get(k) for k in ("proposed_classification", "reasoning")}, "question": question})
    result["evidence"] = ev
    result["verification"] = {**verify(case, ev, result["decision"]), "source": "code"}
    changed = ev["data"].get("proposed_classification") != prev.get("proposed_classification")
    return {"answer": ev["data"].get("response_to_officer") or ev["data"].get("reasoning", ""), "changed": changed,
            "before": prev.get("proposed_classification"), "after": ev["data"].get("proposed_classification"), "source": ev["source"]}


# ---------------------------------------------------------------- pipeline
def run(case: dict) -> dict:
    trace = []

    def step(name, fn):
        t0 = time.time()
        out = fn()
        src = out.get("source", "code") if isinstance(out, dict) else "code"
        trace.append({"agent": name, "source": src, "ms": int((time.time() - t0) * 1000)})
        return out

    timeline = step("Timeline builder", lambda: {**tl.build(case), "source": "code"})
    intake_out = step("Intake agent", lambda: intake(case))
    facts = intake_out["data"]
    ev_out = step("Evidence agent", lambda: evidence(case, timeline, facts))
    decision = step("Rules engine", lambda: {**evaluate(case, facts).to_dict(), "source": "code"})
    verification = step("Verifier", lambda: {**verify(case, ev_out, decision), "source": "code"})
    letter = step("Drafter agent", lambda: draft(case, decision))

    return {
        "case_id": case["case_id"], "llm_mode": llm.mode(), "timeline": timeline, "intake": intake_out,
        "evidence": ev_out, "decision": decision, "verification": verification, "letter": letter,
        "rules": {r["id"]: r for r in RULES["rules"]}, "trace": trace,
    }
