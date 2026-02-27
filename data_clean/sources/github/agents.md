Directory:
sources/github

Target number of files:
8000

File name format:
The files should be called pr-1234.json where "pr-" is always the same and followed by a few digits and ending with .json.

Content rules:
- This directory represents GitHub artifacts, modeled as pull requests (PRs).
- Each document corresponds to exactly one pull request.
- Repository distribution:
  - Redwood Inference is mostly a monorepo; the vast majority of PRs should be in the `redwood` repository.
  - Other repositories exist (SDKs, docs, tooling), but together they represent a minority of PRs.
- PR content should look like realistic GitHub PR pages:
  - Title and description (often includes checklists and links)
  - The description should be a single continuous string even when there are sections
  - A list/summary of commits (can be high-level)
  - Changed areas/files listed at a high level (do not generate huge diffs; include small illustrative snippets only when useful)
  - Review conversation: reviewer comments, author replies, requested changes, approvals
  - CI status summaries and checks (build/test/lint), occasional failures and reruns
  - Merge outcome: merged/closed, and merge method (squash/merge/rebase)
- PR writing norms:
  - Engineering tone: concise, technical, action-oriented.
  - Include context and motivation, especially for non-trivial changes.
  - Reference related work items (Linear is primary for project management; Jira keys may appear for support/escalations).
- Typical PR themes at Redwood:
  - Serving runtime performance improvements (batching, KV cache, scheduling)
  - API gateway/compatibility layers, streaming stability, structured output
  - Observability: metrics, tracing, dashboards, alert tuning
  - Dedicated capacity and autoscaling controls
  - Private deployment installer/upgrade tooling
  - SDK updates (Python/TS/Go), examples, docs site changes
  - Security improvements (auth, RBAC policy bundles, audit logging)
- Keep PRs plausible:
  - Mix of small and large PRs.
  - Include occasional hotfix PRs tied to incidents.
  - Include some WIP/draft PRs.

Metadata rules:
- Required metadata for every PR document:
  - repo: repository name (most commonly `redwood`)
  - pr_number: integer
  - title: PR title
  - author: real Redwood employee name
  - created_at (YYYY-MM-DD)
  - updated_at (YYYY-MM-DD)
  - state: open | closed | merged
  - base_branch: usually main/master/release/*
  - head_branch: feature/*, bugfix/*, hotfix/*, etc.
- Strongly recommended (very common) metadata:
  - reviewers: list of names
  - labels: list (e.g., runtime, sre, perf, docs, security)
  - linked_linear: list of Linear keys (ENG-/PM-/DES-)
  - ci_status: pass | fail | pending
- Optional metadata:
  - linked_jira: list of SUP-/INT- keys (when support-driven)
  - files_changed_count: integer
  - additions: integer
  - deletions: integer
  - release_notes: string or bullet list (when applicable)
  - breaking_change: boolean
- Date constraints: updated_at >= created_at; merged PRs include merged_at (optional) >= created_at.
