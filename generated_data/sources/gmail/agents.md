Directory:
sources/gmail

Target number of files:
120000

File name format:
File names should include the date in a concatenated style followed by a description of the topic of the thread (e.g. 20250625-marketing-kpi-review.json).

Content rules:
- All of the emails must be in an inbox, the files cannot be directly at the top level under gmail.
- This directory contains Gmail exports for a restricted set of Redwood Inference employees:
  - managers
  - sales roles
  - leadership
- IMPORTANT: The restriction applies to all internal participants in threads.
  - Every internal sender/recipient/cc-d person must be one of the real people represented by the subdirectories under sources/gmail/.
  - External participants (customers, prospects, vendors, partners) are allowed.
- Each document represents exactly one email thread (conversation).
  - A thread contains multiple messages (replies/forwards) in chronological order (oldest - newest).
  - Preserve realistic email quoting (e.g., "On Tue, ... wrote:") and forwarded-message headers.
- Emails should look like real Gmail messages:
  - Headers: From, To, Cc (common), Bcc (rare), Date, Subject.
  - Short paragraphs, bullets, and clear asks.
  - Signatures are common; include job titles and company name sometimes.
  - Attachments are referenced frequently; represent as short attachment stubs (filename/type) rather than generating full binary content.
- Typical thread themes for this subset of roles:
  - Sales pipeline: discovery follow-ups, mutual action plans, demo scheduling
  - Pricing/terms, procurement steps, redlines and contract coordination
  - Security/compliance questionnaires and evidence requests (SOC 2, data retention, audit logs)
  - Executive approvals and escalations (credits, discounts, SLA exceptions)
  - Customer escalations and renewal/expansion coordination (often looping in CS)
  - Partner coordination (cloud marketplaces, integration partners)
  - Hiring and org/people topics at manager/leadership level
- Tone guidance:
  - Sales emails: concise, friendly, action-oriented, with clear next steps.
  - Leadership/manager emails: crisp, directive, sometimes sensitive; may be more formal.
  - Many threads include quick one-line replies and fragmented coordination; do not over-polish.

Metadata rules:
- Required metadata for every thread document:
  - thread_id: unique-ish identifier
  - mailbox_owner: the Redwood employee whose mailbox folder contains the thread (must be a real person from sources/gmail/)
  - subject: the thread subject (can evolve with Re:/Fwd:)
  - participants_internal: list of internal participant names (must all be from the sources/gmail/ people set)
  - participants_external: list of external participant identifiers (names and/or emails)
  - message_count: integer
  - first_email_at: ISO date-time
  - last_email_at: ISO date-time
- Optional metadata (use frequently when applicable):
  - thread_type: sales | procurement | security_compliance | escalation | leadership_update | hiring | partner | finance_billing | misc
  - related_account: external company name
  - deal_id: string
  - region: us | eu | apac (if relevant)
  - has_attachments: boolean
  - attachments: list of file names
  - related_links: list of URLs/ids (HubSpot record ids, shared Drive links, DocuSign links, Jira SUP- keys)
- Date constraints: last_email_at >= first_email_at; timestamps should be plausible over multiple years.
