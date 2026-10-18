import json
import os
import sys
from pathlib import Path

os.environ["ARQON_OFFLINE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents import _intake_fallback  # noqa: E402
from app.rules_engine import evaluate  # noqa: E402

CASES = json.loads((Path(__file__).resolve().parent.parent / "data" / "cases.json").read_text(encoding="utf-8"))


def test_all_cases_match_expected():
    for c in CASES:
        d = evaluate(c, _intake_fallback(c["complaint_text"]))
        e = c["expected"]
        assert d.classification == e["classification"], c["case_id"]
        assert d.outcome == e["outcome"], c["case_id"]
        assert d.amounts["bank_pays"] == e["bank_pays"], c["case_id"]
        assert d.amounts["compensation"] == e["compensation"], c["case_id"]


def test_compensation_cap():
    c = next(x for x in CASES if x["case_id"] == "C1007")
    d = evaluate(c, {"clicked_phishing_link": True})
    assert d.amounts["compensation"] == 21250  # 85% of 25,000
