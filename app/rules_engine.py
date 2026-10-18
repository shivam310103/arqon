"""Deterministic liability engine for RBI digital-fraud compensation claims.

The engine never guesses. It reads structured evidence (events) plus facts extracted
from the complaint, and returns a classification, an outcome, the amounts, the rules
applied, the evidence each conclusion rests on, and what is missing.

Gemini proposes; this engine checks. Disagreements are surfaced to the officer.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path

RULES = json.loads((Path(__file__).resolve().parent.parent / "data" / "rules.json").read_text(encoding="utf-8"))
K = RULES["constants"]

CLASSIFICATIONS = ["BANK_NEGLIGENCE", "THIRD_PARTY_BREACH", "CUSTOMER_NEGLIGENCE", "NOT_FRAUD", "UNDETERMINED"]
OUTCOMES = [
    "ZERO_LIABILITY_REFUND", "COMPENSATION", "CUSTOMER_LIABLE", "BANK_POLICY_REVIEW",
    "PENDING_CUSTOMER_ACTION", "INCOMPLETE_EVIDENCE", "REJECT_NOT_FRAUD",
]


def _d(ts: str) -> date:
    return datetime.fromisoformat(ts).date()


def _dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


@dataclass
class Finding:
    check: str
    result: str          # pass | fail | info | missing
    detail: str
    evidence: list[str] = field(default_factory=list)
    rule: str | None = None


@dataclass
class Decision:
    classification: str
    outcome: str
    amounts: dict
    rules_applied: list[str]
    findings: list[Finding]
    missing: list[dict]
    deadline: dict

    def to_dict(self):
        d = asdict(self)
        return d


def evaluate(case: dict, facts: dict) -> Decision:
    """case: case dict with events. facts: complaint facts (from intake agent or fallback)."""
    ev = case["events"]
    by_type: dict[str, list[dict]] = {}
    for e in ev:
        by_type.setdefault(e["type"], []).append(e)

    findings: list[Finding] = []
    missing: list[dict] = []

    txns = [e for e in by_type.get("TXN", []) if e["attrs"].get("disputed")]
    auths = {e["attrs"].get("txn_id"): e for e in by_type.get("AUTH", [])}
    bank_report = (by_type.get("COMPLAINT_BANK") or [None])[0]
    ncrp_report = (by_type.get("COMPLAINT_1930") or [None])[0]
    recovered = sum(e["attrs"].get("amount", 0) for e in by_type.get("RECOVERY", []))

    first_txn = min(txns, key=lambda e: e["ts"]) if txns else None
    fraud_day = _d(first_txn["ts"]) if first_txn else None
    report_dt = _dt(bank_report["ts"]) if bank_report else None
    days_to_bank = (report_dt.date() - fraud_day).days if (report_dt and fraud_day) else None
    days_to_1930 = (_d(ncrp_report["ts"]) - fraud_day).days if (ncrp_report and fraud_day) else None
    window = K["reporting_window_days"]

    # ---- amounts: pre / post report ----
    pre = [t for t in txns if not report_dt or _dt(t["ts"]) <= report_dt]
    post = [t for t in txns if report_dt and _dt(t["ts"]) > report_dt]
    pre_loss = sum(t["attrs"]["amount"] for t in pre)
    post_loss = sum(t["attrs"]["amount"] for t in post)
    gross = pre_loss + post_loss
    net_pre = max(pre_loss - recovered, 0)

    findings.append(Finding("Disputed transactions", "info",
                            f"{len(txns)} disputed, total Rs {gross:,}; recovered Rs {recovered:,}",
                            [t["event_id"] for t in txns]))
    if bank_report:
        res = "pass" if days_to_bank is not None and days_to_bank <= window else "fail"
        findings.append(Finding("Reported to bank within 5 calendar days", res,
                                f"Reported on day {days_to_bank} after the first disputed transaction",
                                [bank_report["event_id"]], "R2"))
    else:
        missing.append({"item": "Customer complaint to bank", "why": "No bank complaint record"})
    if ncrp_report:
        res = "pass" if days_to_1930 is not None and days_to_1930 <= window else "fail"
        findings.append(Finding("Reported to 1930 / NCRP within 5 calendar days", res,
                                f"Filed on day {days_to_1930} (ack {ncrp_report['attrs'].get('ack')})",
                                [ncrp_report["event_id"]], "R4"))
    if post:
        findings.append(Finding("Transactions after the fraud was reported", "info",
                                f"Rs {post_loss:,} debited after reporting; bank bears this",
                                [t["event_id"] for t in post], "R3"))

    # ---- evidence completeness (burden of proof, R5) ----
    for t in txns:
        tid = t["attrs"]["txn_id"]
        if tid not in auths:
            missing.append({"item": f"Authentication log for {tid} (Rs {t['attrs']['amount']:,})",
                            "why": "Bank must prove how this transaction was authorised before assigning liability",
                            "evidence": t["event_id"], "rule": "R5"})

    # ---- classification ----
    bank_fault = [e for e in ev if e["attrs"].get("bank_fault")]
    sim_swaps = [e for e in by_type.get("SIM_SWAP", []) if not e["attrs"].get("customer_requested", True)]
    advisories = by_type.get("BREACH_ADVISORY", [])
    remote_apps = [e for e in by_type.get("APP_INSTALL", []) if e["attrs"].get("risk") == "remote_access"]
    warnings_ack = [e for e in by_type.get("SCAM_WARNING", []) if e["attrs"].get("acknowledged")]
    phishing = by_type.get("PHISHING_SMS", [])
    calls = by_type.get("CALL_REPORTED", [])
    liveness_pass = [e for e in by_type.get("LIVENESS", []) if e["attrs"].get("result") == "pass"]

    cust_neg_evidence = [e["event_id"] for e in remote_apps + warnings_ack + phishing + calls]
    customer_admits = bool(facts.get("shared_credentials") or facts.get("installed_remote_app") or facts.get("clicked_phishing_link"))

    all_registered = bool(txns) and all(
        (auths.get(t["attrs"]["txn_id"], {}).get("attrs", {}).get("device_id") or "").startswith("D-REG")
        for t in txns)
    new_devices = [e for e in ev if e["type"] in ("DEVICE_BIND", "LOGIN") and e["attrs"].get("new_device")]

    if bank_fault:
        cls = "BANK_NEGLIGENCE"
        findings.append(Finding("Bank-side failure", "fail", "; ".join(e["summary"] for e in bank_fault),
                                [e["event_id"] for e in bank_fault], "R1"))
    elif (sim_swaps or advisories) and not customer_admits:
        cls = "THIRD_PARTY_BREACH"
        src = sim_swaps + advisories
        findings.append(Finding("Breach outside bank and customer", "info", "; ".join(e["summary"] for e in src),
                                [e["event_id"] for e in src], "R2"))
    elif customer_admits or cust_neg_evidence:
        cls = "CUSTOMER_NEGLIGENCE"
        findings.append(Finding("Customer negligence indicators", "info",
                                "Customer shared credentials, installed a remote-access app or used a phishing page",
                                cust_neg_evidence, "R3"))
    elif all_registered and liveness_pass and not new_devices:
        cls = "NOT_FRAUD"
        findings.append(Finding("Genuine customer authorisation", "info",
                                "Registered device, biometric authorisation and liveness check passed; no breach signals",
                                [e["event_id"] for e in liveness_pass] + [auths[t["attrs"]["txn_id"]]["event_id"] for t in txns], "R5"))
    else:
        cls = "UNDETERMINED"
        if new_devices:
            findings.append(Finding("New device used", "info", "Transactions came from a newly bound device; cause unclear",
                                    [e["event_id"] for e in new_devices]))

    amounts = {"gross_loss": gross, "recovered": recovered, "net_loss_before_report": net_pre,
               "loss_after_report": post_loss, "bank_pays": 0, "compensation": 0}
    rules = []
    deadline = {}

    # ---- outcome ----
    needs_proof = cls in ("CUSTOMER_NEGLIGENCE", "NOT_FRAUD", "UNDETERMINED")
    if missing and needs_proof:
        outcome = "INCOMPLETE_EVIDENCE"
        amounts["bank_pays"] = None
        rules = ["R5"]
    elif cls == "BANK_NEGLIGENCE":
        outcome, rules = "ZERO_LIABILITY_REFUND", ["R1", "R6"]
        amounts["bank_pays"] = gross - recovered
    elif cls == "THIRD_PARTY_BREACH":
        if days_to_bank is not None and days_to_bank <= window:
            outcome, rules = "ZERO_LIABILITY_REFUND", ["R2", "R6"]
            amounts["bank_pays"] = gross - recovered
        else:
            outcome, rules = "BANK_POLICY_REVIEW", ["R2"]
            amounts["bank_pays"] = None
            findings.append(Finding("Zero-liability window missed", "fail",
                                    f"Reported on day {days_to_bank}; liability falls under the bank's board-approved policy", [], "R2"))
    elif cls == "CUSTOMER_NEGLIGENCE":
        rules = ["R3"]
        amounts["bank_pays"] = post_loss
        eligible_amount = net_pre <= K["compensation_cap_loss"]
        in_scheme = fraud_day and K["scheme_start"] <= fraud_day.isoformat() <= K["scheme_end"]
        individual = case.get("account_type") == "individual"
        first_claim = not case.get("prior_compensation")
        bank_ok = days_to_bank is not None and days_to_bank <= window
        comp = min(round(net_pre * K["compensation_rate"]), K["compensation_max"])
        findings.append(Finding("Compensation: net loss within Rs 50,000", "pass" if eligible_amount else "fail",
                                f"Net loss before reporting Rs {net_pre:,}", [], "R4"))
        if eligible_amount and in_scheme and individual and first_claim and bank_ok:
            rules.append("R4")
            if ncrp_report and days_to_1930 <= window:
                outcome = "COMPENSATION"
                amounts["compensation"] = comp
            else:
                as_of = date.fromisoformat(case["as_of"])
                last_day = fraud_day + timedelta(days=window)
                if as_of <= last_day:
                    outcome = "PENDING_CUSTOMER_ACTION"
                    amounts["compensation"] = comp
                    deadline["customer_action"] = {"action": "File complaint on 1930 / cybercrime.gov.in",
                                                   "by": last_day.isoformat()}
                    missing.append({"item": "1930 / NCRP complaint reference",
                                    "why": f"Required for compensation; customer must file by {last_day.isoformat()}", "rule": "R4"})
                else:
                    outcome = "CUSTOMER_LIABLE"
        else:
            outcome = "CUSTOMER_LIABLE"
    elif cls == "NOT_FRAUD":
        outcome, rules = "REJECT_NOT_FRAUD", ["R5"]
    else:
        outcome, rules = "INCOMPLETE_EVIDENCE", ["R5"]
        amounts["bank_pays"] = None
        if not missing:
            missing.append({"item": "Root-cause evidence", "why": "Cannot establish how credentials were compromised", "rule": "R5"})

    received = date.fromisoformat(case["received_on"])
    days = K["resolution_days_cross_border"] if case.get("cross_border") else K["resolution_days_domestic"]
    deadline["resolve_by"] = (received + timedelta(days=days)).isoformat()
    deadline["days_left"] = (received + timedelta(days=days) - date.fromisoformat(case["as_of"])).days

    return Decision(cls, outcome, amounts, rules, findings, missing, deadline)


def rule_text(rid: str) -> dict:
    return next(r for r in RULES["rules"] if r["id"] == rid)
