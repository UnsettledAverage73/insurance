"""Node 4: Adjuster Copilot & Comms Agent (ClaimFlow decision & HITL routing)."""

from __future__ import annotations

import time
from typing import Any, Optional

from pydantic import BaseModel

from app.schemas import AdjusterDecision, TraceStep, WorkflowState
from app.tools.llm_client import invoke_structured_llm


class _LLMCommsDraft(BaseModel):
    policyholder_notice: Optional[str] = None
    adjuster_audit_brief: Optional[str] = None


def adjuster_node(state: WorkflowState) -> dict[str, Any]:
    """Compute itemized net payout, draft policyholder comms, or escalate to HITL adjuster queue."""
    started = time.perf_counter()
    claim = state["validated_claim"]
    coverage = state["policy_coverage"]
    risk = state["risk_assessment"]
    assert claim is not None and coverage is not None and risk is not None

    gross_claimed = float(claim["claimed_amount"])
    deductible = float(coverage.get("deductible") or 0.0)
    sub_limit = float(coverage.get("sub_limit") or 0.0)
    covered = bool(coverage.get("covered"))
    risk_tier = risk["risk_tier"]

    if not covered:
        final_outcome = "DENIED_EXCLUDED"
        capped_base = 0.0
        net_payout = 0.0
        human_review = False
        default_notice = (
            f"Dear {claim['claimant_name']},\n\n"
            f"Regarding Claim {claim['claim_id']} under Policy {claim['policy_id']} ({claim['policy_type']}): "
            f"After reviewing your {claim['loss_type']} loss reported on {claim['incident_date']}, "
            f"coverage is respectfully DENIED pursuant to {coverage['clause_citation']}.\n\n"
            f"Cited Policy Provision:\n\"{coverage['verbatim_excerpt']}\"\n\n"
            "If you believe additional endorsements apply, please contact your claims specialist."
        )
        default_brief = (
            f"Automated Denial Audit Brief for {claim['claim_id']}: Excluded under {coverage['clause_citation']}."
        )
    elif risk_tier == "LOW":
        final_outcome = "AUTO_APPROVED"
        capped_base = min(gross_claimed, sub_limit) if sub_limit > 0 else gross_claimed
        net_payout = round(max(0.0, capped_base - deductible), 2)
        human_review = False
        default_notice = (
            f"Dear {claim['claimant_name']},\n\n"
            f"Your {claim['loss_type']} claim ({claim['claim_id']}) under Policy {claim['policy_id']} "
            f"has been AUTO-APPROVED for Straight-Through Processing.\n"
            f"Itemized Settlement Breakdown:\n"
            f"- Gross Claimed Amount: ${gross_claimed:,.2f}\n"
            f"- Applicable Sub-Limit Cap: ${capped_base:,.2f}\n"
            f"- Policy Deductible ({coverage['clause_citation']}): -${deductible:,.2f}\n"
            f"- Net Approved Payout: ${net_payout:,.2f}\n\n"
            "Disbursement has been queued to your registered payment method."
        )
        default_brief = None
    else:
        final_outcome = "ESCALATED_HITL"
        capped_base = min(gross_claimed, sub_limit) if sub_limit > 0 else gross_claimed
        net_payout = 0.0
        human_review = True
        rules_text = "; ".join(risk.get("triggered_rules", [])) or "Elevated risk score"
        default_notice = (
            f"Dear {claim['claimant_name']},\n\n"
            f"Your claim {claim['claim_id']} under Policy {claim['policy_id']} has been assigned to a "
            "Senior Claims Adjuster for expedited verification. No additional action is needed at this time."
        )
        default_brief = (
            f"HITL ADJUSTER AUDIT BRIEF — Claim {claim['claim_id']} ({risk_tier} RISK)\n"
            f"- Policy: {claim['policy_id']} ({claim['endorsement_code']}) | Coverage Citation: {coverage['clause_citation']}\n"
            f"- Claimed Amount: ${gross_claimed:,.2f} (Sub-limit: ${sub_limit:,.2f}, Deductible: ${deductible:,.2f})\n"
            f"- Triggered Leakage/Fraud Rules: {rules_text}\n"
            f"- Recommended Action: Verify police report, proof of ownership, and underwriting binding logs before releasing payout."
        )

    system_prompt = (
        "You are an Insurance Claims Adjuster Copilot generating SmartCOMM-ready policyholder "
        "correspondence and concise HITL adjuster audit briefs. Preserve all exact dollar figures and citations."
    )
    user_prompt = (
        f"Outcome: {final_outcome}\nClaim: {claim}\nCoverage: {coverage}\nRisk: {risk}\n"
        f"Computed Net Payout: ${net_payout:,.2f} (Deductible: ${deductible:,.2f}).\n"
        "Draft crisp policyholder_notice and (if escalated/denied) adjuster_audit_brief."
    )
    llm_draft, mode = invoke_structured_llm(system_prompt, user_prompt, _LLMCommsDraft)

    notice = llm_draft.policyholder_notice if (llm_draft and llm_draft.policyholder_notice) else default_notice
    brief = llm_draft.adjuster_audit_brief if (llm_draft and llm_draft.adjuster_audit_brief) else default_brief
    if mode != "deterministic_fallback":
        active_mode = mode
    else:
        active_mode = state.get("inference_mode", "deterministic_fallback")

    decision = AdjusterDecision(
        final_outcome=final_outcome,  # type: ignore[arg-type]
        gross_claimed=gross_claimed,
        deductible_applied=deductible,
        capped_payout_base=capped_base,
        net_payout=net_payout,
        policyholder_notice=notice,
        adjuster_audit_brief=brief,
        human_review_required=human_review,
    )

    trace_status = (
        "DENIED"
        if final_outcome == "DENIED_EXCLUDED"
        else ("ESCALATED" if final_outcome == "ESCALATED_HITL" else "COMPLETED")
    )
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    trace = TraceStep(
        node_id="node_4",
        node_name="Adjuster Copilot & Comms Agent",
        layer="ClaimFlow",
        status=trace_status,
        duration_ms=duration_ms,
        summary=f"Outcome: {final_outcome} | Net Payout: ${net_payout:,.2f} | HITL: {human_review}",
        details=decision.model_dump(),
    )
    return {
        "inference_mode": active_mode,
        "adjuster_decision": decision.model_dump(),
        "final_outcome": final_outcome,
        "active_path": ["Node 4: Adjuster Copilot"],
        "execution_trace": [trace.model_dump()],
    }
