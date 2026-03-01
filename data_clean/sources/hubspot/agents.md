Directory:
sources/hubspot

Target number of files:
15000

File name format:
File names should begin with the literal string "company" + the company name all lowercase connected with dashes (e.g. company-nasa-jet-propulsion-labratory.json).

Content rules:
- This directory represents HubSpot CRM data, with every document representing a prospective or customer company:
  - Each document corresponds to one Company (account) record.
  - The most interesting parts are the user provided notes.
- Company records should be CRM-like and structured rather than long narrative documents.
- Each company record should typically include:
  - Basic firmographics: company name, domain, industry, size band, HQ region, and notes about deployment constraints (cloud/VPC/on-prem).
  - Ownership: account owner (AE) and supporting roles (SE, CSM) where applicable.
  - Stage: one of qualified, discovery, demo, evaluation, procurement.
  - A lightweight timeline of recent activities (bulleted): meetings held, calls, emails, security review steps, POC milestones.
  - Use-case and requirements summary relevant to Redwood Inference:
    - workload type (chat, embeddings, reranking)
    - latency/throughput targets, cost sensitivity
    - model preferences, routing/fallback needs
    - security/compliance needs (SSO/SAML, audit logs, retention, residency)
  - Next steps and blockers (often short, sometimes choppy).
- Notes should feel like real CRM entries:
  - Shorthand, fragments, and bullets are common.
  - Repetition and partial information are normal.
  - Include direct quotes or paraphrases from calls occasionally.
- Include realistic references to linked artifacts as stubs/links (no need to generate full external docs):
  - Fireflies call ids or transcript links
  - Gmail thread ids
  - Drive links (pricing deck, security FAQ)
  - Jira support keys (if the account had escalations)

Metadata rules:
- Required metadata for every company record:
  - company_id: unique-ish identifier
  - company_name
  - company_domain
  - stage: qualified | discovery | demo | evaluation | procurement
  - owner: real Redwood employee name (typically an AE)
  - created_at (YYYY-MM-DD)
  - updated_at (YYYY-MM-DD)
- Optional metadata (use frequently where relevant):
  - account_tier: smb | mid_market | enterprise
  - industry
  - employee_count_range: e.g., 1-50, 51-200, 201-1000, 1000+
  - hq_region: na | eu | apac | latam | other
  - interested_products: hosted_api | dedicated | private | optimize (list)
  - use_cases: list (support-agent, doc-search, code-assistant, summarization, etc.)
  - deployment_requirements: public_cloud | vpc | on_prem | air_gapped
  - security_requirements: list (sso_saml, soc2, iso27001, audit_logging, kms, retention_controls, data_residency)
  - competitors: list
  - forecast_close_month (YYYY-MM)
  - estimated_arr_range
  - se_assigned: name
  - csm_assigned: name (more common for later stages or existing customers)
  - last_activity_at (YYYY-MM-DD)
  - next_step
  - blockers: list
  - linked_fireflies: list of meeting_ids
  - linked_gmail_threads: list of thread_ids
  - linked_drive_docs: list of URLs/paths
  - linked_support_tickets: list of Jira keys
- Date constraints: updated_at >= created_at.
