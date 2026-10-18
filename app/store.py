"""Data access.

Cases/events: local JSON by default; BigQuery when ARQON_BQ_DATASET is set (e.g. "arqon").
Officer decisions + audit trail: in-memory by default; Firestore when ARQON_FIRESTORE=1.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
BQ_DATASET = os.getenv("ARQON_BQ_DATASET", "")
USE_FS = os.getenv("ARQON_FIRESTORE", "") == "1"

_local_cases = {c["case_id"]: c for c in json.loads((DATA / "cases.json").read_text(encoding="utf-8"))}
_bq = None
_fs = None
_decisions: dict[str, list[dict]] = {}


def data_source() -> str:
    return f"bigquery:{BQ_DATASET}" if BQ_DATASET else "local-json"


def decision_store() -> str:
    return "firestore" if USE_FS else "memory"


def _bq_client():
    global _bq
    if _bq is None:
        from google.cloud import bigquery
        _bq = bigquery.Client()
    return _bq


def _events_from_bq(case_id: str) -> list[dict]:
    from google.cloud import bigquery
    q = f"SELECT event_id, case_id, ts, type, source, summary, attrs FROM `{BQ_DATASET}.events` WHERE case_id=@cid ORDER BY ts"
    job = _bq_client().query(q, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("cid", "STRING", case_id)]))
    out = []
    for r in job.result():
        ts = r["ts"]
        ts = ts if isinstance(ts, str) else ts.isoformat()
        out.append({"event_id": r["event_id"], "case_id": r["case_id"], "ts": ts, "type": r["type"],
                    "source": r["source"], "summary": r["summary"], "attrs": json.loads(r["attrs"] or "{}")})
    return out


def list_cases() -> list[dict]:
    return list(_local_cases.values())


def get_case(case_id: str) -> dict | None:
    c = _local_cases.get(case_id)
    if c is None:
        return None
    if BQ_DATASET:
        try:
            c = {**c, "events": _events_from_bq(case_id)}
        except Exception as exc:  # fall back to local evidence so the demo never breaks
            print(f"[store] BigQuery read failed for {case_id}: {exc}")
    return c


def _fs_client():
    global _fs
    if _fs is None:
        from google.cloud import firestore
        _fs = firestore.Client()
    return _fs


def save_decision(case_id: str, record: dict) -> dict:
    record = {**record, "at": datetime.now(timezone.utc).isoformat()}
    if USE_FS:
        try:
            _fs_client().collection("decisions").document(case_id).collection("audit").add(record)
        except Exception as exc:
            print(f"[store] Firestore write failed: {exc}")
    _decisions.setdefault(case_id, []).append(record)
    return record


def get_decisions(case_id: str) -> list[dict]:
    if USE_FS and case_id not in _decisions:
        try:
            docs = _fs_client().collection("decisions").document(case_id).collection("audit").order_by("at").stream()
            _decisions[case_id] = [d.to_dict() for d in docs]
        except Exception as exc:
            print(f"[store] Firestore read failed: {exc}")
    return _decisions.get(case_id, [])
