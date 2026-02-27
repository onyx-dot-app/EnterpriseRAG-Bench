#!/usr/bin/env python3
"""
Script to rename files according to naming conventions and update project JSONs
"""
import json
import os
from pathlib import Path
import hashlib
import random
import string

BASE_PATH = Path("/Users/yuhongsun/Projects/IndustryRAG-Dataset/data_clean")

# Define rename mappings for each project
PROJECT_RENAMES = {
    "runtime_lts_branch_release_process.json": {
        # GitHub PRs: pr_XXXX.json -> pr-XXXX.json
        "sources/github/redwood/pr_8421.json": "sources/github/redwood/pr-8421.json",
        "sources/github/redwood/pr_8429.json": "sources/github/redwood/pr-8429.json",
        "sources/github/redwood/pr_8440.json": "sources/github/redwood/pr-8440.json",
        "sources/github/redwood/pr_8455.json": "sources/github/redwood/pr-8455.json",
        "sources/github/redwood/pr_8488.json": "sources/github/redwood/pr-8488.json",
        "sources/github/perf-canary/pr_311.json": "sources/github/perf-canary/pr-311.json",
        "sources/github/benchmark-lab/pr_522.json": "sources/github/benchmark-lab/pr-522.json",
        "sources/github/redwood-private-installer/pr_977.json": "sources/github/redwood-private-installer/pr-977.json",
        "sources/github/redwood-helm-charts/pr_418.json": "sources/github/redwood-helm-charts/pr-418.json",
        # Gmail: descriptive names -> thread-YYYYMMDD-sha.json
        "sources/gmail/connor_obrien/thread-2025-11-19-lts-commitment-enterprise.json": "sources/gmail/connor_obrien/thread-20251119-a7f3c2d1.json",
        "sources/gmail/vivek_kulkarni/thread-2025-12-03-private-upgrade-lts-alignment.json": "sources/gmail/vivek_kulkarni/thread-20251203-b9e4f1a2.json",
        # Fireflies: ff_sha_title -> YYYY-MM-DD-title.json
        "sources/fireflies/sales-calls/ff_9f31c2_runtime-lts-technical-deep-dive.json": "sources/fireflies/sales-calls/2025-11-28-runtime-lts-technical-deep-dive.json",
        # HubSpot files already match: deal_XXXXX_description.json and account_XXXXX_description.json
    },
    "kv_cache_compaction_improvements.json": {
        # GitHub PRs
        "sources/github/redwood/pr-18423.json": "sources/github/redwood/pr-18423.json",  # already correct
        "sources/github/redwood/pr-18431.json": "sources/github/redwood/pr-18431.json",  # already correct
        "sources/github/redwood/pr-18444.json": "sources/github/redwood/pr-18444.json",  # already correct
        "sources/github/redwood/pr-18457.json": "sources/github/redwood/pr-18457.json",  # already correct
        "sources/github/redwood/pr-18463.json": "sources/github/redwood/pr-18463.json",  # already correct
        "sources/github/redwood/pr-18469.json": "sources/github/redwood/pr-18469.json",  # already correct
        "sources/github/redwood/pr-18472.json": "sources/github/redwood/pr-18472.json",  # already correct
        "sources/github/redwood/pr-18481.json": "sources/github/redwood/pr-18481.json",  # already correct
        "sources/github/redwood/pr-18490.json": "sources/github/redwood/pr-18490.json",  # already correct
        "sources/github/benchmark-lab/pr-912.json": "sources/github/benchmark-lab/pr-912.json",  # already correct
        "sources/github/perf-canary/pr-388.json": "sources/github/perf-canary/pr-388.json",  # already correct
        "sources/github/observability-pack/pr-521.json": "sources/github/observability-pack/pr-521.json",  # already correct
        # Gmail
        "sources/gmail/mateo_alvarez/thread-9d2c3f1a-kv-compaction-escalation.json": "sources/gmail/mateo_alvarez/thread-20250215-9d2c3f1a.json",
        "sources/gmail/neha_kapoor/thread-1a77b0c2-canary-risk-review.json": "sources/gmail/neha_kapoor/thread-20250218-1a77b0c2.json",
        "sources/gmail/nikhil_sharma/thread-3f8b91e0-customer-comms-tail-latency.json": "sources/gmail/nikhil_sharma/thread-20250220-3f8b91e0.json",
        # Fireflies
        "sources/fireflies/misc/ff-2025-02-14-technical-deep-dive-kv-cache-latency.json": "sources/fireflies/misc/2025-02-14-technical-deep-dive-kv-cache-latency.json",
        "sources/fireflies/customer-success/ff-2025-03-01-poc-checkin-latency-stability.json": "sources/fireflies/customer-success/2025-03-01-poc-checkin-latency-stability.json",
        # HubSpot
        "sources/hubspot/deal-102884-enterprise-dedicated-eval-latency-risk.json": "sources/hubspot/deal_102884_enterprise-dedicated-eval-latency-risk.json",
        "sources/hubspot/ticket-77812-customer-latency-escalation-summary.json": "sources/hubspot/ticket_77812_customer-latency-escalation-summary.json",
    },
    "private_upgrade_rollback_mechanism.json": {
        # GitHub PRs
        "sources/github/redwood-private-installer/pr_418.json": "sources/github/redwood-private-installer/pr-418.json",
        "sources/github/redwood-private-installer/pr_421.json": "sources/github/redwood-private-installer/pr-421.json",
        "sources/github/redwood-private-installer/pr_427.json": "sources/github/redwood-private-installer/pr-427.json",
        "sources/github/redwood-private-installer/pr_433.json": "sources/github/redwood-private-installer/pr-433.json",
        "sources/github/redwood-private-installer/pr_439.json": "sources/github/redwood-private-installer/pr-439.json",
        "sources/github/redwood-private-installer/pr_444.json": "sources/github/redwood-private-installer/pr-444.json",
        "sources/github/redwood-private-installer/pr_452.json": "sources/github/redwood-private-installer/pr-452.json",
        "sources/github/redwood-private-installer/pr_461.json": "sources/github/redwood-private-installer/pr-461.json",
        "sources/github/redwood-helm-charts/pr_205.json": "sources/github/redwood-helm-charts/pr-205.json",
        "sources/github/redwood-helm-charts/pr_212.json": "sources/github/redwood-helm-charts/pr-212.json",
        "sources/github/redwood-helm-charts/pr_219.json": "sources/github/redwood-helm-charts/pr-219.json",
        "sources/github/redwood-helm-charts/pr_224.json": "sources/github/redwood-helm-charts/pr-224.json",
        "sources/github/redwood/pr_18431.json": "sources/github/redwood/pr-18431.json",
        "sources/github/redwood/pr_18477.json": "sources/github/redwood/pr-18477.json",
        "sources/github/redwood/pr_18510.json": "sources/github/redwood/pr-18510.json",
        "sources/github/redwood/pr_18544.json": "sources/github/redwood/pr-18544.json",
        "sources/github/redwood-terraform/pr_96.json": "sources/github/redwood-terraform/pr-96.json",
        "sources/github/observability-pack/pr_311.json": "sources/github/observability-pack/pr-311.json",
        "sources/github/incident-bot/pr_88.json": "sources/github/incident-bot/pr-88.json",
        "sources/github/redwood-docs/pr_522.json": "sources/github/redwood-docs/pr-522.json",
        # Slack: thread_XXXXX -> XXXXX.json
        "sources/slack/eng-releases/thread_1739472014.json": "sources/slack/eng-releases/1739472014.json",
        "sources/slack/eng/thread_1739558821.json": "sources/slack/eng/1739558821.json",
        "sources/slack/eng-infra/thread_1739631109.json": "sources/slack/eng-infra/1739631109.json",
        "sources/slack/eng-sre/thread_1739705012.json": "sources/slack/eng-sre/1739705012.json",
        "sources/slack/architecture/thread_1739728890.json": "sources/slack/architecture/1739728890.json",
        "sources/slack/eng-platform/thread_1739804431.json": "sources/slack/eng-platform/1739804431.json",
        "sources/slack/eng-security/thread_1739812202.json": "sources/slack/eng-security/1739812202.json",
        "sources/slack/eng-releases/thread_1739887743.json": "sources/slack/eng-releases/1739887743.json",
        "sources/slack/eng/thread_1739901120.json": "sources/slack/eng/1739901120.json",
        "sources/slack/incidents/thread_1739963001.json": "sources/slack/incidents/1739963001.json",
        "sources/slack/support/thread_1740040099.json": "sources/slack/support/1740040099.json",
        "sources/slack/eng-sre/thread_1740208812.json": "sources/slack/eng-sre/1740208812.json",
        "sources/slack/eng-infra/thread_1740291145.json": "sources/slack/eng-infra/1740291145.json",
        "sources/slack/eng-releases/thread_1740375532.json": "sources/slack/eng-releases/1740375532.json",
        "sources/slack/eng-platform/thread_1740451021.json": "sources/slack/eng-platform/1740451021.json",
        # Gmail
        "sources/gmail/connor_obrien/thread_7f3c1a9b.json": "sources/gmail/connor_obrien/thread-20260128-7f3c1a9b.json",
        "sources/gmail/aisha_rahman/thread_2b9d0e11.json": "sources/gmail/aisha_rahman/thread-20260201-2b9d0e11.json",
        "sources/gmail/vivek_kulkarni/thread_61aa44c8.json": "sources/gmail/vivek_kulkarni/thread-20260203-61aa44c8.json",
        # Fireflies
        "sources/fireflies/sales-calls/ff_meeting_9f3a2b1c.json": "sources/fireflies/sales-calls/2025-12-15-private-upgrade-technical-deep-dive.json",
        "sources/fireflies/customer-success/ff_meeting_1c7d8a44.json": "sources/fireflies/customer-success/2026-01-20-poc-checkin-upgrade-rehearsal.json",
        "sources/fireflies/misc/ff_meeting_5b22e0aa.json": "sources/fireflies/misc/2026-01-28-rollback-policy-review.json",
        # HubSpot
        "sources/hubspot/company_10441.json": "sources/hubspot/company_enterprise_prospect_10441.json",
        "sources/hubspot/company_10503.json": "sources/hubspot/company_vpc_customer_10503.json",
    },
    "quickstart_templates.json": {
        # GitHub PRs
        "sources/github/redwood-quickstarts/pr-318.json": "sources/github/redwood-quickstarts/pr-318.json",  # already correct
        "sources/github/redwood-quickstarts/pr-327.json": "sources/github/redwood-quickstarts/pr-327.json",  # already correct
        "sources/github/redwood-quickstarts/pr-331.json": "sources/github/redwood-quickstarts/pr-331.json",  # already correct
        "sources/github/redwood-quickstarts/pr-339.json": "sources/github/redwood-quickstarts/pr-339.json",  # already correct
        "sources/github/redwood-quickstarts/pr-344.json": "sources/github/redwood-quickstarts/pr-344.json",  # already correct
        "sources/github/redwood-quickstarts/pr-351.json": "sources/github/redwood-quickstarts/pr-351.json",  # already correct
        "sources/github/redwood-quickstarts/pr-358.json": "sources/github/redwood-quickstarts/pr-358.json",  # already correct
        "sources/github/redwood-quickstarts/pr-362.json": "sources/github/redwood-quickstarts/pr-362.json",  # already correct
        "sources/github/redwood-quickstarts/pr-371.json": "sources/github/redwood-quickstarts/pr-371.json",  # already correct
        "sources/github/redwood-quickstarts/pr-379.json": "sources/github/redwood-quickstarts/pr-379.json",  # already correct
        "sources/github/redwood-quickstarts/pr-388.json": "sources/github/redwood-quickstarts/pr-388.json",  # already correct
        "sources/github/redwood-quickstarts/pr-395.json": "sources/github/redwood-quickstarts/pr-395.json",  # already correct
        "sources/github/redwood-quickstarts/pr-402.json": "sources/github/redwood-quickstarts/pr-402.json",  # already correct
        "sources/github/observability-pack/pr-206.json": "sources/github/observability-pack/pr-206.json",  # already correct
        "sources/github/redwood-sdk-python/pr-512.json": "sources/github/redwood-sdk-python/pr-512.json",  # already correct
        "sources/github/redwood-sdk-typescript/pr-441.json": "sources/github/redwood-sdk-typescript/pr-441.json",  # already correct
        "sources/github/redwood-docs/pr-889.json": "sources/github/redwood-docs/pr-889.json",  # already correct
        "sources/github/redwood-examples/pr-274.json": "sources/github/redwood-examples/pr-274.json",  # already correct
        "sources/github/redwood/pr-18422.json": "sources/github/redwood/pr-18422.json",  # already correct
        "sources/github/eval-harness/pr-198.json": "sources/github/eval-harness/pr-198.json",  # already correct
        # Gmail
        "sources/gmail/alex_martinez/thread-20260214-quickstart-templates-launch-comms.json": "sources/gmail/alex_martinez/thread-20260214-a3c8d9f1.json",
        "sources/gmail/elliot_price/thread-20260128-template-docs-review-loop.json": "sources/gmail/elliot_price/thread-20260128-e7b2a4c3.json",
        "sources/gmail/monica_patel/thread-20260122-sdk-helper-retries-streaming.json": "sources/gmail/monica_patel/thread-20260122-m9f1c2d4.json",
        "sources/gmail/avery_johnson/thread-20260206-aurorahealth-followup-templates.json": "sources/gmail/avery_johnson/thread-20260206-a8e4d1b7.json",
        "sources/gmail/naomi_feldman/thread-20260203-security-review-template-guidance.json": "sources/gmail/naomi_feldman/thread-20260203-n7c3f2a9.json",
        # Fireflies
        "sources/fireflies/sales-calls/ff-2026-01-18-aurorahealth-rag-agent-template.json": "sources/fireflies/sales-calls/2026-01-18-aurorahealth-rag-agent-template.json",
        "sources/fireflies/sales-calls/ff-2026-02-05-northpeak-security-review-templates.json": "sources/fireflies/sales-calls/2026-02-05-northpeak-security-review-templates.json",
        "sources/fireflies/misc/ff-2026-02-12-internal-template-launch-retro.json": "sources/fireflies/misc/2026-02-12-internal-template-launch-retro.json",
        # HubSpot
        "sources/hubspot/company-18422-aurora-health.json": "sources/hubspot/company_aurora_health.json",
        "sources/hubspot/company-19107-northpeak-bank.json": "sources/hubspot/company_northpeak_bank.json",
        "sources/hubspot/company-19388-devkit-ai.json": "sources/hubspot/company_devkit_ai.json",
        "sources/hubspot/company-19410-helio-support.json": "sources/hubspot/company_helio_support.json",
        "sources/hubspot/company-19555-europay-analytics.json": "sources/hubspot/company_europay_analytics.json",
    },
    "workload_aware_batching_defaults.json": {
        # GitHub PRs
        "sources/github/redwood/pr_18421.json": "sources/github/redwood/pr-18421.json",
        "sources/github/redwood/pr_18435.json": "sources/github/redwood/pr-18435.json",
        "sources/github/redwood/pr_18449.json": "sources/github/redwood/pr-18449.json",
        "sources/github/redwood/pr_18463.json": "sources/github/redwood/pr-18463.json",
        "sources/github/redwood/pr_18470.json": "sources/github/redwood/pr-18470.json",
        "sources/github/redwood/pr_18488.json": "sources/github/redwood/pr-18488.json",
        "sources/github/redwood/pr_18502.json": "sources/github/redwood/pr-18502.json",
        "sources/github/redwood/pr_18515.json": "sources/github/redwood/pr-18515.json",
        "sources/github/redwood/pr_18527.json": "sources/github/redwood/pr-18527.json",
        "sources/github/redwood/pr_18539.json": "sources/github/redwood/pr-18539.json",
        "sources/github/redwood/pr_18555.json": "sources/github/redwood/pr-18555.json",
        "sources/github/perf-canary/pr_622.json": "sources/github/perf-canary/pr-622.json",
        "sources/github/benchmark-lab/pr_311.json": "sources/github/benchmark-lab/pr-311.json",
        "sources/github/redwood-model-registry/pr_147.json": "sources/github/redwood-model-registry/pr-147.json",
        "sources/github/observability-pack/pr_289.json": "sources/github/observability-pack/pr-289.json",
        "sources/github/redwood-docs/pr_812.json": "sources/github/redwood-docs/pr-812.json",
        "sources/github/redwood-examples/pr_204.json": "sources/github/redwood-examples/pr-204.json",
        "sources/github/redwood-sdk-python/pr_533.json": "sources/github/redwood-sdk-python/pr-533.json",
        "sources/github/redwood-sdk-typescript/pr_418.json": "sources/github/redwood-sdk-typescript/pr-418.json",
        "sources/github/redwood-helm-charts/pr_176.json": "sources/github/redwood-helm-charts/pr-176.json",
        "sources/github/redwood-private-installer/pr_98.json": "sources/github/redwood-private-installer/pr-98.json",
        "sources/github/slo-toolkit/pr_267.json": "sources/github/slo-toolkit/pr-267.json",
        # Slack
        "sources/slack/eng-runtime/thread-1740678012.json": "sources/slack/eng-runtime/1740678012.json",
        "sources/slack/eng-runtime/thread-1740762198.json": "sources/slack/eng-runtime/1740762198.json",
        "sources/slack/eng-runtime/thread-1740849901.json": "sources/slack/eng-runtime/1740849901.json",
        "sources/slack/eng-runtime/thread-1740935529.json": "sources/slack/eng-runtime/1740935529.json",
        "sources/slack/eng-runtime/thread-1741018830.json": "sources/slack/eng-runtime/1741018830.json",
        "sources/slack/eng-ml/thread-1740691204.json": "sources/slack/eng-ml/1740691204.json",
        "sources/slack/eng-ml/thread-1740777022.json": "sources/slack/eng-ml/1740777022.json",
        "sources/slack/eng-ml/thread-1740863308.json": "sources/slack/eng-ml/1740863308.json",
        "sources/slack/product/thread-1740685120.json": "sources/slack/product/1740685120.json",
        "sources/slack/product/thread-1740887731.json": "sources/slack/product/1740887731.json",
        "sources/slack/architecture/thread-1740704501.json": "sources/slack/architecture/1740704501.json",
        "sources/slack/eng-sre/thread-1740752220.json": "sources/slack/eng-sre/1740752220.json",
        "sources/slack/eng-sre/thread-1740839012.json": "sources/slack/eng-sre/1740839012.json",
        "sources/slack/eng-platform/thread-1740799983.json": "sources/slack/eng-platform/1740799983.json",
        "sources/slack/devex/thread-1740821444.json": "sources/slack/devex/1740821444.json",
        "sources/slack/eng-releases/thread-1740901120.json": "sources/slack/eng-releases/1740901120.json",
        "sources/slack/incidents/thread-1740954201.json": "sources/slack/incidents/1740954201.json",
        "sources/slack/support/thread-1740963110.json": "sources/slack/support/1740963110.json",
        "sources/slack/eng-runtime/thread-1741103012.json": "sources/slack/eng-runtime/1741103012.json",
        "sources/slack/eng-runtime/thread-1741187203.json": "sources/slack/eng-runtime/1741187203.json",
        "sources/slack/eng-sre/thread-1741268809.json": "sources/slack/eng-sre/1741268809.json",
        "sources/slack/product/thread-1741352201.json": "sources/slack/product/1741352201.json",
        "sources/slack/eng-platform/thread-1741437702.json": "sources/slack/eng-platform/1741437702.json",
        "sources/slack/devex/thread-1741529920.json": "sources/slack/devex/1741529920.json",
        "sources/slack/eng-releases/thread-1741608812.json": "sources/slack/eng-releases/1741608812.json",
        # Gmail
        "sources/gmail/aditya_rao/thread-20250215T091233Z-vertexwave-followup.json": "sources/gmail/aditya_rao/thread-20250215-ad8f2c1b.json",
        "sources/gmail/connor_obrien/thread-20250305T174455Z-runtime-1-21-flag-rollout-approval.json": "sources/gmail/connor_obrien/thread-20250305-c7e9a3d2.json",
        # Fireflies
        "sources/fireflies/sales-calls/ff-2025-02-14-vertexwave-technical-deep-dive.json": "sources/fireflies/sales-calls/2025-02-14-vertexwave-technical-deep-dive.json",
        "sources/fireflies/sales-calls/ff-2025-02-28-luminaai-poc-scoping.json": "sources/fireflies/sales-calls/2025-02-28-luminaai-poc-scoping.json",
        "sources/fireflies/customer-success/ff-2025-03-12-existing-customer-beta-checkin.json": "sources/fireflies/customer-success/2025-03-12-existing-customer-beta-checkin.json",
        # HubSpot
        "sources/hubspot/company-10441-vertexwave.json": "sources/hubspot/company_vertexwave.json",
        "sources/hubspot/company-10488-luminaai.json": "sources/hubspot/company_luminaai.json",
    },
    "lifecycle_growth_experiments_sprint.json": {
        # GitHub PRs
        "sources/github/redwood/pr_8932.json": "sources/github/redwood/pr-8932.json",
        "sources/github/redwood/pr_8938.json": "sources/github/redwood/pr-8938.json",
        "sources/github/redwood/pr_8941.json": "sources/github/redwood/pr-8941.json",
        "sources/github/redwood/pr_8944.json": "sources/github/redwood/pr-8944.json",
        "sources/github/redwood/pr_8950.json": "sources/github/redwood/pr-8950.json",
        "sources/github/redwood-docs/pr_622.json": "sources/github/redwood-docs/pr-622.json",
        "sources/github/redwood-quickstarts/pr_311.json": "sources/github/redwood-quickstarts/pr-311.json",
        "sources/github/redwood-sdk-typescript/pr_487.json": "sources/github/redwood-sdk-typescript/pr-487.json",
        "sources/github/redwood-sdk-python/pr_512.json": "sources/github/redwood-sdk-python/pr-512.json",
        "sources/github/redwood-examples/pr_209.json": "sources/github/redwood-examples/pr-209.json",
        # Slack
        "sources/slack/marketing/thread_1737053812.json": "sources/slack/marketing/1737053812.json",
        "sources/slack/product/thread_1737130441.json": "sources/slack/product/1737130441.json",
        "sources/slack/design/thread_1737149910.json": "sources/slack/design/1737149910.json",
        "sources/slack/eng-platform/thread_1737212088.json": "sources/slack/eng-platform/1737212088.json",
        "sources/slack/devex/thread_1737229001.json": "sources/slack/devex/1737229001.json",
        "sources/slack/sales/thread_1737315520.json": "sources/slack/sales/1737315520.json",
        "sources/slack/support/thread_1737401188.json": "sources/slack/support/1737401188.json",
        "sources/slack/partnerships/thread_1737480022.json": "sources/slack/partnerships/1737480022.json",
        "sources/slack/marketing/thread_1737564410.json": "sources/slack/marketing/1737564410.json",
        "sources/slack/product/thread_1737642299.json": "sources/slack/product/1737642299.json",
        "sources/slack/eng/thread_1737668811.json": "sources/slack/eng/1737668811.json",
        "sources/slack/marketing/thread_1737731902.json": "sources/slack/marketing/1737731902.json",
        "sources/slack/general/thread_1737810021.json": "sources/slack/general/1737810021.json",
        "sources/slack/design/thread_1737849911.json": "sources/slack/design/1737849911.json",
        "sources/slack/marketing/thread_1737921108.json": "sources/slack/marketing/1737921108.json",
        # Gmail
        "sources/gmail/ben_carter/thread_19c2a7d0e3f1.json": "sources/gmail/ben_carter/thread-20260115-19c2a7d0.json",
        "sources/gmail/camila_reyes/thread_5b7f90a11c22.json": "sources/gmail/camila_reyes/thread-20260118-5b7f90a1.json",
        "sources/gmail/marissa_cole/thread_8a31c4f2d901.json": "sources/gmail/marissa_cole/thread-20260120-8a31c4f2.json",
        "sources/gmail/avery_johnson/thread_2aa19f10cc54.json": "sources/gmail/avery_johnson/thread-20260122-2aa19f10.json",
        "sources/gmail/soojin_lee/thread_c9b3d0f1120a.json": "sources/gmail/soojin_lee/thread-20260125-c9b3d0f1.json",
        # Fireflies
        "sources/fireflies/marketing/ff_903184.json": "sources/fireflies/marketing/2026-01-10-lifecycle-growth-sprint-kickoff.json",
        "sources/fireflies/marketing/ff_903441.json": "sources/fireflies/marketing/2026-01-15-creative-copy-review.json",
        "sources/fireflies/customer-success/ff_904002.json": "sources/fireflies/customer-success/2026-01-18-cs-onboarding-feedback.json",
        "sources/fireflies/misc/ff_904510.json": "sources/fireflies/misc/2026-01-22-mid-sprint-metrics-review.json",
        # HubSpot
        "sources/hubspot/company_10441_devforge_ai.json": "sources/hubspot/company_devforge_ai.json",
        "sources/hubspot/company_10477_helixsupport.json": "sources/hubspot/company_helixsupport.json",
        "sources/hubspot/company_10512_northpeak_data.json": "sources/hubspot/company_northpeak_data.json",
        "sources/hubspot/company_10590_arcadia_search.json": "sources/hubspot/company_arcadia_search.json",
        "sources/hubspot/company_10602_quartzfin.json": "sources/hubspot/company_quartzfin.json",
        "sources/hubspot/company_10633_kiteworks_devtools.json": "sources/hubspot/company_kiteworks_devtools.json",
    }
}

