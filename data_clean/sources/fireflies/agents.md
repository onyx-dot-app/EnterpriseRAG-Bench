Directory:
sources/fireflies

Target number of files:
10000

File name format:
The documents must include the date and meeting title in the format of 2025-01-28-meeting-title.json

Content rules:
- Documents in this directory are Fireflies.ai meeting artifacts, specifically call transcripts.
- The vast majority of calls are sales-related and fall into these common categories:
  - discovery
  - demo
  - poc (proof of concept) scoping
  - poc check-in / weekly sync
  - renewal/expansion check-ins (less common)
  - security / compliance review
  - procurement / legal process calls
  - technical deep dives (e.g., performance, private deployments)
- Transcript structure should resemble typical Fireflies exports:
  - A brief meeting header (date/time, duration, attendees)
  - Optional auto-generated sections (may be present or absent): Summary, Topics, Action items, Questions
  - Transcript body with speaker labels and periodic timestamps (e.g., every 15-60 seconds)
- The transcript itself should feel authentic:
  - Transcription is often imperfect.
    - Words may be swapped for similar-sounding ones.
    - Proper nouns and acronyms are sometimes incorrect (e.g., Redwood product names, customer names, Kubernetes/VPC/KV cache, etc.).
    - Punctuation/paragraphing can be inconsistent; occasional run-on sentences.
    - Speaker attribution can be wrong at times (or generic labels like Speaker 1/Speaker 2 appear).
  - Include natural speech patterns: filler words, interruptions, clarifications, and occasional crosstalk.
- Sales-call realism guidelines:
  - Include qualification and context gathering (current stack, constraints, stakeholders, timeline, success criteria).
  - Include typical objections and tradeoffs (latency vs cost, dedicated vs hosted, VPC/on-prem constraints, data retention).
  - Frequently discuss enterprise/security topics when relevant: SOC 2/ISO, audit logs, SSO/SAML, RBAC, encryption/KMS, data residency.
  - Calls often end with a recap and explicit next steps (send pricing, share security docs, schedule demo, start pilot, run benchmarks).
- Attendee patterns:
  - A significant percentage of sales calls include an AE+SE pair from Redwood.
  - Some calls are SE-led (deep dives) or CSM-led (check-ins), but AE+SE is common.
- Do not rewrite transcripts into clean prose; keep them as transcript-like artifacts.
- References to shared artifacts are common (decks, docs, benchmark spreadsheets). Represent these as links or short notes rather than generating long external content.

Metadata rules:
- Every document must include:
  - meeting_id: unique-ish identifier
  - recorded_at: ISO date-time
  - duration_minutes: integer
  - call_type: discovery | demo | poc_scoping | poc_checkin | checkin | security_review | procurement_legal | technical_deep_dive | other
  - title: meeting title as it would appear in a calendar (can be generic/templated; do not over-polish)
  - redwood_owner: a real Redwood employee name (often the AE)
  - redwood_attendees: list of Redwood attendee names (often AE+SE)
  - customer_company: company name
  - customer_attendees: list of customer names (roles optional)
- Optional metadata (use frequently but not always):
  - competitors_mentioned: list
  - next_steps: list of strings
  - action_items: list of {owner, item, due_date?}
  - transcription_quality: low | medium | high
  - crm_deal_id or crm_account_id (string)
- recorded_at and duration should be plausible; transcripts should align roughly with duration.
