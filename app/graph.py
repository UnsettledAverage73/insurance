"""5-Node LangGraph StateGraph wiring InsuranceOps (outer shell) + ClaimFlow (inner engine)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.nodes.adjuster import adjuster_node
from app.nodes.gatekeeper import gatekeeper_node
from app.nodes.l2_support import l2_support_node
from app.nodes.policy_rag import policy_rag_node
from app.nodes.risk_scorer import risk_scorer_node
from app.schemas import (
    AdjusterDecision,
    ClaimProcessResponse,
    GatekeeperResult,
    L2SupportTicket,
    PolicyCoverageResult,
    RiskAssessment,
    TraceStep,
    WorkflowState,
)
from app.tools.llm_client import detect_inference_mode

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _route_after_gatekeeper(state: WorkflowState) -> str:
    return "l2_support" if state.get("route") == "l2_support" else "policy_rag"


def _route_after_policy_rag(state: WorkflowState) -> str:
    return "l2_support" if state.get("route") == "l2_support" else "risk_scorer"


def _route_after_risk_scorer(state: WorkflowState) -> str:
    return "l2_support" if state.get("route") == "l2_support" else "adjuster"


def build_workflow_graph():
    """Compile the unified 5-node InsureOps-ClaimFlow LangGraph state machine."""
    graph = StateGraph(WorkflowState)

    graph.add_node("gatekeeper", gatekeeper_node)
    graph.add_node("policy_rag", policy_rag_node)
    graph.add_node("risk_scorer", risk_scorer_node)
    graph.add_node("adjuster", adjuster_node)
    graph.add_node("l2_support", l2_support_node)

    graph.add_edge(START, "gatekeeper")
    graph.add_conditional_edges(
        "gatekeeper",
        _route_after_gatekeeper,
        {"l2_support": "l2_support", "policy_rag": "policy_rag"},
    )
    graph.add_conditional_edges(
        "policy_rag",
        _route_after_policy_rag,
        {"l2_support": "l2_support", "risk_scorer": "risk_scorer"},
    )
    graph.add_conditional_edges(
        "risk_scorer",
        _route_after_risk_scorer,
        {"l2_support": "l2_support", "adjuster": "adjuster"},
    )
    graph.add_edge("adjuster", END)
    graph.add_edge("l2_support", END)

    return graph.compile()


_compiled_graph = None


def get_compiled_graph():
    """Return a cached compiled LangGraph workflow."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_workflow_graph()
    return _compiled_graph


def _append_audit_log(response: ClaimProcessResponse) -> None:
    audit_path = Path(os.getenv("AUDIT_LOG_PATH", PROJECT_ROOT / ".audit_log.jsonl"))
    try:
        with audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(response.model_dump()) + "\n")
    except OSError:
        pass


def run_claim_pipeline(raw_payload: dict[str, Any]) -> ClaimProcessResponse:
    """Execute the 5-node LangGraph workflow and persist a decision-level audit record."""
    run_id = f"run-{uuid.uuid4().hex[:10]}"
    audit_record_id = f"AUD-{uuid.uuid4().hex[:8].upper()}"
    timestamp = datetime.now(timezone.utc).isoformat()

    initial_state: WorkflowState = {
        "run_id": run_id,
        "raw_payload": raw_payload,
        "inference_mode": detect_inference_mode(),
        "active_path": [],
        "execution_trace": [],
    }
    final_state = get_compiled_graph().invoke(initial_state)

    response = ClaimProcessResponse(
        run_id=run_id,
        timestamp=timestamp,
        claim_id=str(raw_payload.get("claim_id", "UNKNOWN")),
        policy_id=str(raw_payload.get("policy_id", "UNKNOWN")),
        inference_mode=final_state.get("inference_mode", detect_inference_mode()),
        active_path=final_state.get("active_path", []),
        final_outcome=final_state.get("final_outcome", "UNKNOWN"),
        gatekeeper=GatekeeperResult.model_validate(final_state["gatekeeper"]),
        policy_coverage=(
            PolicyCoverageResult.model_validate(final_state["policy_coverage"])
            if final_state.get("policy_coverage")
            else None
        ),
        risk_assessment=(
            RiskAssessment.model_validate(final_state["risk_assessment"])
            if final_state.get("risk_assessment")
            else None
        ),
        adjuster_decision=(
            AdjusterDecision.model_validate(final_state["adjuster_decision"])
            if final_state.get("adjuster_decision")
            else None
        ),
        l2_support_ticket=(
            L2SupportTicket.model_validate(final_state["l2_support_ticket"])
            if final_state.get("l2_support_ticket")
            else None
        ),
        execution_trace=[TraceStep.model_validate(t) for t in final_state.get("execution_trace", [])],
        audit_record_id=audit_record_id,
    )
    _append_audit_log(response)
    return response
