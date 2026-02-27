Directory:
sources/jira

Target number of files:
6000

File name format:
Files for customer-support should be SUP-12345.json with up to 5 digits. Files for internal support should be INT-12345 with up to 5 digits.

Content rules:
- Jira at Redwood Inference is used only for support workflows (not project management).
  - Customer-facing support tickets live under sources/jira/customer-support.
  - Internal support/helpdesk tickets live under sources/jira/internal-support.
- Each document represents exactly one Jira issue.
- Use realistic support-ticket structure and tone:
  - Clear, operationally oriented summaries.
  - Description often follows templates (Issue summary, Impact, Environment, Steps to reproduce, Logs).
  - Comments capture back-and-forth between Support/CS, SRE/Eng, and sometimes the customer.
  - Investigation notes may include hypotheses, partial findings, and links to dashboards/logs.
  - Resolution notes include workaround/fix, rollout notes, and any follow-up items.
- Common issue types:
  - Bug, Support Request, Incident (or Major Incident), Task (support ops), Question
  - Epics/Stories are rare and should generally not be used for planning; prefer operational tickets.
- Common support themes for an LLM inference platform:
  - Latency regressions, timeouts, streaming disconnects
  - 5xx errors, throttling/429s, quota and rate-limit issues
  - Model version pinning, rollouts, fallback routing behavior
  - Dedicated capacity issues: autoscaling, GPU shortages, noisy-neighbor symptoms
  - Private/VPC/on-prem issues: networking (DNS/TLS), IAM/RBAC/SSO, audit logs
  - Usage and billing discrepancies, invoice questions (some routed to finance/legal)
  - Security questionnaires and evidence requests (often tied to security/compliance)
- Cross-references are common and should appear as links or identifiers:
  - Slack threads/channels (e.g., #support, #incidents)
  - GitHub PRs/commits
  - Confluence runbooks, postmortems, and standards
  - Incident identifiers and status page events
- Keep these as support artifacts:
  - More structured than Slack, less polished than Confluence.
  - Do not turn tickets into long-form docs; preserve the ticket-like feel.

Metadata rules:
- Key prefixes / projects:
  - Customer support issues use key prefix SUP- (e.g., SUP-1842)
  - Internal support issues use key prefix INT- (e.g., INT-330)
- Required metadata for every issue:
  - key
  - project: customer-support | internal-support
  - issue_type
  - summary
  - status: e.g., New | Triage | In Progress | Blocked | Waiting on Customer | Resolved | Closed
  - priority: P0 | P1 | P2 | P3 | P4 (or equivalent)
  - created_at (YYYY-MM-DD)
  - updated_at (YYYY-MM-DD)
  - reporter: real Redwood employee name
  - assignee: real Redwood employee name (can be unassigned for new tickets)
- Optional metadata (use frequently where appropriate):
  - severity: Sev0 | Sev1 | Sev2 | Sev3 (common for P0/P1 customer-impacting issues)
  - customer_company (customer-support only)
  - customer_tier: self_serve | dedicated | private | enterprise
  - components: list (e.g., api-gateway, serving-runtime, scheduler, billing, auth, console)
  - labels: list
  - environment: prod | staging plus region (e.g., us-east, eu-west)
  - affected_models: list
  - affected_regions: list
  - sla_due_at / first_response_due_at (customer-support only)
  - linked_issues: list of keys
  - related_incident_id
  - related_github_prs: list
  - related_confluence_pages: list
- Date constraints: updated_at >= created_at.
