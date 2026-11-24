"""End-to-end pytest suite covering all 5 InsureOps-ClaimFlow LangGraph & FastAPI scenarios."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLE_EVENTS = json.loads(
    (Path(__file__).resolve().parents[1] / "sample_data" / "test_events.json").read_text(
        encoding="utf-8"
    )
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def _scenario_payload(scenario_id: str) -> dict:
    return next(item["payload"] for item in SAMPLE_EVENTS if item["scenario_id"] == scenario_id)


def test_health_and_scenarios(client: TestClient) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["policy_chunks"] >= 5
    assert body["runbook_chunks"] >= 4

    scenarios = client.get("/scenarios")
    assert scenarios.status_code == 200
    assert len(scenarios.json()) == 5


def test_scenario_01_auto_glass_approved(client: TestClient) -> None:
    resp = client.post("/process-claim", json=_scenario_payload("SCENARIO_01"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["final_outcome"] == "AUTO_APPROVED"
    assert data["active_path"] == [
        "Node 1: Gatekeeper",
        "Node 2: Policy RAG",
        "Node 3: Risk Scorer",
        "Node 4: Adjuster Copilot",
    ]
    assert data["policy_coverage"]["covered"] is True
    assert "END-GLASS-01" in data["policy_coverage"]["clause_citation"]
    assert data["risk_assessment"]["risk_tier"] == "LOW"
    assert data["adjuster_decision"]["net_payout"] == 950.0
    assert data["l2_support_ticket"] is None


def test_scenario_02_flood_excluded_under_basic_fire(client: TestClient) -> None:
    resp = client.post("/process-claim", json=_scenario_payload("SCENARIO_02"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["final_outcome"] == "DENIED_EXCLUDED"
    assert data["policy_coverage"]["covered"] is False
    assert data["policy_coverage"]["coverage_status"] == "EXCLUDED"
    assert "EX-FLD-09" in data["policy_coverage"]["clause_citation"]
    assert data["adjuster_decision"]["net_payout"] == 0.0


def test_scenario_03_theft_48h_post_inception_escalated(client: TestClient) -> None:
    resp = client.post("/process-claim", json=_scenario_payload("SCENARIO_03"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["final_outcome"] == "ESCALATED_HITL"
    assert data["risk_assessment"]["risk_tier"] == "HIGH"
    assert data["risk_assessment"]["days_since_inception"] == 2
    assert any("COND-7D-01" in rule for rule in data["risk_assessment"]["triggered_rules"])
    assert data["adjuster_decision"]["human_review_required"] is True
    assert data["adjuster_decision"]["net_payout"] == 0.0


def test_scenario_04_policy_sync_mismatch_routed_to_l2(client: TestClient) -> None:
    resp = client.post("/process-claim", json=_scenario_payload("SCENARIO_04"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["final_outcome"] == "L2_SUPPORT_TRIAGED"
    assert data["active_path"] == ["Node 1: Gatekeeper", "Node 5: L2 Support RCA"]
    assert data["gatekeeper"]["error_code"] == "ERR_POLICY_SYNC_MISMATCH"
    assert data["policy_coverage"] is None
    assert data["l2_support_ticket"]["patch_type"] == "SQL_SYNC_PATCH"
    assert "UPDATE cc_policy_cache" in data["l2_support_ticket"]["proposed_patch"]


def test_scenario_05_truncated_endorsement_routed_to_l2(client: TestClient) -> None:
    resp = client.post("/process-claim", json=_scenario_payload("SCENARIO_05"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["final_outcome"] == "L2_SUPPORT_TRIAGED"
    assert data["active_path"] == ["Node 1: Gatekeeper", "Node 5: L2 Support RCA"]
    assert data["gatekeeper"]["error_code"] == "ERR_MISSING_ENDORSEMENT"
    assert data["l2_support_ticket"]["patch_type"] == "JSON_SCHEMA_PATCH"
    assert "END-GLASS-01" in data["l2_support_ticket"]["proposed_patch"]
