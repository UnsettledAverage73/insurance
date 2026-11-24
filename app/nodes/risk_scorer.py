"""Node 3: Leakage & Risk Scoring Agent (ClaimFlow deterministic rules)."""

from __future__ import annotations

import time
from datetime import date
from typing import Any

from app.schemas import RiskAssessment, TraceStep, WorkflowState
from app.tools.policy_registry import is_duplicate_invoice


def risk_scorer_node(state: WorkflowState) -> dict[str, Any]:
    """Run deterministic anti-leakage and fraud rules to assign LOW, MEDIUM, or HIGH risk."""
    started = time.perf_counter()
    claim = state["validated_claim"]
    coverage = state["policy_coverage"]
    assert claim is not None and coverage is not None

    inception_dt = date.fromisoformat(claim["policy_inception_date"])
    incident_dt = date.fromisoformat(claim["incident_date"])
    days_since_inception = (incident_dt - inception_dt).days

    sub_limit = float(coverage.get("sub_limit") or 0.0)
    claimed_amount = float(claim["claimed_amount"])
    utilization_pct = round((claimed_amount / sub_limit) * 100, 2) if sub_limit > 0 else 0.0
    duplicate_invoice = is_duplicate_invoice(claim.get("invoice_hash", ""))

    triggered_rules: list[str] = []
    leakage_flags: list[str] = []
    rule_conflict = False
    conflict_reason = None

    if days_since_inception < 0:
        rule_conflict = True
        conflict_reason = (
            f"Incident date {claim['incident_date']} precedes policy inception "
            f"{claim['policy_inception_date']} ({days_since_inception} days)."
        )
        triggered_rules.append("ERR_RULE_CONFLICT: Incident predates policy inception")
    elif days_since_inception <= 7:
        triggered_rules.append(
            f"COND-7D-01: Loss occurred {days_since_inception} day(s) (<= 7 days) post-inception"
        )

    if duplicate_invoice:
        triggered_rules.append("DUP-INV-01: Duplicate invoice hash detected in ClaimCenter")
        leakage_flags.append("Duplicate invoice hash")

    if coverage.get("covered") and sub_limit > 0:
        if claimed_amount > sub_limit:
            leakage_flags.append(
                f"Sub-limit overrun (${claimed_amount:,.2f} > ${sub_limit:,.2f} limit)"
            )
            triggered_rules.append("LEAK-SUB-01: Claimed amount exceeds coverage sub-limit")
        elif utilization_pct >= 80.0:
            leakage_flags.append(
                f"High sub-limit utilization ({utilization_pct:.1f}% >= 80% threshold)"
            )
            triggered_rules.append("COND-7D-01: High sub-limit utilization >= 80%")

    if claimed_amount >= 25000.0 and coverage.get("covered"):
        triggered_rules.append(f"HIGH-VAL-01: High-value claim (${claimed_amount:,.2f} >= $25,000)")

    if duplicate_invoice or (0 <= days_since_inception <= 7 and coverage.get("covered")):
        risk_tier = "HIGH"
    elif len(leakage_flags) >= 2 or (leakage_flags and claimed_amount >= 25000.0):
        risk_tier = "HIGH"
    elif leakage_flags or triggered_rules:
        risk_tier = "MEDIUM"
    else:
        risk_tier = "LOW"

    assessment = RiskAssessment(
        risk_tier=risk_tier,  # type: ignore[arg-type]
        days_since_inception=days_since_inception,
        sublimit_utilization_pct=utilization_pct,
        duplicate_invoice_detected=duplicate_invoice,
        triggered_rules=triggered_rules,
        leakage_flags=leakage_flags,
        rule_conflict=rule_conflict,
        conflict_reason=conflict_reason,
    )

    next_route = "l2_support" if rule_conflict else "adjuster"
    trace_status = "FAULT_DETECTED" if rule_conflict else ("ESCALATED" if risk_tier == "HIGH" else "COMPLETED")
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    summary = (
        f"Risk Tier: {risk_tier} | Days post-inception: {days_since_inception} | "
        f"Rules triggered: {len(triggered_rules)}"
    )
    trace = TraceStep(
        node_id="node_3",
        node_name="Leakage & Risk Scoring Agent",
        layer="ClaimFlow",
        status=trace_status,
        duration_ms=duration_ms,
        summary=summary,
        details=assessment.model_dump(),
    )
    return {
        "route": next_route,
        "risk_assessment": assessment.model_dump(),
        "active_path": ["Node 3: Risk Scorer"],
        "execution_trace": [trace.model_dump()],
    }
