Directory:
sources/slack

Target number of files:
200000

File name format:
The documents are named some timestamp.json in unix time (just a single number with no underscore etc.) followed by a description of the thread (e.g., 1740535447-v2-api-rollout-blockers.json). Note that the vast majority of Slack threads (even on technical or complex seeming topics) should be very short. This should reflect how users actually communicate on Slack. Nearly all messages are just a short message (1-2 concise phrases) and a short response (or even no responses at all).

Content rules:
- Each document represents exactly one Slack thread.
  - Include the root message and all replies.
  - Present messages in chronological order.
- Every Slack thread should be contained as a single continuous string containing messages from different people
  - The messages do not need individual timestamps, we just need the time of the initial message.
  - The messages should be prefixed with the sender's name
- Slack threads do not have natural-language titles. Do NOT invent or infer titles.
- Write messages in realistic Slack style:
  - Short, informal, sometimes incomplete sentences.
  - A lot of messages will be fairly short/choppy from the team.
  - Common abbreviations, quick questions, and back-and-forth coordination.
  - @mentions, emoji shortcodes (e.g., :thumbsup:), reactions (as lightweight annotations), and links.
  - Inline code and fenced code blocks for logs, commands, config snippets.
  - Occasional bot/system messages (e.g., incident bot, deploy bot) are allowed.

Metadata rules:
- Required metadata for every thread document:
  - channel: Slack channel name (must correspond to a subdirectory under sources/slack/, e.g., eng-sre, incidents, product)
  - thread_ts: the root message timestamp (e.g., 1740535447)
  - first_message_ts: timestamp of the first message in the thread
  - last_message_ts: timestamp of the last message in the thread
  - participants: list of participant display names (real Redwood employees; may include bots)
- Title:
  - Omit the title field entirely for Slack thread documents.
- Slack does not have a lot of other metadata so keep it constrainted to the list above.
- Timestamp constraints:
  - last_message_ts >= first_message_ts.
  - Timestamps should be plausible over multiple years.
