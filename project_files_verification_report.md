# Project Files Verification Report

**Date:** 2026-02-27
**Total Projects Verified:** 6

## Executive Summary

All 6 projects have issues. Total statistics:
- **Total files across all projects:** 436
- **Missing files:** 37 (8.5%)
- **Naming convention violations:** 87 (20.0%)
- **Projects passing:** 0/6 (0%)

---

## Naming Convention Standards

| Source Type | Pattern | Example |
|-------------|---------|---------|
| confluence | `short-descriptive-dashes.json` | `company-pto-policy-2025.json` |
| fireflies | `YYYY-MM-DD-meeting-title.json` | `2025-01-28-meeting-title.json` |
| github | `pr-NNNN.json` or `pr_NNNN.json` | `pr-1234.json` |
| gmail | `thread[-_]YYYYMMDD[-_]8charhash.json` | `thread-20250321-abc12345.json` |
| google_drive | `short-descriptive-dashes.json` | Must not contain parentheses `()` |
| hubspot | `company_name.json` | `company_nasa_jpl.json` |
| jira | `SUP-NNNNN.json` or `INT-NNNNN.json` | `SUP-12345.json` (up to 5 digits, no extra text) |
| linear | `ABC-NNNNN.json` | `ENG-4921.json` (3+ letter prefix, up to 5 digits) |
| slack | `1234567890.json` | Unix timestamp digits only (10+ digits) |

---

## Project 1: case_study_customer_reference_program

**Status:** ❌ FAIL

**Statistics:**
- Total files: 64
- Missing files: 11
- Naming violations: 19

### Missing Files

1. `sources/gmail/avery_johnson/thread_20250507_arcadia_design-partner_invite.json`
2. `sources/gmail/camila_reyes/thread_20250521_case-study_intake_questions_arcadia.json`
3. `sources/gmail/markus_klein/thread_20250523_arcadia_metrics_validation_followup.json`
4. `sources/gmail/priyom_das/thread_20250524_quantapay_poc_and_case-study_terms.json`
5. `sources/gmail/soojin_lee/thread_20250607_quantapay_case-study_draft_review.json`
6. `sources/gmail/michael_grant/thread_20250610_customer_quote_logo_release_redlines_quantapay.json`
7. `sources/gmail/rachel_kim/thread_20250612_reference-call_process_arcadia_quantapay.json`
8. `sources/gmail/hannah_schmitt/thread_20250614_emEA_reference_candidate_moonlake.json`
9. `sources/github/redwood-docs/pr_842_add-case-studies-section-and-templates.json`
10. `sources/github/redwood-docs/pr_869_publish-arcadia-health-story-draft-private-deployment.json`
11. `sources/github/redwood-quickstarts/pr_311_add-customer-story-links-in-readme.json`

### Naming Convention Violations

**Google Drive (8 violations):** All contain parentheses which violate pattern
- `Reference_Program_Project_Plan_(Draft).json`
- `Design_Partner_Target_List_(Sheet).json`
- `Outreach_Sequences_and_Email_Copy_(Draft).json`
- `Metrics_Validation_Worksheet_(Sheet).json`
- `Arcadia_Health_Case_Study_Outline_(Draft).json`
- `QuantaPay_Case_Study_Outline_(Draft).json`
- `NovaDocs_Case_Study_Outline_(Draft).json`
- `Reference_Call_Prep_One_Pager_(Internal).json`

**Gmail (8 violations):** Missing required 8-character hash
- All 8 gmail files use descriptive names instead of hash format
- Example: `thread_20250507_arcadia_design-partner_invite.json` should be `thread-20250507-a1b2c3d4.json`

**GitHub (3 violations):** Use underscore separator and descriptive suffixes
- `pr_842_add-case-studies-section-and-templates.json` → should be `pr-842.json`
- `pr_869_publish-arcadia-health-story-draft-private-deployment.json` → should be `pr-869.json`
- `pr_311_add-customer-story-links-in-readme.json` → should be `pr-311.json`

---

## Project 2: dedicated_throughput_slo_tier_definitions

**Status:** ❌ FAIL

**Statistics:**
- Total files: 59
- Missing files: 0
- Naming violations: 10

### Naming Convention Violations

**Google Drive (10 violations):** All use hyphens instead of underscores/spaces
- `throughput-slo-kickoff-notes.json`
- `tier-matrix-v1-sheet.json`
- `dedicated-shapes-benchmark-results-sheet.json`
- `throughput-slo-error-budget-simulation.json`
- `dedicated-pricing-sensitivity-analysis.json`
- `dedicated-tier-launch-deck-draft.json`
- `dedicated-slo-customer-comms-drafts.json`
- `throughput-slo-and-tiers-internal-faq.json`
- `dedicated-throughput-metrics-taxonomy.json`
- `open-questions-and-decisions-log.json`

