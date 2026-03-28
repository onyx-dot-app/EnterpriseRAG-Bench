A single run(command="...") tool with Unix-style commands outperforms a catalog of typed function calls.

Here's what I learned.

Why *nix
Unix made a design decision 50 years ago: everything is a text stream. Programs don't exchange complex binary structures or share memory objects — they communicate through text pipes. Small tools each do one thing well, composed via | into powerful workflows. Programs describe themselves with --help, report success or failure with exit codes, and communicate errors through stderr.

LLMs made an almost identical decision 50 years later: everything is tokens. They only understand text, only produce text. Their "thinking" is text, their "actions" are text, and the feedback they receive from the world must be text.

These two decisions, made half a century apart from completely different starting points, converge on the same interface model. The text-based system Unix designed for human terminal operators — cat, grep, pipe, exit codes, man pages — isn't just "usay LLMs. It's a natural fit. When it comes to tool use, an LLM is essentially a terminal operator — one that's faster than any human and has already seen vast amounts of shell commands and CLI patterns in its training data.

This is the core philosophy of the *nix Agent: don't invent a new tool interface. Take what Unix has proven over 50 years and hand it directly to the LLM.

Why a single run
The single-tool hypothesis
Most agent frameworks give LLMs a catalog of independent tools:

tools: [search_web, read_file, write_file, run_code, send_email, ...]
Before each call, the LLM must make a tool selection — which one? What parameters? The more tools you add, the harder the selection, and accuracy drops. Cognitive load is spent on "which tool?" instead of "what do I need to accomplish?"

My approach: one run(command="...") tool, all capabilities exposed as CLI commands.

run(command="cat notes.md")
run(command="cat log.txt | grep ERROR | wc -l")
run(command="see screenshot.png")
run(command="memory searchployment issue'")
run(command="clip sandbox bash 'python3 analyze.py'")
The LLM still chooses which command to use, but this is fundamentally different from choosing among 15 tools with different schemas. Command selection is string composition within a unified namespace — function selection is context-switching between unrelated APIs.

LLMs already speak CLI
Why are CLI commands a better fit for LLMs than structured function calls?

Because CLI is the densest tool-use pattern in LLM training data. Billions of lines on GitHub are full of:

# README install instructions
pip install -r requirements.txt && python main.py

# CI/CD build scripts
make build && make test && make deploy

# Stack Overflow solutions
cat /var/log/syslog | grep "Out of memory" | tail -20
I don't need to teach the LLM how to use CLI — it already knows. This familiarity is probabilistic and model-dependent, but in practice it's remarkably reliable across mainstream models.

Compare two approaches to the same task:

Task: Read a log f count the error lines

Function-calling approach (3 tool calls):
  1. read_file(path="/var/log/app.log") → returns entire file
  2. search_text(text=<entire file>, pattern="ERROR") → returns matching lines
  3. count_lines(text=<matched lines>) → returns number

CLI approach (1 tool call):
  run(command="cat /var/log/app.log | grep ERROR | wc -l")
  → "42"
One call replaces three. Not because of special optimization — but because Unix pipes natively support composition.

Making pipes and chains work
A single run isn't enough on its own. If run can only execute one command at a time, the LLM still needs multiple calls for composed tasks. So I make a chain parser (parseChain) in the command routing layer, supporting four Unix operators:

|   Pipe: stdout of previous command becomes stdin of next
&&  And:  execute next only if previous succeeded
||  Or:   execute next only if previous failed
;   Seq:  execute next regardless of previous result
With this mechanism, every tool call can be a complete w# One tool call: download → inspect
curl -sL $URL -o data.csv && cat data.csv | head 5

# One tool call: read → filter → sort → top 10
cat access.log | grep "500" | sort | head 10

# One tool call: try A, fall back to B
cat config.yaml || echo "config not found, using defaults"
N commands × 4 operators — the composition space grows dramatically. And to the LLM, it's just a string it already knows how to write.

The command line is the LLM's native tool interface.

Heuristic design: making CLI guide the agent
Single-tool + CLI solves "what to use." But the agent still needs to know "how to use it." It can't Google. It can't ask a colleague. I use three progressive design techniques to make the CLI itself serve as the agent's navigation system.