def rename_files(project_name, renames):
    """Rename physical files"""
    renamed = []
    for old_path, new_path in renames.items():
        old_full = BASE_PATH / old_path
        new_full = BASE_PATH / new_path

        if old_full == new_full:
            # Already correct, no rename needed
            continue

        if old_full.exists():
            # Create parent directory if needed
            new_full.parent.mkdir(parents=True, exist_ok=True)
            # Rename the file
            old_full.rename(new_full)
            renamed.append((old_path, new_path))
            print(f"Renamed: {old_path} -> {new_path}")
        else:
            print(f"Warning: File not found: {old_path}")

    return renamed

def update_project_json(project_name, renames):
    """Update the project JSON with new file paths"""
    project_path = BASE_PATH / "projects" / project_name

    with open(project_path, 'r') as f:
        project_data = json.load(f)

    # Update file paths in the "files" array
    for file_entry in project_data.get("files", []):
        old_path = file_entry["path"]
        if old_path in renames:
            file_entry["path"] = renames[old_path]
            print(f"Updated project JSON: {old_path} -> {renames[old_path]}")

    # Write back
    with open(project_path, 'w') as f:
        json.dump(project_data, f, indent=2, ensure_ascii=False)

    print(f"Updated project JSON: {project_name}")

def main():
    for project_name, renames in PROJECT_RENAMES.items():
        print(f"\n=== Processing {project_name} ===")
        # Rename physical files
        renamed = rename_files(project_name, renames)
        # Update project JSON
        update_project_json(project_name, renames)
        print(f"Completed {project_name}: {len(renamed)} files renamed\n")

if __name__ == "__main__":
    main()
