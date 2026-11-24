"""FastAPI entrypoint for InsureOps-ClaimFlow."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.graph import get_compiled_graph, run_claim_pipeline
from app.schemas import ClaimProcessResponse
from app.tools.llm_client import detect_inference_mode
from app.tools.rag_store import get_rag_store

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_EVENTS_PATH = PROJECT_ROOT / "sample_data" / "test_events.json"
STATIC_DIR = PROJECT_ROOT / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Pre-warm LanceDB vector index and compiled LangGraph workflow on startup."""
    get_rag_store()
    get_compiled_graph()
    yield


app = FastAPI(
    title="InsureOps-ClaimFlow",
    description="Unified P&C Claims Processing (ClaimFlow AI) + AMS L2 Support Triage (InsuranceOps)",
    version="1.0.0",
    lifespan=lifespan,
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def serve_ui() -> FileResponse:
    """Serve the single-page visual trace viewer."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health_check() -> dict[str, Any]:
    """Return service health, active inference backend, and LanceDB readiness."""
    rag = get_rag_store()
    return {
        "status": "ok",
        "service": "InsureOps-ClaimFlow",
        "inference_mode": detect_inference_mode(),
        "lancedb_tables": ["policy_wordings", "ams_runbooks"],
        "policy_chunks": rag.policy_table.count_rows(),
        "runbook_chunks": rag.runbook_table.count_rows(),
    }


@app.get("/scenarios")
def list_scenarios() -> list[dict[str, Any]]:
    """Return the 5 pre-built P&C + AMS L2 demo scenarios."""
    return json.loads(SAMPLE_EVENTS_PATH.read_text(encoding="utf-8"))


@app.post("/process-claim", response_model=ClaimProcessResponse)
def process_claim(payload: dict[str, Any] = Body(...)) -> ClaimProcessResponse:
    """Execute the 5-node InsureOps-ClaimFlow LangGraph pipeline for an FNOL claim event."""
    return run_claim_pipeline(payload)


@app.get("/audit-logs")
def get_audit_logs(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent immutable decision-level JSON audit records."""
    audit_path = Path(os.getenv("AUDIT_LOG_PATH", PROJECT_ROOT / ".audit_log.jsonl"))
    if not audit_path.exists():
        return []
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    return list(reversed(records[-limit:]))
