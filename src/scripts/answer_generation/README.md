# Answer Generation

As discussed in the Evaluation section of the [methodology](methodology.md), the repository provides three retrieval approaches to help refine the gold question set.
By pooling results from structurally different retrievers, questions whose gold documents were incomplete or incorrect are more likely to be surfaced and corrected through the evaluation pipeline.

## Vector Search

The vector search approach is a straightforward embed-and-retrieve pipeline. All source documents are embedded using OpenAI's `text-embedding-3-large` model (3072 dimensions) and stored in a Qdrant collection.
Chunking is intentionally minimal: each document's title and content fields are concatenated into a single embedding. If it exceeds the maximum limit, it is simply split at the last possible complete word.
Most generated documents fall within the model's token limit, so there is no sliding window, overlap, or multi-chunk logic.

At query time, the question is embedded with the same model and a single cosine-similarity search retrieves the top 10 results (configurable). No re-ranking, query expansion, or filtering is applied.
The retrieved documents are then formatted into a prompt and passed to an LLM, which generates an answer grounded only in the provided context.

This approach serves as a fast, inexpensive baseline. It performs well on questions where the query and the relevant document share strong semantic overlap, but struggles with questions that are more complex.

---

## BM25 Keyword Search

The BM25 approach uses OpenSearch to provide a traditional keyword-based retrieval baseline. All source documents are indexed into a single OpenSearch index with their title and content concatenated into one `text` field. No embeddings or LLM calls are required at indexing time.

At query time, the question is issued as a standard BM25 `match` query against the `text` field, and the top 10 results (configurable) are retrieved. As with vector search, the retrieved documents are formatted into a prompt and passed to an LLM for answer generation using the same prompt template.

This approach is the cheapest and fastest of the three, requiring no embedding API calls. It serves as a lexical baseline that is fast and performs best in cases with high lexical overlap.

---

## Agent-Based Retrieval

The agent-based approach replaces the fixed retrieval pipeline with an LLM agent that explores the corpus iteratively in an agent loop.
Rather than relying on pre-computed embeddings, the agent navigates the document directory structure directly — searching, reading, and reasoning about files in real time using shell commands.

The agent is given three tools: a shell execution tool with access to standard Unix utilities (`grep`, `find`, `jq`, `sed`, `awk`, `ls`, `tree`, etc.), a document read tool that extracts title and content from corpus files and surfaces the document's UUID, and a document selection tool for tracking which files it considers relevant to the answer.
Its working directory is set to the corpus root (`generated_data/sources`), so it operates relative to the source directory structure. The agent iteratively searches for documents, reads their contents, evaluates relevance, and refines its search strategy based on what it finds. Tool calls within a single LLM response are executed in parallel.
This loop continues until the agent produces a final answer or a per-question wall-clock time limit is reached, at which point a forced-finish LLM call prompts it to answer with whatever information it has gathered so far.

Command execution follows a two-layer architecture. The execution layer runs shell commands with full pipe semantics — raw bytes flow between pipe segments unmodified, preserving correct behavior for chained commands.
The presentation layer runs after execution and formats the output for the LLM: search commands (`grep`, `rg`, `find`, `glob`) are capped at 100 results when they are the last command in a pipe chain, and all output is subject to a generic 2,000-line / 50 KB truncation limit.
Full output from truncated commands is saved to a temporary file the agent can navigate with subsequent `grep` or `tail` commands.
Additional signals — such as repeat-command detection, zero-result counters with directory navigation hints, and null-field guidance for JSON inspection — help the agent avoid common dead ends.

To manage context window constraints, the conversation uses reactive LLM-based compaction rather than hard-coded pruning. When the LLM rejects a request because the context is too large, the full conversation is serialized, summarized by a cheap LLM, and replaced with a compact four-message sequence (system prompt, original question, research summary, continuation prompt). This preserves research progress while freeing context for further exploration.

This approach is significantly more expensive and slower than vector search, but it can handle question types which require variable numbers of documents to answer,
multi-hop or complex queries, or questions where the source directory structure contains critical information.

### Agent Retrieval Deep Dive

#### Tools

The agent has three tools:

1. **`run`** — Executes shell commands with support for pipes (`|`), logical operators (`&&`, `||`), and sequential execution (`;`). The allowed command set includes `grep`, `find`, `jq`, `sed`, `awk`, `ls`, `tree`, `cat`, `head`, `tail`, `xargs`, `wc`, `sort`, `uniq`, and `cut`. Commands that are not installed on the host system are silently removed from the allowlist — the LLM only sees commands it can actually use. Each subprocess is given a 1-minute timeout.

