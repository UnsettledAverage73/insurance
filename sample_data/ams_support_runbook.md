# ValueMomentum AMS L2/L3 Support Troubleshooting Runbook

## SOP-AMS-001: Policy Status Sync Mismatch (`ERR_POLICY_SYNC_MISMATCH`)
- **Symptoms:** Guidewire PolicyCenter / BillingCenter reports policy status as `ACTIVE` (premium paid and in-force), while ClaimCenter local replica (`cc_policy_cache`) reports `LAPSED` or `PENDING_CANCEL`.
- **Root Cause:** Asynchronous Kafka / MuleSoft `PolicyStatusChanged` integration event experienced dead-letter queue (DLQ) delay or out-of-order offset commit between BillingCenter and ClaimCenter.
- **L2 Triage Action:**
  1. Confirm authoritative `billing_status == "ACTIVE"` and `policycenter_status == "ACTIVE"`.
  2. Do **NOT** deny the policyholder claim for lapse; freeze automated claims adjudication.
  3. Generate a Jira/ServiceNow RCA ticket assigned to `AMS-Core-Integration-L2`.
  4. Propose safe, idempotent SQL sync patch for human L2 approval to align `cc_policy_cache.status = 'ACTIVE'` and trigger event replay.
- **Approved SQL Remediation Template:**
  ```sql
  UPDATE cc_policy_cache
  SET status = 'ACTIVE', sync_source = 'PolicyCenter_Reconciled', updated_at = CURRENT_TIMESTAMP
  WHERE policy_id = '{policy_id}' AND billing_status = 'ACTIVE';
  ```

## SOP-AMS-002: Truncated or Missing Endorsement Code (`ERR_MISSING_ENDORSEMENT`)
- **Symptoms:** Incoming FNOL webhook payload contains a missing, empty, or truncated `endorsement_code` (for example `"END-GL"` instead of `"END-GLASS-01"`), or an endorsement code not matching the valid catalog regex `^END-[A-Z]+-\d{2}$`.
- **Root Cause:** Upstream ACORD XML-to-JSON API gateway adapter truncated the `coverage_endorsement` string to 6 characters or dropped the attribute during schema transformation.
- **L2 Triage Action:**
  1. Halt ClaimFlow RAG evaluation to prevent false-negative coverage denial.
  2. Look up authoritative active endorsements for `policy_id` in PolicyCenter.
  3. Generate a Jira/ServiceNow RCA ticket assigned to `AMS-Gateway-Adapters-L2`.
  4. Propose a safe JSON payload schema patch restoring the full authoritative `endorsement_code` for L2 engineer approval before re-driving the FNOL event.

## SOP-AMS-003: Malformed FNOL Payload / Schema Violation (`ERR_MALFORMED_PAYLOAD`)
- **Symptoms:** Missing mandatory FNOL fields (`policy_id`, `incident_date`, `loss_type`, `claimed_amount`), invalid ISO-8601 date strings, or negative/zero `claimed_amount`.
- **Root Cause:** Upstream digital portal or broker webhook submitted `v1` payload without required fields or bypassed client-side validation.
- **L2 Triage Action:**
  1. Reject payload from Straight-Through Processing (STP) prior to LLM invocation.
  2. Document exact field validation failures in Jira RCA.
  3. Propose normalized JSON schema patch with default mappings or request broker re-submission.

## SOP-AMS-004: Downstream Payout Webhook Timeout (`ERR_PAYOUT_WEBHOOK_504`)
- **Symptoms:** ClaimCenter disbursement call to Payment Gateway returns HTTP `504 Gateway Timeout`.
- **Root Cause:** Payment processor latency spike or connection pool exhaustion on MuleSoft egress proxy.
- **L2 Triage Action:** Verify `idempotency_key` in `payout_ledger` before retrying to guarantee zero duplicate disbursements.

## SOP-AMS-005: Domain Rule Conflict or Unresolved Policy Exception (`ERR_RULE_CONFLICT`)
- **Symptoms:** ClaimFlow domain agents detect contradictory policy clauses, missing endorsement text in vector store, or inconsistent deductible/sub-limit calculation.
- **Root Cause:** Newly issued state endorsement wording not yet ingested into LanceDB knowledge base or conflicting adjuster rule thresholds.
- **L2 Triage Action:** Escalate to `AMS-Domain-Config-L2`, attach full LangGraph node execution trace, and suspend auto-payout until knowledge base sync completes.
