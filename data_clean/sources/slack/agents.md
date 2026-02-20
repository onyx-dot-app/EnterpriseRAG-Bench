Directory:
sources/slack

Target number of files:
200000

Content rules:
- Each document represents exactly one Slack thread.
  - Include the root message and all replies.
  - Present messages in chronological order.
- Slack threads do not have natural-language titles. Do NOT invent or infer titles.
- Write messages in realistic Slack style:
  - Short, informal, sometimes incomplete sentences.
  - Common abbreviations, quick questions, and back-and-forth coordination.
  - @mentions, emoji shortcodes (e.g., :thumbsup:), reactions (as lightweight annotations), and links.
  - Inline code and fenced code blocks for logs, commands, config snippets.
  - Occasional bot/system messages (e.g., incident bot, deploy bot) are allowed.
- Do not add narrative summaries or hindsight context unless it appears as a message in the thread.
- If a message references files, screenshots, or attachments, represent them as small stubs (filename, type, URL placeholder) rather than generating long binary-like content.
- Threads may reference other systems (Jira/Linear tickets, GitHub PRs, incidents, runbooks). Preserve these references as-is.

Metadata rules:
- Required metadata for every thread document:
  - channel: Slack channel name (must correspond to a subdirectory under sources/slack/, e.g., eng-sre, incidents, product)
  - thread_ts: the root message timestamp (Slack-style, e.g., 1705171331.123456)
  - first_message_ts: timestamp of the first message in the thread
  - last_message_ts: timestamp of the last message in the thread
  - participants: list of participant display names (real Redwood employees; may include bots)
  - message_count: integer
- Title:
  - Omit the title field entirely for Slack thread documents.
- Optional metadata (use sparingly):
  - related_jira_keys: list (e.g., ["SRE-1842", "SUP-9910"])
  - related_linear_ids: list
  - related_github_prs: list of URLs or org/repo#id
  - incident_id: string (if in incident-related channels)
  - tags: 0–5 short tags (rare)
  - visibility: internal (default) | restricted (for security/customer-sensitive threads)
- Timestamp constraints:
  - last_message_ts >= first_message_ts.
  - Timestamps should be plausible over multiple years.
