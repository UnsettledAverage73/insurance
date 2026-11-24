"""Node 2: Policy Coverage RAG Agent (ClaimFlow domain engine)."""

from __future__ import annotations

import re
import time
from typing import Any

from pydantic import BaseModel, Field

from app.schemas import PolicyCoverageResult, TraceStep, WorkflowState
from app.tools.llm_client import invoke_structured_llm
from app.tools.rag_store import get_rag_store


class _LLMCoverageOutput(BaseModel):
    covered: bool
    coverage_status: str = Field(..., pattern="^(COVERED|EXCLUDED|NOT_FOUND|CONFLICT)$")
    matched_section: str
    clause_citation: str
    verbatim_excerpt: str
    sub_limit: float
    deductible: float
    reasoning: str


def _extract_money(text: str, label: str, default: float) -> float:
    match = re.search(rf"{label}:\*\*\s*\$([0-9,]+)", text, re.IGNORECASE)
    if not match:
        match = re.search(rf"{label}[^\$]*\$([0-9,]+)", text, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(",", ""))
    return default


def _deterministic_coverage_eval(
    claim: dict[str, Any], chunks: list[dict[str, Any]]
) -> PolicyCoverageResult:
    loss_type = claim["loss_type"].lower().strip()
    endorsement = claim["endorsement_code"].upper().strip()
    policy_type = claim["policy_type"].upper().strip()

    exclusion_chunk = next(
        (
            c
            for c in chunks
            if (loss_type in {"flood", "water_inundation", "surface_water"} and "EX-FLD-09" in c["content"])
            or (loss_type in {"racing", "intentional_act"} and "EX-RAC-04" in c["content"])
        ),
        None,
    )
    if exclusion_chunk:
        lines = [ln.strip() for ln in exclusion_chunk["content"].splitlines() if ln.strip()]
        excerpt = " ".join(lines[1:4]) if len(lines) > 1 else exclusion_chunk["content"][:280]
        return PolicyCoverageResult(
            covered=False,
            coverage_status="EXCLUDED",
            matched_section=exclusion_chunk["title"],
            clause_citation=f"{exclusion_chunk['source']} :: {exclusion_chunk['section_code']}",
            verbatim_excerpt=excerpt,
            sub_limit=0.0,
            deductible=0.0,
            reasoning=(
                f"Peril '{loss_type}' under policy form {policy_type} ({endorsement}) triggers "
                f"explicit policy exclusion {exclusion_chunk['section_code']}."
            ),
            retrieved_chunks=chunks,
        )

    matched = next(
        (c for c in chunks if endorsement in c["content"] or loss_type in c["content"].lower()),
        chunks[0] if chunks else None,
    )
    if not matched:
        return PolicyCoverageResult(
            covered=False,
            coverage_status="NOT_FOUND",
            matched_section="Unknown",
            clause_citation="N/A",
            verbatim_excerpt="No matching policy clause found in LanceDB.",
            sub_limit=0.0,
            deductible=0.0,
            reasoning="Could not locate applicable policy wording in vector store.",
            retrieved_chunks=chunks,
        )

    sub_limit = _extract_money(matched["content"], r"(?:Sub-Limit|Policy Limit)", 2500.0)
    deductible = _extract_money(matched["content"], "Deductible", 250.0)
    lines = [ln.strip() for ln in matched["content"].splitlines() if ln.strip()]
    excerpt = " ".join(lines[1:4]) if len(lines) > 1 else matched["content"][:280]

    peril_supported = loss_type in matched["content"].lower() or (
        loss_type == "auto_glass" and "END-GLASS-01" in matched["content"]
    )
    if not peril_supported:
        return PolicyCoverageResult(
            covered=False,
            coverage_status="EXCLUDED",
            matched_section=matched["title"],
            clause_citation=f"{matched['source']} :: {matched['section_code']}",
            verbatim_excerpt=excerpt,
            sub_limit=0.0,
            deductible=0.0,
            reasoning=f"Named-peril policy {policy_type} ({endorsement}) does not cover '{loss_type}'.",
            retrieved_chunks=chunks,
        )

    return PolicyCoverageResult(
        covered=True,
        coverage_status="COVERED",
        matched_section=matched["title"],
        clause_citation=f"{matched['source']} :: {matched['section_code']}",
        verbatim_excerpt=excerpt,
        sub_limit=sub_limit,
        deductible=deductible,
        reasoning=(
            f"Peril '{loss_type}' is explicitly covered under {matched['title']} "
            f"with a ${sub_limit:,.0f} sub-limit and ${deductible:,.0f} deductible."
        ),
        retrieved_chunks=chunks,
    )


def policy_rag_node(state: WorkflowState) -> dict[str, Any]:
    """Query LanceDB policy wordings and determine coverage, exclusions, and deductibles."""
    started = time.perf_counter()
    claim = state["validated_claim"]
    assert claim is not None

    rag = get_rag_store()
    query = (
        f"Policy {claim['policy_type']} endorsement {claim['endorsement_code']} "
        f"loss_type {claim['loss_type']}: {claim['incident_description']}"
    )
    chunks = rag.retrieve_policy_clauses(
        query=query,
        endorsement_code=claim["endorsement_code"],
        loss_type=claim["loss_type"],
        top_k=3,
    )

    chunks_text = "\n\n---\n\n".join(
        f"[{c['doc_id']} | {c['section_code']}] {c['content']}" for c in chunks
    )
    system_prompt = (
        "You are a senior P&C Insurance Policy Coverage RAG Analyst. "
        "Determine coverage strictly from the retrieved policy wording chunks. "
        "Check exclusions first (such as EX-FLD-09 for flood under Basic Fire), "
        "and cite the exact section code and verbatim wording."
    )
    user_prompt = (
        f"Claim payload:\n{claim}\n\nRetrieved Policy Wordings:\n{chunks_text}\n\n"
        "Return structured coverage evaluation."
    )
    llm_result, mode = invoke_structured_llm(system_prompt, user_prompt, _LLMCoverageOutput)

    if llm_result is not None:
        coverage = PolicyCoverageResult(
            covered=llm_result.covered,
            coverage_status=llm_result.coverage_status,  # type: ignore[arg-type]
            matched_section=llm_result.matched_section,
            clause_citation=llm_result.clause_citation,
            verbatim_excerpt=llm_result.verbatim_excerpt,
            sub_limit=llm_result.sub_limit,
            deductible=llm_result.deductible,
            reasoning=llm_result.reasoning,
            retrieved_chunks=chunks,
        )
    else:
        coverage = _deterministic_coverage_eval(claim, chunks)

    next_route = "l2_support" if coverage.coverage_status in {"NOT_FOUND", "CONFLICT"} else "risk_scorer"
    trace_status = "DENIED" if not coverage.covered else "COMPLETED"
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    trace = TraceStep(
        node_id="node_2",
        node_name="Policy Coverage RAG Agent",
        layer="ClaimFlow",
        status=trace_status,
        duration_ms=duration_ms,
        summary=f"{coverage.coverage_status} ({coverage.clause_citation}): {coverage.reasoning}",
        details={
            "coverage_status": coverage.coverage_status,
            "clause_citation": coverage.clause_citation,
            "sub_limit": coverage.sub_limit,
            "deductible": coverage.deductible,
        },
    )
    return {
        "route": next_route,
        "inference_mode": mode,
        "policy_coverage": coverage.model_dump(),
        "active_path": ["Node 2: Policy RAG"],
        "execution_trace": [trace.model_dump()],
    }
