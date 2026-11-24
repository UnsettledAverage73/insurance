"""Node 5: L2 Support Triage & RCA Agent (InsuranceOps AMS self-healing layer)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.schemas import L2SupportTicket, TraceStep, WorkflowState
from app.tools.llm_client import invoke_structured_llm
from app.tools.policy_registry import get_policy_record
from app.tools.rag_store import get_rag_store


class _LLMTicketDraft(BaseModel):
    assigned_queue: str
    severity: str = Field(..., pattern="^(P1|P2|P3)$")
    root_cause_analysis: str
    patch_type: str = Field(..., pattern="^(SQL_SYNC_PATCH|JSON_SCHEMA_PATCH|MANUAL_INVESTIGATION)$")
    proposed_patch: str


def _deterministic_l2_ticket(
    raw_payload: dict[str, Any],
    error_code: str,
    fault_summary: str,
    runbook: dict[str, Any],
) -> L2SupportTicket:
    policy_id = str(raw_payload.get("policy_id", "UNKNOWN"))
    claim_id = str(raw_payload.get("claim_id", "UNKNOWN"))
    policy_rec = get_policy_record(policy_id)
    ticket_id = f"INC-AMS-{uuid.uuid4().hex[:6].upper()}"
    excerpt = "\n".join(runbook["content"].splitlines()[:6])

    if error_code == "ERR_POLICY_SYNC_MISMATCH":
        assigned_queue = "AMS-Core-Integration-L2"
        severity = "P1"
        patch_type = "SQL_SYNC_PATCH"
        rca = (
            f"Claim {claim_id} was intercepted prior to adjudication due to core system state drift "
            f"on {policy_id}. PolicyCenter & BillingCenter confirm ACTIVE paid status, whereas "
            "ClaimCenter cc_policy_cache remains LAPSED due to async Kafka/MuleSoft DLQ lag."
        )
        proposed_patch = (
            f"-- Safe, idempotent ClaimCenter cache reconciliation for {policy_id}\n"
            "UPDATE cc_policy_cache\n"
            "SET status = 'ACTIVE', sync_source = 'PolicyCenter_Reconciled', updated_at = CURRENT_TIMESTAMP\n"
            f"WHERE policy_id = '{policy_id}' AND billing_status = 'ACTIVE';"
        )
    elif error_code == "ERR_MISSING_ENDORSEMENT":
        assigned_queue = "AMS-Gateway-Adapters-L2"
        severity = "P2"
        patch_type = "JSON_SCHEMA_PATCH"
        auth_list = policy_rec["endorsements"] if policy_rec else ["END-GLASS-01"]
        loss_type = str(raw_payload.get("loss_type", "")).lower()
        suggested_end = (
            "END-GLASS-01"
            if "glass" in loss_type and "END-GLASS-01" in auth_list
            else auth_list[0]
        )
        patched_payload = dict(raw_payload)
        patched_payload["endorsement_code"] = suggested_end
        rca = (
            f"FNOL webhook for {claim_id} arrived with truncated/invalid endorsement_code "
            f"'{raw_payload.get('endorsement_code')}'. PolicyCenter confirms authoritative "
            f"endorsements {auth_list} for {policy_id}. Upstream ACORD XML-to-JSON adapter truncated field."
        )
        proposed_patch = json.dumps(
            {
                "patch_operation": "replace",
                "path": "/endorsement_code",
                "from": raw_payload.get("endorsement_code"),
                "to": suggested_end,
                "patched_fnol_payload": patched_payload,
            },
            indent=2,
        )
    elif error_code == "ERR_MALFORMED_PAYLOAD":
        assigned_queue = "AMS-Intake-Portal-L2"
        severity = "P2"
        patch_type = "JSON_SCHEMA_PATCH"
        rca = f"FNOL payload for {claim_id} failed Pydantic intake validation: {fault_summary}"
        proposed_patch = json.dumps(
            {
                "action": "normalize_fnol_payload",
                "fault": fault_summary,
                "received_payload": raw_payload,
            },
            indent=2,
        )
    else:
        assigned_queue = "AMS-Domain-Config-L2"
        severity = "P2"
        patch_type = "MANUAL_INVESTIGATION"
        rca = f"Domain rule conflict encountered during ClaimFlow execution for {claim_id}: {fault_summary}"
        proposed_patch = f"-- Escalated for manual domain review\n-- Fault: {fault_summary}"

    return L2SupportTicket(
        ticket_id=ticket_id,
        target_system="Jira / ServiceNow",
        assigned_queue=assigned_queue,
        severity=severity,  # type: ignore[arg-type]
        error_code=error_code,
        matched_runbook_sop=f"{runbook['source']} :: {runbook['section_code']}",
        runbook_excerpt=excerpt,
        root_cause_analysis=rca,
        patch_type=patch_type,  # type: ignore[arg-type]
        proposed_patch=proposed_patch,
        requires_human_approval=True,
    )


def l2_support_node(state: WorkflowState) -> dict[str, Any]:
    """Cross-reference AMS runbooks in LanceDB and generate Jira RCA + safe data-fix patch."""
    started = time.perf_counter()
    raw_payload = state.get("raw_payload") or {}
    gatekeeper = state.get("gatekeeper") or {}
    risk = state.get("risk_assessment") or {}
    coverage = state.get("policy_coverage") or {}

    if not gatekeeper.get("passed", True):
        error_code = gatekeeper.get("error_code") or "ERR_MALFORMED_PAYLOAD"
        fault_summary = gatekeeper.get("fault_summary") or "Gatekeeper detected payload/sync fault."
    elif risk.get("rule_conflict"):
        error_code = "ERR_RULE_CONFLICT"
        fault_summary = risk.get("conflict_reason") or "Rule conflict in Risk Scorer."
    else:
        error_code = "ERR_RULE_CONFLICT"
        fault_summary = coverage.get("reasoning") or "Policy RAG could not resolve coverage."

    rag = get_rag_store()
    runbooks = rag.retrieve_runbooks(query=f"{error_code} {fault_summary}", error_code=error_code, top_k=2)
    top_runbook = runbooks[0] if runbooks else {
        "source": "ams_support_runbook.md",
        "section_code": "SOP-AMS-005",
        "content": fault_summary,
    }

    system_prompt = (
        "You are a ValueMomentum L2 AMS Support Triage & RCA Engineer. "
        "Using the retrieved AMS troubleshooting runbook and execution trace, produce a crisp "
        "Root Cause Analysis and a safe, human-approved SQL sync or JSON schema patch."
    )
    user_prompt = (
        f"Error Code: {error_code}\nFault Summary: {fault_summary}\n"
        f"Raw Payload: {raw_payload}\nGatekeeper: {gatekeeper}\n"
        f"Retrieved Runbook:\n{top_runbook['content']}\n"
    )
    llm_ticket, mode = invoke_structured_llm(system_prompt, user_prompt, _LLMTicketDraft)

    ticket = _deterministic_l2_ticket(raw_payload, error_code, fault_summary, top_runbook)
    if llm_ticket is not None:
        ticket.assigned_queue = llm_ticket.assigned_queue
        ticket.severity = llm_ticket.severity  # type: ignore[assignment]
        ticket.root_cause_analysis = llm_ticket.root_cause_analysis
        ticket.patch_type = llm_ticket.patch_type  # type: ignore[assignment]
        ticket.proposed_patch = llm_ticket.proposed_patch

    active_mode = mode if mode != "deterministic_fallback" else state.get("inference_mode", "deterministic_fallback")
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    trace = TraceStep(
        node_id="node_5",
        node_name="L2 Support Triage & RCA Agent",
        layer="InsuranceOps",
        status="ESCALATED",
        duration_ms=duration_ms,
        summary=f"Created {ticket.ticket_id} ({ticket.severity}) -> {ticket.patch_type} [{ticket.matched_runbook_sop}]",
        details=ticket.model_dump(),
    )
    return {
        "inference_mode": active_mode,
        "l2_support_ticket": ticket.model_dump(),
        "final_outcome": "L2_SUPPORT_TRIAGED",
        "active_path": ["Node 5: L2 Support RCA"],
        "execution_trace": [trace.model_dump()],
    }
