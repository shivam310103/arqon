"""Build the evidence timeline and find the break point (the first event where control was lost)."""
from __future__ import annotations

from datetime import datetime

# Event types that signal a compromise or anomaly, with display severity.
ANOMALY = {
    "SIM_SWAP": "high", "BREACH_ADVISORY": "high", "APP_INSTALL": "high", "PHISHING_SMS": "high",
    "CALL_REPORTED": "high", "CONTACT_UPDATE": "high",
}
CATEGORY = {
    "LOGIN": "access", "DEVICE_BIND": "device", "SIM_SWAP": "telecom", "OTP_SENT": "otp", "AUTH": "auth",
    "TXN": "money", "BANK_ALERT": "alert", "LIVENESS": "identity", "COMPLAINT_BANK": "report",
    "COMPLAINT_1930": "report", "RECOVERY": "money", "BREACH_ADVISORY": "external", "APP_INSTALL": "device",
    "SCAM_WARNING": "alert", "PHISHING_SMS": "external", "CALL_REPORTED": "external", "CONTACT_UPDATE": "bank",
}


def _is_anomaly(e: dict) -> bool:
    a = e["attrs"]
    if e["type"] in ANOMALY:
        if e["type"] == "SIM_SWAP" and a.get("customer_requested"):
            return False
        if e["type"] == "CONTACT_UPDATE" and a.get("processed", True):
            return False
        return True
    if e["type"] in ("DEVICE_BIND", "LOGIN") and a.get("new_device"):
        return True
    if a.get("bank_fault"):
        return True
    return False


def build(case: dict) -> dict:
    events = sorted(case["events"], key=lambda e: e["ts"])
    txns = [e for e in events if e["type"] == "TXN" and e["attrs"].get("disputed")]
    first_txn = txns[0] if txns else None
    items = []
    for e in events:
        sev = "normal"
        if _is_anomaly(e):
            sev = "anomaly"
        elif e["type"] == "TXN" and e["attrs"].get("disputed"):
            sev = "disputed"
        elif e["type"] in ("COMPLAINT_BANK", "COMPLAINT_1930"):
            sev = "report"
        items.append({**e, "category": CATEGORY.get(e["type"], "other"), "severity": sev})

    break_point = None
    if first_txn:
        before = [e for e in items if e["severity"] == "anomaly" and e["ts"] <= first_txn["ts"]]
        if before:
            bp = before[0]
            gap = datetime.fromisoformat(first_txn["ts"]) - datetime.fromisoformat(bp["ts"])
            minutes = int(gap.total_seconds() // 60)
            break_point = {"event_id": bp["event_id"], "summary": bp["summary"],
                           "minutes_before_first_txn": minutes, "first_txn_id": first_txn["event_id"]}
    return {"events": items, "break_point": break_point}
