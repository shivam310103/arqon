"""Run the 8 labelled cases through the full pipeline and print a score.

    python scripts/run_evals.py          # uses Gemini if configured in .env, else offline
Writes eval_report.json.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)
r = c.get("/api/evals?live=true").json()
print(f"Mode: {r['llm_mode']}")
print(f"Final decisions correct:   {r['decision_accuracy']:.0%}")
acc = r["ai_classification_accuracy"]
print(f"AI classification correct: {acc:.0%} over {r['gemini_runs']} Gemini runs" if acc is not None else "AI classification correct: n/a (Gemini did not run - offline fallback)")
print(f"Citation validity:         {r['citation_validity']:.0%}\n")
for row in r["rows"]:
    mark = "OK " if row["outcome_correct"] and row["amount_correct"] else "XX "
    ai = {True: "AI ok", False: "AI MISS", None: "AI n/a"}[row["ai_classification_correct"]]
    print(f"{mark}{row['case_id']}  expected {row['expected']['outcome']:<24} got {row['got']['outcome']:<24} {ai}  "
          f"cites {row['citations_valid']}/{row['citations_checked']}  ({row['intake_source']}/{row['evidence_source']})")
Path("eval_report.json").write_text(json.dumps(r, indent=2))
