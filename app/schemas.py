"""Pydantic domain schemas and LangGraph state definitions for InsureOps-ClaimFlow."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


class ClaimEvent(BaseModel):
    """Canonical First Notice of Loss (FNOL) payload schema."""

    claim_id: str = Field(..., min_length=3)
    policy_id: str = Field(..., min_length=3)
    policy_type: str = Field(..., min_length=2)
    endorsement_code: str = Field(..., pattern=r"^END-[A-Z]+-\d{2}$")
    policy_inception_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    incident_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    loss_type: str = Field(..., min_length=2)
    claimed_amount: float = Field(..., gt=0)
    invoice_hash: str = Field(default="")
    claimant_name: str = Field(default="Unnamed Insured")
    incident_description: str = Field(..., min_length=5)


class GatekeeperResult(BaseModel):
    """Output from Node 1: Payload & Sync Gatekeeper (InsuranceOps layer)."""

    passed: bool
    route: Literal["claimflow", "l2_support"]
    error_code: Optional[str] = None
    fault_summary: Optional[str] = None
    policycenter_status: Optional[str] = None
    billing_status: Optional[str] = None
    claims_status: Optional[str] = None
    authoritative_endorsements: list[str] = Field(default_factory=list)
    validation_checks: list[str] = Field(default_factory=list)


class PolicyCoverageResult(BaseModel):
    """Output from Node 2: Policy Coverage RAG Agent (ClaimFlow layer)."""

    covered: bool
    coverage_status: Literal["COVERED", "EXCLUDED", "NOT_FOUND", "CONFLICT"]
    matched_section: str
    clause_citation: str
    verbatim_excerpt: str
    sub_limit: float = Field(ge=0)
    deductible: float = Field(ge=0)
    reasoning: str
    retrieved_chunks: list[dict[str, Any]] = Field(default_factory=list)


class RiskAssessment(BaseModel):
    """Output from Node 3: Leakage & Risk Scoring Agent (ClaimFlow layer)."""

    risk_tier: Literal["LOW", "MEDIUM", "HIGH"]
    days_since_inception: int
    sublimit_utilization_pct: float
    duplicate_invoice_detected: bool
    triggered_rules: list[str] = Field(default_factory=list)
    leakage_flags: list[str] = Field(default_factory=list)
    rule_conflict: bool = False
    conflict_reason: Optional[str] = None


class AdjusterDecision(BaseModel):
    """Output from Node 4: Adjuster Copilot & Comms Agent (ClaimFlow layer)."""

    final_outcome: Literal["AUTO_APPROVED", "DENIED_EXCLUDED", "ESCALATED_HITL"]
    gross_claimed: float
    deductible_applied: float
    capped_payout_base: float
    net_payout: float
    policyholder_notice: Optional[str] = None
    adjuster_audit_brief: Optional[str] = None
    human_review_required: bool


class L2SupportTicket(BaseModel):
    """Output from Node 5: L2 Support Triage & RCA Agent (InsuranceOps layer)."""

    ticket_id: str
    target_system: str = "Jira / ServiceNow"
    assigned_queue: str
    severity: Literal["P1", "P2", "P3"]
    error_code: str
    matched_runbook_sop: str
    runbook_excerpt: str
    root_cause_analysis: str
    patch_type: Literal["SQL_SYNC_PATCH", "JSON_SCHEMA_PATCH", "MANUAL_INVESTIGATION"]
    proposed_patch: str
    requires_human_approval: bool = True


class TraceStep(BaseModel):
    """Single node execution trace record for audit and UI visualization."""

    node_id: str
    node_name: str
    layer: Literal["InsuranceOps", "ClaimFlow"]
    status: Literal["PASSED", "FAULT_DETECTED", "COMPLETED", "ESCALATED", "DENIED"]
    duration_ms: float
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class WorkflowState(TypedDict, total=False):
    """Shared LangGraph state flowing across the 5-node InsureOps-ClaimFlow pipeline."""

    run_id: str
    raw_payload: dict[str, Any]
    validated_claim: Optional[dict[str, Any]]
    route: str
    inference_mode: str
    gatekeeper: Optional[dict[str, Any]]
    policy_coverage: Optional[dict[str, Any]]
    risk_assessment: Optional[dict[str, Any]]
    adjuster_decision: Optional[dict[str, Any]]
    l2_support_ticket: Optional[dict[str, Any]]
    final_outcome: str
    active_path: Annotated[list[str], operator.add]
    execution_trace: Annotated[list[dict[str, Any]], operator.add]


class ClaimProcessResponse(BaseModel):
    """API response returned by POST /process-claim."""

    run_id: str
    timestamp: str
    claim_id: str
    policy_id: str
    inference_mode: str
    active_path: list[str]
    final_outcome: str
    gatekeeper: GatekeeperResult
    policy_coverage: Optional[PolicyCoverageResult] = None
    risk_assessment: Optional[RiskAssessment] = None
    adjuster_decision: Optional[AdjusterDecision] = None
    l2_support_ticket: Optional[L2SupportTicket] = None
    execution_trace: list[TraceStep]
    audit_record_id: str
