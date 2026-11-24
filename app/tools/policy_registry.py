"""Mock P&C Core Systems Registry (PolicyCenter, BillingCenter, ClaimCenter cache)."""

from __future__ import annotations

from typing import Any, Optional


POLICY_REGISTRY: dict[str, dict[str, Any]] = {
    "POL-CA-8841": {
        "policy_id": "POL-CA-8841",
        "policy_type": "CA-2026",
        "insured_name": "Apex Fleet Logistics LLC",
        "inception_date": "2026-01-15",
        "policycenter_status": "ACTIVE",
        "billing_status": "ACTIVE",
        "claims_status": "ACTIVE",
        "endorsements": ["END-GLASS-01", "END-COMP-02"],
        "sync_note": "In-sync across PolicyCenter, BillingCenter, and ClaimCenter.",
    },
    "POL-BF-5520": {
        "policy_id": "POL-BF-5520",
        "policy_type": "BF-2026",
        "insured_name": "Metro Storage Warehousing",
        "inception_date": "2025-11-01",
        "policycenter_status": "ACTIVE",
        "billing_status": "ACTIVE",
        "claims_status": "ACTIVE",
        "endorsements": ["END-FIRE-01"],
        "sync_note": "In-sync across PolicyCenter, BillingCenter, and ClaimCenter.",
    },
    "POL-CA-9902": {
        "policy_id": "POL-CA-9902",
        "policy_type": "CA-2026",
        "insured_name": "Vanguard Freight Carriers",
        "inception_date": "2026-11-18",
        "policycenter_status": "ACTIVE",
        "billing_status": "ACTIVE",
        "claims_status": "ACTIVE",
        "endorsements": ["END-COMP-02", "END-GLASS-01"],
        "sync_note": "Recently bound policy (within 7-day inception monitoring window).",
    },
    "POL-CA-7731": {
        "policy_id": "POL-CA-7731",
        "policy_type": "CA-2026",
        "insured_name": "Harbor Cold Chain Transport",
        "inception_date": "2026-03-01",
        "policycenter_status": "ACTIVE",
        "billing_status": "ACTIVE",
        "claims_status": "LAPSED",
        "endorsements": ["END-GLASS-01"],
        "sync_note": "Kafka DLQ lag detected: PolicyStatusChanged not applied to cc_policy_cache.",
    },
}

KNOWN_INVOICE_HASHES: set[str] = {
    "inv-hash-dup-0001",
    "inv-hash-settled-77",
}


def get_policy_record(policy_id: str) -> Optional[dict[str, Any]]:
    """Return mock Guidewire PolicyCenter/BillingCenter/ClaimCenter status for a policy ID."""
    return POLICY_REGISTRY.get(policy_id)


def is_duplicate_invoice(invoice_hash: str) -> bool:
    """Check whether an invoice hash already exists in ClaimCenter settlement history."""
    return bool(invoice_hash and invoice_hash in KNOWN_INVOICE_HASHES)