**Note:** Google Drive files should use underscores or spaces, not hyphens. These violate the pattern requirement.

---

## Project 3: hardware_tuning_profiles_pack

**Status:** ❌ FAIL

**Statistics:**
- Total files: 119
- Missing files: 0
- Naming violations: 15

### Naming Convention Violations

**Google Drive (12 violations):** All use hyphens instead of underscores/spaces
- `working-notes-kernel-vs-scheduler-knobs.json`
- `profile-pack-config-draft.json`
- `benchmarks-matrix-v1.json`
- `h100-results-jan-2026.json`
- `l40s-results-jan-2026.json`
- `b200-smoke-results-feb-2026.json`
- `profile-rollout-checklist.json`
- `b200-capacity-and-driver-plan.json`
- `runtime-profile-metrics-map.json`
- `runtime-1-22-profile-pack-release-plan.json`
- `performance-profiles-customer-messaging-draft.json`
- `retro-notes-profile-pack-v1.json`

**HubSpot (3 violations):** Empty company name
- Three instances of `company_.json` (missing company identifier)

---

## Project 4: safe_apply_rollback_mechanism

**Status:** ❌ FAIL

**Statistics:**
- Total files: 65
- Missing files: 17
- Naming violations: 23

### Missing Files (Slack - 17 files)

All missing files are Slack threads with "thread-" prefix instead of timestamp only:
1. `sources/slack/eng-platform/thread-1730741182.json`
2. `sources/slack/product/thread-1730834409.json`
3. `sources/slack/eng-runtime/thread-1730919920.json`
4. `sources/slack/eng-sre/thread-1731005511.json`
5. `sources/slack/eng-security/thread-1731091129.json`
6. `sources/slack/eng-releases/thread-1731177710.json`
7. `sources/slack/architecture/thread-1731263400.json`
8. `sources/slack/incidents/thread-1731349988.json`
9. `sources/slack/eng-oncall/thread-1731351402.json`
10. `sources/slack/eng-platform/thread-1731438809.json`
11. `sources/slack/eng-platform/thread-1731525010.json`
12. `sources/slack/eng-runtime/thread-1731611200.json`
13. `sources/slack/eng-sre/thread-1731697404.json`
14. `sources/slack/eng-platform/thread-1731783622.json`
15. `sources/slack/eng-platform/thread-1731869820.json`
16. `sources/slack/eng-sre/thread-1731956001.json`
17. `sources/slack/announcements/thread-1732042200.json`

### Naming Convention Violations

**Slack (17 violations):** All use "thread-" prefix
- Should be timestamp only: `1730741182.json` not `thread-1730741182.json`

**Google Drive (5 violations):** All use hyphens
- `safe-apply-rollback-working-notes.json`
- `rollback-ux-wire-notes.json`
- `config-change-metric-gates-thresholds-sheet.json`
- `rollback-edge-case-testing-matrix.json`
- `safe-apply-rollout-checklist.json`

**JIRA (1 violation):** Contains description after ticket number
- `SUP-2431-rollback-button-missing-for-dedicated-deployment.json` → should be `SUP-2431.json`

---

## Project 5: incident_taxonomy_ownership_mapping

**Status:** ❌ FAIL

**Statistics:**
- Total files: 62
- Missing files: 9
- Naming violations: 15

### Missing Files

**GitHub (5 files):**
1. `sources/github/incident-bot/pr_218.json`
2. `sources/github/incident-bot/pr_223.json`
3. `sources/github/slo-toolkit/pr_97.json`
4. `sources/github/observability-pack/pr_311.json`
5. `sources/github/redwood/pr_10421.json`

**Gmail (4 files):**
1. `sources/gmail/neha_kapoor/thread_2025_02_03_incident_taxonomy_sla_signoff.json`
2. `sources/gmail/ava_chen/thread_2025_02_06_exec_update_incident_taxonomy.json`
3. `sources/gmail/dev_patel/thread_2025_02_10_support_playbook_alignment.json`
4. `sources/gmail/marissa_cole/thread_2025_02_12_console_dashboard_requirements.json`

### Naming Convention Violations

**Google Drive (6 violations):** All use hyphens
- `incident-taxonomy-working-notes.json`
- `incident-inventory-and-clustering-sheet.json`
- `ownership-map-services-sheet.json`
- `incident-tagging-pipeline-spike.json`
- `capacity-related-incident-categories.json`
- `incident-sla-and-comms-alignment.json`

**GitHub (5 violations):** Use underscore separator
- All should use hyphen: `pr-218.json` not `pr_218.json`