Technique 1: Progressive --help discovery
A well-designed CLI tool doesn't require reading documentation — because --help tells you everything. I apply the same principle to the agent, structured as progressive disclosure: the agent doesn't need to load aion at once, but discovers details on-demand as it goes deeper.

Level 0: Tool Description → command list injection

The run tool's description is dynamically generated at the start of each conversation, listing all registered commands with one-line summaries:

Available commands:
  cat    — Read a text file. For images use 'see'. For binary use 'cat -b'.
  see    — View an image (auto-attaches to vision)
  ls     — List files in current topic
  write  — Write file. Usage: write <path> [content] or stdin
  grep   — Filter lines matching a pattern (supports -i, -v, -c)
  memory — Search or manage memory
  clip   — Operate external environments (sandboxes, services)
  ...
The agent knows what's available from turn one, but doesn't need every parameter of every command — that would waste context.

Note: There's an open design question here: injecting the full command list vs. on-demand discovery. As commands grow, the list itself consumes context budget. I'm still exploring the right balance.evel 1: command (no args) → usage

When the agent is interested in a command, it just calls it. No arguments? The command returns its own usage:

→ run(command="memory")
[error] memory: usage: memory search|recent|store|facts|forget

→ run(command="clip")
  clip list                              — list available clips
  clip <name>                            — show clip details and commands
  clip <name> <command> [args...]         — invoke a command
  clip <name> pull <remote-path> [name]   — pull file from clip to local
  clip <name> push <local-path> <remote>  — push local file to clip
Now the agent knows memory has five subcommands and clip supports list/pull/push. One call, no noise.

Level 2: nd (missing args) → specific parameters

The agent decides to use memory search but isn't sure about the format? It drills down:

→ run(cnd="memory search")
[error] memory: usage: memory search <query> [-t topic_id] [-k keyword]

→ run(command="clip sandbox")
  Clip: sandbox
  Commands:
    ip sandbox bash <script>
    clip sandbox read <path>
    clip sandbox write <path>
  File transfer:
    clip sandbox pull <remote-path> [local-name]
    clip sandbox push <local-path> <remote-path>
Progressive disclosure: overview (injected) → usage (explored) → parameters (drilled down). The agent discovers on-demand, each level providing just enough information for the next step.

This is fundamentally different from stuffing 3,000 words of tool documentation into the system prompt. Most of that information is irrelevant most of the time — pure context waste. Progressive help lets the agent decide when it needs more.

This also imposes a requirement on command design: every command and subcommand must have complete help output.not just for humans — it's for the agent. A good help message means one-shot success. A missing one means a blind guess.

Technique 2: Error messages as navigation
Agents will make mistakes. The key isn't preventing errors — it's making every error point to the right direction.

Traditional CLI errors are designed for humans who can Google. Agents can't Google. So I require every error to contain both "what went wrong" and "what to do instead":

Traditional CLI:
  $ cat photo.png
  cat: ry file (standard output)
  → Human Googles "how to view image in terminal"

My design:
  [error] cat: binary image file (182KB). Use: see photo.png
  → Agent calls see directly, one-step correction
More examples:

[error] unknown command: foo
Available: cat, ls, see, write, grep, memory, clip, ...
→ Agent immediately know commands exist

[error] not an image file: data.csv (use cat to read text files)
→ Agent switches from see to cat

[error] clip "sandbox" not found. Use 'clip list' to see available clips
→ Agent knows to list clipsst
Technique 1 (help) solves "what can I do?" Technique 2 (errors) solves "what should I do instead?" Together, the agent's recovery cost is minimal — usually 1-2 steps to the right path.

Real case: The cost of silent stderr

For a while, myode silently dropped stderr when calling external sandboxes — whenever stdout was non-empty, stderr was discarded. The agent ran pip install pymupdf, got exit code 127. stderr contained bash: pip: command not found, but the agent couldn't see it. It only knew "it failed," not "why" — and proceeded to blindly guess 10 different package managers:

