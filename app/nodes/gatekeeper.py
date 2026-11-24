"""Node 1: Payload & Sync Gatekeeper (InsuranceOps deterministic guardrail)."""

from __future__ import annotations

import re
import time
from typing import Any

from pydantic import ValidationError

from app.schemas import ClaimEvent, GatekeeperResult, TraceStep, WorkflowState
from app.tools.policy_registry import get_policy_record

ENDORSEMENT_PATTERN = re.compile(r"^END-[A-Z]+-\d{2}$")


def gatekeeper_node(state: WorkflowState) -> dict[str, Any]:
    """Validate FNOL JSON schema and PolicyCenter/Billing/Claims sync before LLM execution."""
    started = time.perf_counter()
    raw = dict(state.get("raw_payload") or {})
    checks: list[str] = []

    endorsement_raw = raw.get("endorsement_code")
    if not isinstance(endorsement_raw, str) or not ENDORSEMENT_PATTERN.match(endorsement_raw.strip()):
        policy_id = str(raw.get("policy_id", ""))
        policy_rec = get_policy_record(policy_id)
        auth_endorsements = policy_rec["endorsements"] if policy_rec else []
        fault = (
            f"Invalid or truncated endorsement_code '{endorsement_raw}'. "
            "Expected catalog format ^END-[A-Z]+-\\d{2}$."
        )
        checks.append("Schema check failed: endorsement_code missing or truncated")
        result = GatekeeperResult(
            passed=False,
            route="l2_support",
            error_code="ERR_MISSING_ENDORSEMENT",
            fault_summary=fault,
            policycenter_status=policy_rec["policycenter_status"] if policy_rec else None,
            billing_status=policy_rec["billing_status"] if policy_rec else None,
            claims_status=policy_rec["claims_status"] if policy_rec else None,
            authoritative_endorsements=auth_endorsements,
            validation_checks=checks,
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        trace = TraceStep(
            node_id="node_1",
            node_name="Payload & Sync Gatekeeper",
            layer="InsuranceOps",
            status="FAULT_DETECTED",
            duration_ms=duration_ms,
            summary=fault,
            details=result.model_dump(),
        )
        return {
            "route": "l2_support",
            "gatekeeper": result.model_dump(),
            "active_path": ["Node 1: Gatekeeper"],
            "execution_trace": [trace.model_dump()],
        }

    checks.append("Endorsement code format valid")

    try:
        claim = ClaimEvent.model_validate(raw)
    except ValidationError as exc:
        err_msgs = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        fault = f"FNOL payload failed Pydantic schema validation: {err_msgs}"
        checks.append(f"Schema check failed: {err_msgs}")
        result = GatekeeperResult(
            passed=False,
            route="l2_support",
            error_code="ERR_MALFORMED_PAYLOAD",
            fault_summary=fault,
            validation_checks=checks,
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        trace = TraceStep(
            node_id="node_1",
            node_name="Payload & Sync Gatekeeper",
            layer="InsuranceOps",
            status="FAULT_DETECTED",
            duration_ms=duration_ms,
            summary=fault,
            details=result.model_dump(),
        )
        return {
            "route": "l2_support",
            "gatekeeper": result.model_dump(),
            "active_path": ["Node 1: Gatekeeper"],
            "execution_trace": [trace.model_dump()],
        }

    checks.append("Required FNOL JSON fields validated")

    policy_rec = get_policy_record(claim.policy_id)
    if not policy_rec:
        fault = f"Policy '{claim.policy_id}' was not found in Guidewire PolicyCenter registry."
        checks.append("PolicyCenter lookup failed: unknown policy_id")
        result = GatekeeperResult(
            passed=False,
            route="l2_support",
            error_code="ERR_MALFORMED_PAYLOAD",
            fault_summary=fault,
            validation_checks=checks,
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        trace = TraceStep(
            node_id="node_1",
            node_name="Payload & Sync Gatekeeper",
            layer="InsuranceOps",
            status="FAULT_DETECTED",
            duration_ms=duration_ms,
            summary=fault,
            details=result.model_dump(),
        )
        return {
            "route": "l2_support",
            "gatekeeper": result.model_dump(),
            "active_path": ["Node 1: Gatekeeper"],
            "execution_trace": [trace.model_dump()],
        }

    pc_status = policy_rec["policycenter_status"]
    bill_status = policy_rec["billing_status"]
    cc_status = policy_rec["claims_status"]
    auth_endorsements = list(policy_rec["endorsements"])

    if not (pc_status == bill_status == cc_status == "ACTIVE"):
        fault = (
            f"Core system status sync mismatch for {claim.policy_id}: "
            f"PolicyCenter={pc_status}, BillingCenter={bill_status}, ClaimCenter={cc_status}."
        )
        checks.append(f"Sync check failed: Billing={bill_status} vs ClaimCenter={cc_status}")
        result = GatekeeperResult(
            passed=False,
            route="l2_support",
            error_code="ERR_POLICY_SYNC_MISMATCH",
            fault_summary=fault,
            policycenter_status=pc_status,
            billing_status=bill_status,
            claims_status=cc_status,
            authoritative_endorsements=auth_endorsements,
            validation_checks=checks,
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        trace = TraceStep(
            node_id="node_1",
            node_name="Payload & Sync Gatekeeper",
            layer="InsuranceOps",
            status="FAULT_DETECTED",
            duration_ms=duration_ms,
            summary=fault,
            details=result.model_dump(),
        )
        return {
            "route": "l2_support",
            "gatekeeper": result.model_dump(),
            "active_path": ["Node 1: Gatekeeper"],
            "execution_trace": [trace.model_dump()],
        }

    checks.append("PolicyCenter / BillingCenter / ClaimCenter status in sync (ACTIVE)")

    if claim.endorsement_code not in auth_endorsements:
        fault = (
            f"Endorsement '{claim.endorsement_code}' is not active on {claim.policy_id} "
            f"(PolicyCenter endorsements: {auth_endorsements})."
        )
        checks.append("Endorsement catalog verification failed")
        result = GatekeeperResult(
            passed=False,
            route="l2_support",
            error_code="ERR_MISSING_ENDORSEMENT",
            fault_summary=fault,
            policycenter_status=pc_status,
            billing_status=bill_status,
            claims_status=cc_status,
            authoritative_endorsements=auth_endorsements,
            validation_checks=checks,
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        trace = TraceStep(
            node_id="node_1",
            node_name="Payload & Sync Gatekeeper",
            layer="InsuranceOps",
            status="FAULT_DETECTED",
            duration_ms=duration_ms,
            summary=fault,
            details=result.model_dump(),
        )
        return {
            "route": "l2_support",
            "gatekeeper": result.model_dump(),
            "active_path": ["Node 1: Gatekeeper"],
            "execution_trace": [trace.model_dump()],
        }

    checks.append(f"Endorsement {claim.endorsement_code} verified against PolicyCenter")
    result = GatekeeperResult(
        passed=True,
        route="claimflow",
        policycenter_status=pc_status,
        billing_status=bill_status,
        claims_status=cc_status,
        authoritative_endorsements=auth_endorsements,
        validation_checks=checks,
    )
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    trace = TraceStep(
        node_id="node_1",
        node_name="Payload & Sync Gatekeeper",
        layer="InsuranceOps",
        status="PASSED",
        duration_ms=duration_ms,
        summary="FNOL schema valid and PolicyCenter/Billing/Claims systems are in sync.",
        details=result.model_dump(),
    )
    return {
        "route": "claimflow",
        "validated_claim": claim.model_dump(),
        "gatekeeper": result.model_dump(),
        "active_path": ["Node 1: Gatekeeper"],
        "execution_trace": [trace.model_dump()],
    }
