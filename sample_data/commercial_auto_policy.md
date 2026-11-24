# Commercial Auto & Basic Fire P&C Policy Wording (Form VM-PC-2026)

## Section 1.1 — Auto Glass & Windshield Coverage (Endorsement `END-GLASS-01`)
Under Commercial Auto Policy Form `CA-2026` with active Endorsement `END-GLASS-01`, the Insurer agrees to pay for direct physical loss or accidental breakage to front windshields, rear windows, side door glass, and laminated safety glass of a covered commercial vehicle.
- **Coverage Status:** COVERED for `auto_glass` and `windshield_breakage` perils.
- **Sub-Limit:** $2,500 per occurrence.
- **Deductible:** $250 per full glass replacement occurrence ($0 for minor resin chip repair under $150).
- **Conditions:** Replacement parts must match OEM safety specifications.

## Section 1.2 — Commercial Auto Theft & Comprehensive Loss (Endorsement `END-COMP-02`)
Under Commercial Auto Policy Form `CA-2026` with active Endorsement `END-COMP-02`, the Insurer covers direct physical loss caused by theft, larceny, vandalism, or attempted theft of an insured commercial vehicle or permanently attached equipment.
- **Coverage Status:** COVERED for `theft` and `vandalism` perils.
- **Sub-Limit:** $50,000 per occurrence.
- **Deductible:** $1,000 per occurrence.
- **Conditions:** Police report reference required within 48 hours of discovery. Subject to Section 4.1 Early-Inception Anti-Leakage Review.

## Section 2.1 — Basic Fire & Lightning Coverage (Endorsement `END-FIRE-01`)
Under Basic Fire & Allied Perils Policy Form `BF-2026` with active Endorsement `END-FIRE-01`, the Insurer covers direct physical damage to insured commercial premises caused solely by fire, lightning, or smoke from a hostile fire.
- **Coverage Status:** COVERED for `fire`, `lightning`, and `smoke` perils.
- **Policy Limit:** $100,000 per occurrence.
- **Deductible:** $1,000 per occurrence.
- **Scope Note:** Named-peril policy; only perils explicitly listed in Section 2.1 or an attached endorsement are covered.

## Section 3.1 — Flood, Surface Water & Inundation Exclusion (Exclusion `EX-FLD-09`)
Under Policy Forms `BF-2026` and `CA-2026` (unless separate Flood Endorsement `END-FLD-99` is explicitly scheduled on the Declarations page), this policy **DOES NOT COVER** loss or damage caused directly or indirectly by:
1. Flood, surface water, waves, tidal water, storm surge, or overflow of any body of water;
2. Mudslide, mudflow, or backup of sewers/drains resulting from surface water accumulation.
Such loss is **EXCLUDED** regardless of any other cause or event contributing concurrently or in any sequence to the loss. Claims for `flood` or `water_inundation` under `BF-2026` without `END-FLD-99` must be **DENIED** citing Exclusion `EX-FLD-09`.

## Section 3.2 — Racing & Intentional Acts Exclusion (Exclusion `EX-RAC-04`)
This policy does not apply to any loss arising out of organized racing, speed contests, stunt driving, or intentional damage caused by or at the direction of any insured.

## Section 4.1 — Early-Inception Waiting & Claims Leakage Audit Clause (`COND-7D-01`)
To prevent underwriting misrepresentation, early-claim fraud, and claims leakage:
1. **7-Day Inception Rule:** Any First Notice of Loss (FNOL) with an `incident_date` occurring within **7 calendar days (168 hours)** of the `policy_inception_date` is automatically flagged as `HIGH` risk and **MUST NOT** be auto-settled; it must be routed to a Human Claims Adjuster (SIU/Audit Queue).
2. **High-Utilization Sub-Limit Check:** Any claim where `claimed_amount` exceeds **80% of the applicable coverage sub-limit** is flagged for leakage verification.
3. **Duplicate Invoice Guardrail:** Any claim submitting an `invoice_hash` previously settled or pending in ClaimCenter is immediately escalated as `HIGH` risk for duplicate-billing audit.