pip install         → 127  (doesn't exist)
python3 -m pip      → 1    (module not found)
uv pip install      → 1    (wrong usage)
pip3 install        → 127
sudo apt install    → 127
... 5 more attempts ...
uv run --with pymupdf python3 script.py → 0 ✓  (10th try)
10 calls, ~5 seconds of inference each. If stderr had been visible the first time, one call would have been enough.

stderr is the information agents need most, precisely when commanp it.

Technique 3: Consistent output format
The first two techniques handle discovery and correction. The third lets the agent get better at using the system over time.

I append consistent metadata to every tool result:

file1.txt
file2.txt
dir1/
[exit:0 | 12ms]
The LLM extracts two signals:

Exit codes (Unix convention, LLMs already know these):

exit:0 — success

exit:1 — general error

exit:127 — command not found

Duration (cost awareness):

12ms — cheap, call freely

3.2s — m5s — expensive, use sparingly

After seeing [exit:N | Xs] dozens of times in a conversation, the agent internalizes the pattern. It starts anticipating — seeing exit:1 means check the error, seeing long duration means reduce calls.

Consistent output format makes the agent smarter over time. Inconsistency makes every call feeke the first.

The three techniques form a progression:

--help       →  "What can I do?"        →  Proactive discovery
Error Msg    →  "What should I do?"     →  Reactive correction
Output Fmt   →  "How did it go?"        →  Continuous learning
Two-layer architecture: engineering the heuristic design
The section above described how CLI guides agents at the semantic level. But to make it work in practice, there's an engineering problem: th of a command and what the LLM needs to see are often very different things.

Two hard constraints of LLMs
Constraint A: The context window is finite and expensive. Every token costs money, attention, and inference speed. Stuffing a 10MB file into context doesn't just waste budget — it pushes earlier conversation out of the window. The agent "forgets."

Constraint B: LLMs can only process text. Binary data produces high-entropy meaningless tokens through the tokenizer. It doesn't just waste context — it disrupts attention on surrounding valid tokens, degrading reasoning quality.

These two constraints mean: raw command output can't go directly to the LLM — it needs a presentation layer for processing. But that processing can't affect command execution logic — or pipes break. Hence, two layerution layer vs. presentation layer
┌─────────────────────────────────────────────┐
│  Layer 2: LLM Presentation Layer            │  ← Designed for LLM constraints
│  Binary guard | Truncation+overflow | Meta   │
├─────────────────────────────────────────────┤
│  Layer 1: Unix Execution Layer   1:
  cat output → [500KB raw text] → grep input
  grep output → [matching lines] → head input
  head output → [first 10 lines]
If you truncate cat's output in Layer 1 → grep only searches the first 200 lines, producing incomplete results. If you add [exit:0] in Layer 1 → it flows into grep as data, becoming a seao Layer 1 must remain raw, lossless, metadata-free. Processing only happens in Layer 2 — after the pipe chain completes and the final result is ready to return to the LLM.

Layer 1 serves Unix semantics. Layer 2 serveLLM cognition. The separation isn't a design preference — it's a logical necessity.

Layer 2's four mechanisms
Mechanism A: Binary Guard (addreing Constraint B)

Before returning anything to the LLM, check if it's text:

Null byte detected → binary
UTF-8 validation failed → binary
Control character ratio > 10% → binary

If image: [error] binary image (182KB). Use: see photo.png
If other: [error] binary file (1.2MB). Use: cat -b file.bin
The LLM never receives data it can't process.

Mechanism B: Overflow Mode (addressing Constraint A)

Output > 200 lines or > 50KB?
  → Truncate to first 200 lines (rune-safe, won't split UTF-8)
  → Write full output to /tmp/cmd-output/cmd-{n}.txt
  → Return to LLM:

    [first 200 lines]

    --- output truncated (5000 lines, 245.3KB) ---
    Full output: /tmp/cmd-output/cmd-3.txt
    Explore: cat /tmp/cmd-output/cmd-3.txt | grep <pattern>
             cat /tmp/cmd-output/cmd-3.txt | tail 100
    [exit:0 | 1.2s]
Key insight: the LLM already knows how to use grep, head, tail to navigate filemode transforms "large data exploration" into a skill the LLM already has.

Mechanism C: Metadata Footer

actual output here
[exit:0 | 1.2s]
Exit code + duration, appended as the last line of Layer 2. Gives the agent signals for success/failure and cost awareness, without polluting Layer 1's pipe data.

Mechanism D: stderr Attachment

When command fails with stderr:
  output + "\n[stderr] " + stderr

Ensures the agent can see why something failed, preventing blind retries.
Lessons learned: stories from production
Story 1: A PNG that caused 20 iterations of thrashing
A user uploaded an architecture diagram. The agent read it with cat, receiving 182KB of raw PNG bytes. The LLM's tokenizer turned these bytes into thousands of meaningless tokens crammed into the context. The LLM couldn't make sense of it and started trying different read approaches — cat -f, cat --format, cat --type image — each time receiving the same garbage. After 20 iterations, the process was force-terminated.

Root cause: cat had no binary detection, Layer 2 ho guard. Fix: isBinary() guard + error guidance Use: see photo.png. Lesson: The tool result is the agent's eyes. Return garbage = agent goes blind.

Story 2: Silent stderr and 10 blind retries
The agent needed to read a PDF. It tried pip install pymupdf, got exit code 127. stderr contained bash: pip: command not found, but the code dropped it — because there was some stdout output, and the logic was "if stdout exists, ignore stderr."

The agent only knew "it failed," not "why." What followed was a long trial-and-error:

pip install         → 127  (doesn't exist)
python3 -m pip      → 1    (module not found)
uv pip install      → 1    (wrong usage)
pip3 install        → 127
sudo apt install    → 127
... 5 more attempts ...
uv run --with pymupdf python3 script.py → 0 ✓
10 calls, ~5 seconds of inference each. If stderr had been visible the first time, one call would have sufficed.

Root cause: InvokeClip silently dropped stderr when stdout was non-empty. Fix: Always attach stderr on failure. Lesson: stderr is the informationt, precisely when commands fail.

Story 3: The value of overflow mode
The agent analyzed a 5,000-line log file. Without truncation, the full text (~200KB) was stuffed into context. The LLM's attention was overwhelmed, response quality dropped sharply, and earlier conversation was pushed out of the context window.

With overflow mode:

[first 200 lines of log content]

--- output truncated (5000 lines, 198.5KB) ---
Full output: /tmp/cmd-output/cmd-3.txt
Explore: cat /tmp/cmd-output/cmd-3.txt | grep <pattern>
         cat /tmp/cmd-output/cmd-3.txt | tail 100
[exit:0 | 45ms]
The agent saw the first 200 lines, understood the file structure, then used grep to pinpoint the issue — 3 calls total, under 2KB of context.

Lesson: Giving the agent a "map" is far more effective than giving it the entire territory.

Boundaes and limitations
CLI isn't a silver bullet. Typed APIs may be the better choice in these scenarios:

Strongly-typed interactions: Database queries, GraphQL APIs, and other cases requiring structured input/output. Schema validation is more reliable than string parsing.

High-security requirements: CLI's string concatenation carries inherent injection risks. In untrusted-input scenarios, typed parameters are safer. agent-clip mitigates this through sandbox isolation.

Native multimodal: Pure audio/video processing and other binary-stream scenarios where CLI's text pipe is a bottleneck.

Additionally, "no iteration limit" doesn't mean "no safety boundaries." Safety is ensured by external mechanisms:

Sandbox isolation: Commands execute inside BoxLite containers, no escape possible

API budgets: LLM calls have account-level spending caps

User cancellation: Frontend provides cancel buttons, backend supports graceful shutdown

Hand Unix philosophy to the execution layer, hand LLM's cognitive constraints to the presentation layer, and use help, error messages, and output format as three progressive heuristic navigation techniques.

CLI is all agents need.

Source code (Go): github.com/epiral/agent-clip

Core files: internal/tools.go (command routing), internal/chain.go (pipes), internal/loop.go (two-layer agentic loop), internal/fs.go (binary guard), internal/clip.go (stderr handling), internal/browser.go (vision auto-attach), internal/memory.go (semantic memory).