2. **`read_document`** — Reads a file relative to the corpus root. Instead of returning raw JSON, it extracts the document's title and content fields (via `extract_document_content`) and appends the `dataset_doc_uuid` at the end of the output. This gives the agent a clean, readable view of the document while surfacing the ID needed for the selection tool.

3. **`select_doc_by_dsid`** — Adds or removes a document UUID from the answer's document set. UUIDs are validated against a pre-built index so invalid IDs are rejected immediately. The accumulated set persists across context compactions and is returned as the final `document_ids` in the output.

When the LLM emits multiple tool calls in a single response, they are dispatched in parallel via a thread pool with a 1-minute collective timeout. Results are collected and appended to the conversation in the original call order so the LLM sees a consistent message sequence.

#### Two-Layer Execution Architecture

Command execution is split into two layers to keep pipe semantics correct while still managing the LLM's context window.

**Layer 1 — Execution.** The `parse_chain` parser splits the command string into segments by `|`, `&&`, `||`, and `;`, respecting quoted strings. Segments are executed sequentially with raw bytes piped between them — no truncation or metadata injection occurs at this level. The only checks are: command allowlist validation on the first segment, binary detection on the final segment's stdout, and early exit on non-zero return codes with stderr.

**Layer 2 — Presentation.** After the chain completes, the raw output passes through a formatting pipeline before being returned to the LLM:

1. **Search truncation** — If the last command in the chain is `grep`, `rg`, `find`, or `glob`, the output is capped at 100 lines. The full output is written to a temp file and a navigation hint is appended.
2. **Generic truncation** — All output is subject to a 2,000-line / 50 KB limit (whichever is hit first). Truncated output is similarly saved to a temp file with `grep` / `tail` navigation hints. If the truncated output is a list of file paths, the hint instead suggests scoping by subdirectory.
3. **Null-field guidance** — When `jq` returns `null`, a hint suggests inspecting the document's `content_field_names` or running `jq 'keys'` to discover the actual structure.
4. **Repeat-command detection** — If the agent issues the exact same command twice, the result is annotated with a note pointing to the original command index.
5. **Zero-result counter** — Consecutive zero-result searches against the same base path are counted. After 5 misses, a hint lists the available source subdirectories.
6. **Metadata footer** — Every result ends with `[exit:<code> | <ms> | cmd #<n> | session: <s>s]` so the agent can track its own progress and time usage.

#### Conversation Loop

The conversation is driven by `run_agent_conversation` in `src/llm/auto_conversation.py`, a wall-clock-bounded loop. Key behaviors:

- **Time budget**: Each question gets 10 minutes. A shutdown warning is injected 30 seconds before the deadline.
- **Forced finish**: After the deadline, a separate toolless LLM call forces the agent to produce a final text answer with whatever it has gathered.
- **No-tool-call nudge**: If the agent responds with text but no tool calls mid-conversation, a user message nudges it to keep calling tools.
- **LLM error retry**: Transient LLM errors trigger a 5-second backoff and retry.
- **Reasoning level**: Both the main agent LLM and the forced-finish LLM use medium-level reasoning.

#### Context Compaction

Rather than proactively pruning old messages at a fixed character threshold, compaction is **reactive** — it triggers only when the LLM API returns a context-overflow error. This lets the conversation grow naturally until the model actually rejects it.

When an overflow is detected:

1. The full conversation is serialized into a text blob. Individual tool results are capped at 1,000 characters each, and the total input is capped at 150K characters (keeping the most recent tail).
2. A cheap LLM summarizes the research session, capturing: the question, searches performed, documents found (with paths and UUIDs), key facts extracted, current status, and unexplored avenues.
3. The message list is replaced with four messages: the original system prompt, the original question, the research summary as an assistant message, and a continuation prompt.
4. The selected document set (`select_doc_by_dsid` state) is preserved across compactions since it lives outside the message list.

A maximum of 3 compactions are allowed per conversation to prevent infinite loops. If the cheap LLM summary fails, the system falls back to simple oldest-first pair pruning.

#### Script Options

The script supports parallel question processing (`--parallelism`), resumption of partial runs (`--resume`), single-question debugging (`--question-id`), and type-balanced subsets (`--subset-per-type`). At startup it validates the command allowlist, builds the UUID index, and injects the corpus document count into the system prompt to give the agent a sense of scale.

---

### Alternative Agent Based Retrieval

The approach outlined above is inspired by coding agents such as Claude Code and Opencode. The quality of the retrieval is similar but some users might prefer the familiar experience with these coding tools.
They are also easier to tune the search behavior of using AGENTS.md files which may be helpful on custom datasets. An example AGENTS.md file is provided for your reference [here](src/scripts/answer/generation/agents_example.md).