**Gmail (4 violations):** Use descriptive names instead of hash format
- Example: `thread_2025_02_03_incident_taxonomy_sla_signoff.json` should be `thread-20250203-a1b2c3d4.json`

---

## Project 6: private_observability_minimum_pack

**Status:** ❌ FAIL

**Statistics:**
- Total files: 67
- Missing files: 0
- Naming violations: 5

### Naming Convention Violations

**Google Drive (5 violations):**

1. `Private Observability Min Pack - Working Spec (Draft).json` - Contains spaces and parentheses
2. `private-min-pack-alert-noise-review-sheet.json` - Uses hyphens
3. `onprem-airgap-test-plan-observability-pack.json` - Uses hyphens
4. `private-observability-min-pack-prd-draft.json` - Uses hyphens
5. `private-min-pack-dashboard-wireframes.json` - Uses hyphens

---

## Common Issues by Source Type

### 1. **Google Drive** (Most common violations: 47 total)
- **Issue:** Files use hyphens (`-`) instead of underscores (`_`) or spaces
- **Pattern expected:** `[A-Za-z0-9_]+(\s+[A-Za-z0-9_]+)*\.json`
- **Files should NOT contain:**
  - Hyphens within names
  - Parentheses `()`

### 2. **Gmail** (16 violations)
- **Issue:** Files use descriptive names instead of required hash format
- **Pattern expected:** `thread[-_]YYYYMMDD[-_]8charhash.json`
- **Example:** `thread-20250507-a1b2c3d4.json`
- **Common mistake:** `thread_20250507_descriptive_name.json` (missing hash, too descriptive)

### 3. **Slack** (17 violations)
- **Issue:** Files include "thread-" prefix before timestamp
- **Pattern expected:** Just timestamp digits `1234567890.json`
- **Common mistake:** `thread-1730741182.json` should be `1730741182.json`

### 4. **GitHub** (11 violations)
- **Issue 1:** Using underscore instead of hyphen separator
  - Wrong: `pr_842.json`
  - Right: `pr-842.json` or `pr842.json`
- **Issue 2:** Including descriptive suffixes
  - Wrong: `pr_842_add-case-studies-section-and-templates.json`
  - Right: `pr-842.json`

### 5. **JIRA** (1 violation)
- **Issue:** Including description after ticket number
- **Pattern expected:** `(SUP|INT)-\d{1,5}\.json`
- **Wrong:** `SUP-2431-rollback-button-missing-for-dedicated-deployment.json`
- **Right:** `SUP-2431.json`

### 6. **HubSpot** (3 violations)
- **Issue:** Empty company identifier
- **Pattern expected:** `company_[a-z0-9_]+\.json`
- **Wrong:** `company_.json`
- **Right:** `company_acme_corp.json`

---

## Recommendations

### Immediate Actions Required:

1. **Create missing files** (37 files total):
   - 11 files in case_study_customer_reference_program
   - 17 files in safe_apply_rollback_mechanism
   - 9 files in incident_taxonomy_ownership_mapping

2. **Rename files violating conventions** (87 files total):
   - Focus on Google Drive files (47 violations) - replace hyphens with underscores
   - Fix Gmail files (16 violations) - use proper hash format
   - Fix Slack files (17 violations) - remove "thread-" prefix
   - Fix GitHub files (11 violations) - use hyphen separator, remove descriptions

### Systematic Fixes:

**For Google Drive:**
```bash
# Replace hyphens with underscores
mv "throughput-slo-kickoff-notes.json" "throughput_slo_kickoff_notes.json"
```

**For Slack:**
```bash
# Remove "thread-" prefix
mv "thread-1730741182.json" "1730741182.json"
```

**For Gmail:**
```bash
# Need to regenerate with proper hash
mv "thread_20250507_arcadia_design-partner_invite.json" "thread-20250507-a1b2c3d4.json"
```

**For GitHub:**
```bash
# Simplify to just PR number
mv "pr_842_add-case-studies-section-and-templates.json" "pr-842.json"
```

**For JIRA:**
```bash
# Remove descriptive suffix
mv "SUP-2431-rollback-button-missing-for-dedicated-deployment.json" "SUP-2431.json"
```

---

## Impact Assessment

**Data Quality:** 20% of files have naming issues, 8.5% of files are missing entirely. This could impact:
- Automated data pipeline processing
- Search and retrieval operations
- Cross-reference validation
- Documentation generation

**Priority:** HIGH - These issues should be resolved before any production deployment or automated processing of this dataset.

---

## Validation Script

A Python validation script has been created at:
`/Users/yuhongsun/Projects/IndustryRAG-Dataset/verify_project_files.py`

Run with:
```bash
python verify_project_files.py
```

This script checks both file existence and naming convention compliance for all 6 projects.
