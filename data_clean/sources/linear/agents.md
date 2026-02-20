Directory:
sources/linear

Target number of files:
35000

Content rules:
- Linear is Redwood Inference’s internal project management system (planning and executing work), used primarily by:
  - engineering
  - product management
  - design
- Each document represents one Linear ticket.
- Compared to Jira/Slack, Linear issues are more execution-oriented and better structured:
  - Clear problem statement and context
  - Goals and non-goals
  - Scope and constraints
  - Acceptance criteria / definition of done
  - Implementation notes and open questions
  - Testing plan and rollout/release plan (feature flags, canary, monitoring)
  - Risks, dependencies, and mitigation plans
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
- Use realistic planning constructs:
  - Projects/Initiatives group multiple issues.
  - Cycles/sprints may be referenced for scheduling.
  - Estimates and priorities are commonly used.

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
- Optional metadata (use frequently where appropriate):
  - project: project/initiative name
  - cycle: e.g., 2025-W07 or Cycle 41
  - estimate: integer points
  - due_date (YYYY-MM-DD)
  - labels: list
  - parent_issue / sub_issues: list of keys
  - dependencies: list of keys
  - links: list of URLs/ids (GitHub PRs, Confluence pages, Drive docs, dashboards)
  - customer_impact: none | low | medium | high
  - release: e.g., runtime-1.18, console-2025.02
  - security_review_required: boolean
- Date constraints: updated_at >= created_at.
