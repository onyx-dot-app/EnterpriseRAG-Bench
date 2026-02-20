Directory:
sources/confluence

Target number of files:
5000

Content rules:
- Confluence is Redwood Inference’s formal internal documentation system.
- Documents should read like polished, broadly consumable references (not personal scratchpads). Write in complete sentences with clear structure.
- Use standard Confluence-style organization: headings, short intro, bulleted lists, numbered procedures, tables for configs/requirements, and clearly labeled sections.
- Typical doc types include:
  - Architecture overviews and subsystem docs
  - Engineering standards (API, infra, observability, performance, model-serving)
  - Decision records (ADRs) and design reviews
  - Runbooks and operational playbooks
  - Incident review summaries and reliability initiatives
  - Product docs (PRDs, roadmaps, pricing/packaging notes, release notes)
  - Security/compliance policies and evidence procedures
  - Company handbook / HR policies
  - Customer success processes, enablement, and escalation playbooks
- Keep tone professional and internally oriented. Avoid highly speculative content.
- Include concrete details where appropriate: service names, SLOs, thresholds, rollout steps, ownership, and links/references to related pages.
- It’s OK to include code snippets, CLI commands, JSON/YAML examples, and diagrams described in text.
- Avoid “meeting notes” style content here; place team notes/scratchpads in Google Drive instead.

Metadata rules:
- Every document must include:
  - title
  - space: one of the Confluence top areas reflected by subdirectories (e.g., eng-sre, eng-serving-runtime, security-and-compliance, company-handbook, product-docs)
  - author: a real Redwood employee name
  - owner_team: engineering/product/security/people-ops/finance-legal/customer-success/go-to-market
  - status: draft | in_review | published
  - created_at (YYYY-MM-DD)
  - last_updated (YYYY-MM-DD)
- Optional fields:
  - reviewers (list of names)
  - labels (0–8 short tags)
  - related_pages (list of internal links/ids)
  - confidentiality: internal (default) | restricted (security/legal/customer-sensitive)
- Dates should be plausible (spanning multiple years) and last_updated should be >= created_at.
