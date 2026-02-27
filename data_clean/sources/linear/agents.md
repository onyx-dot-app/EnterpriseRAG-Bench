Directory:
sources/linear

Target number of files:
35000

File name format:
Files should be called the first 3 letters of the team like ABC-12345.json with anywhere from 1 to 5 digits after the team prefix.

Content rules:
- Linear is Redwood Inference’s internal project management system (planning and executing work), used primarily by:
  - engineering
  - product management
  - design
- Each document represents one Linear ticket.
- Comments and updates should reflect real project work:
  - Progress updates, partial decisions, trade-offs
  - Review feedback (PM/Design/Eng), approvals, and follow-up tasks
  - Links to artifacts (PRDs/design specs in Confluence or Drive, GitHub PRs, dashboards, incident learnings)
- Typical Redwood platform themes that appear in Linear work:
  - Serving runtime performance improvements (batching, KV cache, kernel scheduling)
  - Reliability/SLO initiatives and observability enhancements
  - API/SDK features, compatibility layers, structured output
  - Dedicated capacity tooling and autoscaling controls
  - Private/VPC/on-prem deployment features (RBAC, audit logging, upgrades)
  - Console UX improvements (dashboards, rollouts, cost breakdowns)
  - Security & compliance feature work (SSO/SAML, encryption/KMS integrations)

Metadata rules:
- Team directories and key prefixes:
  - sources/linear/engineering issues use key prefix ENG- (e.g., ENG-1842)
  - sources/linear/product-management issues use key prefix PM- (e.g., PM-330)
  - sources/linear/design issues use key prefix DES- (e.g., DES-98)
- Required metadata for every document:
  - key
  - team: engineering | product-management | design
  - title: short natural-language summary
  - status: e.g., Triage | Backlog | Planned | In Progress | In Review | Blocked | Done | Canceled
  - priority: P0 | P1 | P2 | P3 (or equivalent)
  - created_at (YYYY-MM-DD)
  - updated_at (YYYY-MM-DD)
  - creator: real Redwood employee name
  - assignee: real Redwood employee name (or unassigned)
- Optional metadata (use where appropriate):
  - project: project/initiative name
  - cycle: e.g., 2025-W07 or Cycle 41
  - estimate: integer points
  - due_date (YYYY-MM-DD)
  - labels: list
  - parent_issue / sub_issues: list of keys
  - dependencies: list of keys
  - customer_impact: none | low | medium | high
  - release: e.g., runtime-1.18, console-2025.02
  - security_review_required: boolean
- Date constraints: updated_at >= created_at.
