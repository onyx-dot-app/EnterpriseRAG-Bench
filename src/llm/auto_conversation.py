"""Automatic conversation utilities for running LLM conversations without user input."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from dataclasses import dataclass
from typing import Any, Callable

from src.llm.factory import get_llm
from src.llm.interface import LLMInterface, Message, ToolCall
from src.llm.tracing import log_to_span, traced_span
from src.tools.exceptions import ToolTerminationSignal
from src.tools.runner import ToolRunner


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_MAX_CONTEXT_CHARS = 200_000

# Patterns that LLM providers use to signal context window overflow.
_CONTEXT_OVERFLOW_PATTERNS = (
    "context_length_exceeded",
    "maximum context length",
    "too many tokens",
    "prompt is too long",
    "request too large",
    "context window",
    "token limit",
    "exceeds the model",
    "max_tokens",
    "input is too long",
)

# Maximum number of LLM-based compactions per conversation to avoid loops.
_MAX_COMPACTIONS = 3


def _is_context_overflow_error(exc: Exception) -> bool:
    """Return True if *exc* signals that the LLM context window was exceeded."""
    msg = str(exc).lower()
    return any(p in msg for p in _CONTEXT_OVERFLOW_PATTERNS)


def prune_messages(
    messages: list[Message],
    max_chars: int = _MAX_CONTEXT_CHARS,
) -> None:
    """Drop the oldest tool_call/tool_result pairs when context is too large.

    Preserves the first two messages (typically system + user) and trims from
    the front of the remaining history.  Mutates *messages* in place so that
    callers sharing the same list reference see the pruned version.
    """
    total_chars = sum(len(m.content or "") for m in messages)
    if total_chars <= max_chars:
        return

    # Find how many elements to drop from messages[2:]
    drop = 0
    idx = 2
    while total_chars > max_chars and idx + 1 < len(messages):
        if (
            messages[idx].role == "tool_call"
            and messages[idx + 1].role == "tool_result"
        ):
            total_chars -= len(messages[idx].content or "")
            total_chars -= len(messages[idx + 1].content or "")
            drop += 2
            idx += 2
        else:
            total_chars -= len(messages[idx].content or "")
            drop += 1
            idx += 1

    if drop:
        del messages[2 : 2 + drop]


def _run_llm_step(
    llm: LLMInterface,
    messages: list[Message],
    step: int,
    quiet: bool = False,
) -> tuple[str, list[ToolCall]]:
    """Call the LLM and collect the full text response and tool calls.

    Also traces the step to Braintrust.
    """
    full_response = ""
    tool_calls: list[ToolCall] = []

    with traced_span(f"llm_step_{step}", span_type="llm") as step_span:
        for chunk in llm.generate(messages):
            if isinstance(chunk, str):
                full_response += chunk
                if not quiet:
                    print(chunk, end="", flush=True)
            elif isinstance(chunk, ToolCall):
                tool_calls.append(chunk)

        log_to_span(
            step_span,
            input=[
                {"role": m.role, "content": (m.content or "")[:500]}
                for m in messages[-3:]
            ],
            output=full_response if full_response else None,
            metadata={
                "tool_calls": (
                    [
                        {
                            "name": tc.name,
                            "args": tc.args,
                            "call_id": tc.call_id,
                        }
                        for tc in tool_calls
                    ]
                    if tool_calls
                    else None
                ),
            },
        )

    return full_response, tool_calls


def _dispatch_tool_calls_toolrunner(
    tool_calls: list[ToolCall],
    tool_runner: ToolRunner,
    messages: list[Message],
) -> ToolTerminationSignal | None:
    """Execute tool calls via a ToolRunner, appending messages.

    Returns a ToolTerminationSignal if one was raised, else None.
    """
    for tool_call in tool_calls:
        messages.append(Message(role="tool_call", content="", tool_call=tool_call))

        termination_signal: ToolTerminationSignal | None = None

        with traced_span(tool_call.name, span_type="tool") as tool_span:
            try:
                result = tool_runner.run(tool_call.name, **tool_call.args)
            except ToolTerminationSignal as sig:
                result = sig.result
                termination_signal = sig
            log_to_span(
                tool_span,
                input=tool_call.args,
                output=result,
            )

        messages.append(
            Message(
                role="tool_result",
                content=result,
                call_id=tool_call.call_id,
            )
        )

        if termination_signal is not None:
            return termination_signal

    return None


ToolExecutor = Callable[..., str]


def _dispatch_tool_calls_executor(
    tool_calls: list[ToolCall],
    executors: dict[str, ToolExecutor],
    messages: list[Message],
    quiet: bool = False,
) -> ToolTerminationSignal | None:
    """Execute tool calls via a dict of executor callables, appending messages.

    Each executor is called with ``**tool_call.args``.  If an executor raises
    ``ToolTerminationSignal``, that signal is returned immediately.

    Returns a ToolTerminationSignal if one was raised, else None.
    """
    for tool_call in tool_calls:
        messages.append(Message(role="tool_call", content="", tool_call=tool_call))

        if not quiet:
            print(f"\n[Tool: {tool_call.name}] args={json.dumps(tool_call.args)}")

        executor = executors.get(tool_call.name)
        termination_signal: ToolTerminationSignal | None = None

        with traced_span(tool_call.name, span_type="tool") as tool_span:
            if executor is None:
                result = (
                    f"[error] unknown tool '{tool_call.name}'. "
                    f"Available tools: {', '.join(sorted(executors.keys()))}."
                )
            else:
                try:
                    result = executor(**tool_call.args)
                except ToolTerminationSignal as sig:
                    result = sig.result
                    termination_signal = sig

            log_to_span(
                tool_span,
                input=tool_call.args,
                output=result,
            )

        if not quiet:
            preview = result[:300].replace("\n", " ")
            print(f"  -> {preview}")

        messages.append(
            Message(
                role="tool_result",
                content=result,
                call_id=tool_call.call_id,
            )
        )

        if termination_signal is not None:
            return termination_signal

    return None


@dataclass
class _ToolResult:
    """Container for the result of a single tool execution."""

    tool_call: ToolCall
    result: str
    signal: ToolTerminationSignal | None


def _execute_single_tool(
    tool_call: ToolCall,
    executors: dict[str, ToolExecutor],
) -> _ToolResult:
    """Execute one tool call and capture its result or termination signal."""
    executor = executors.get(tool_call.name)
    if executor is None:
        return _ToolResult(
            tool_call=tool_call,
            result=(
                f"[error] unknown tool '{tool_call.name}'. "
                f"Available tools: {', '.join(sorted(executors.keys()))}."
            ),
            signal=None,
        )
    try:
        result = executor(**tool_call.args)
        return _ToolResult(tool_call=tool_call, result=result, signal=None)
    except ToolTerminationSignal as sig:
        return _ToolResult(tool_call=tool_call, result=sig.result, signal=sig)


def _dispatch_tool_calls_executor_parallel(
    tool_calls: list[ToolCall],
    executors: dict[str, ToolExecutor],
    messages: list[Message],
    quiet: bool = False,
    timeout: float = 120,
) -> ToolTerminationSignal | None:
    """Execute tool calls in parallel via threads, appending messages in order.

    All tool calls are submitted concurrently.  Results are collected and
    appended to *messages* in the original tool-call order so the LLM sees a
    consistent conversation.  If any executor raises ``ToolTerminationSignal``,
    the first one (in submission order) is returned after all results are
    recorded.

    Args:
        tool_calls: Tool calls to execute.
        executors: Mapping of tool name → callable.
        messages: Conversation messages (appended in place).
        quiet: Suppress output previews.
        timeout: Max seconds to wait for all tool calls to complete.

    Returns:
        A ToolTerminationSignal if one was raised, else None.
    """
    if not quiet:
        for tc in tool_calls:
            print(f"\n[Tool: {tc.name}] args={json.dumps(tc.args)}")

    # Submit all tool calls to a thread pool
    with ThreadPoolExecutor(max_workers=len(tool_calls)) as pool:
        future_to_idx = {
            pool.submit(_execute_single_tool, tc, executors): i
            for i, tc in enumerate(tool_calls)
        }

        # Collect results, respecting timeout.  If some futures don't
        # finish in time, as_completed raises TimeoutError — we catch it
        # and fill placeholders below so the loop always continues.
        results: dict[int, _ToolResult] = {}
        try:
            for future in as_completed(future_to_idx, timeout=timeout):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    results[idx] = _ToolResult(
                        tool_call=tool_calls[idx],
                        result=f"[error] tool execution failed: {exc}",
                        signal=None,
                    )
        except TimeoutError:
            pass  # handled by placeholder logic below

    # Fill in timeout placeholders for any tool calls that didn't complete
    for i, tc in enumerate(tool_calls):
        if i not in results:
            results[i] = _ToolResult(
                tool_call=tc,
                result=f"[error] tool '{tc.name}' timed out after {timeout}s",
                signal=None,
            )

    # Append messages and trace in original order
    first_signal: ToolTerminationSignal | None = None
    for i in range(len(tool_calls)):
        tr = results[i]
        messages.append(Message(role="tool_call", content="", tool_call=tr.tool_call))

        with traced_span(tr.tool_call.name, span_type="tool") as tool_span:
            log_to_span(tool_span, input=tr.tool_call.args, output=tr.result)

        if not quiet:
            preview = tr.result[:300].replace("\n", " ")
            print(f"  -> {preview}")

        messages.append(
            Message(
                role="tool_result",
                content=tr.result,
                call_id=tr.tool_call.call_id,
            )
        )

        if first_signal is None and tr.signal is not None:
            first_signal = tr.signal

    return first_signal


# ---------------------------------------------------------------------------
# Iteration-based auto conversation (original)
# ---------------------------------------------------------------------------


def run_auto_conversation(
    llm: LLMInterface,
    tool_runner: ToolRunner,
    messages: list[Message],
    max_tool_cycles: int = 20,
    max_iterations: int = 50,
    quiet: bool = False,
) -> str:
    """
    Run a conversation automatically without user input until completion.

    Args:
        llm: The LLM instance with tools configured.
        tool_runner: The tool runner with registered tools.
        messages: The conversation messages (modified in place).
        max_tool_cycles: Maximum number of tool call cycles before forcing output.
        max_iterations: Maximum total LLM calls to prevent infinite loops.
        quiet: If True, suppress LLM status output for fallback LLM.

    Returns:
        The final text response from the LLM.

    Raises:
        RuntimeError: If max iterations exceeded without getting a response.
    """
    with traced_span("auto_conversation", span_type="task") as conversation_span:
        tool_cycles = 0
        current_llm = llm
        step = 0

        for _ in range(max_iterations):
            step += 1

            full_response, tool_calls = _run_llm_step(
                current_llm, messages, step, quiet=True
            )

            # Handle tool calls
            if tool_calls:
                tool_cycles += 1

                # Check if we've hit the tool cycle limit
                if tool_cycles >= max_tool_cycles:
                    # Add a message telling the LLM to output the JSON now
                    messages.append(
                        Message(
                            role="user",
                            content=(
                                "You have used the maximum number of tool calls. "
                                "Please output the final result now without any more tool calls."
                            ),
                        )
                    )
                    # Create a new LLM instance without tools to force text output
                    current_llm = get_llm(tools=None, quiet=quiet)
                    continue

                signal = _dispatch_tool_calls_toolrunner(
                    tool_calls, tool_runner, messages
                )
                if signal is not None:
                    log_to_span(
                        conversation_span,
                        output=signal.result,
                        metadata={
                            "total_steps": step,
                            "tool_cycles": tool_cycles,
                            "terminated_by_tool": True,
                        },
                    )
                    return signal.result
                continue

            # No tool calls = final response
            if full_response:
                messages.append(Message(role="assistant", content=full_response))
                log_to_span(
                    conversation_span,
                    output=full_response,
                    metadata={"total_steps": step, "tool_cycles": tool_cycles},
                )
                return full_response

        raise RuntimeError(f"Max iterations ({max_iterations}) exceeded")


# ---------------------------------------------------------------------------
# Time-based agent conversation
# ---------------------------------------------------------------------------


class AgentConversationResult:
    """Result of a time-based agent conversation."""

    __slots__ = ("terminated_by_tool", "timed_out", "tool_cycles", "llm_retries")

    def __init__(
        self,
        terminated_by_tool: bool = False,
        timed_out: bool = False,
        tool_cycles: int = 0,
        llm_retries: int = 0,
    ) -> None:
        self.terminated_by_tool = terminated_by_tool
        self.timed_out = timed_out
        self.tool_cycles = tool_cycles
        self.llm_retries = llm_retries


def run_agent_conversation(
    llm: LLMInterface,
    executors: dict[str, ToolExecutor],
    messages: list[Message],
    timeout_seconds: float = 300,
    shutdown_warning_seconds: float = 30,
    shutdown_message: str | None = None,
    no_tool_calls_message: str | None = None,
    force_finish_llm: LLMInterface | None = None,
    force_finish_message: str | None = None,
    parallel_tool_execution: bool = False,
    tool_timeout: float = 120,
    quiet: bool = False,
    context_compaction_fn: Callable[[list[Message]], None] | None = None,
    deadline_credit_fn: Callable[[], float] | None = None,
) -> AgentConversationResult:
    """Run a time-bounded agent conversation with custom tool executors.

    Unlike ``run_auto_conversation`` which is iteration-limited and uses
    ``ToolRunner``, this loop is wall-clock bounded and dispatches tool calls
    through a plain ``dict[str, Callable]``.  It also supports:

    - Context pruning when messages exceed a character threshold.
    - LLM error retries with back-off.
    - A graceful shutdown warning injected before the deadline.
    - A forced final LLM call (with a restricted tool set) after timeout.
    - A nudge message when the LLM responds without any tool calls.

    Tool executors may raise ``ToolTerminationSignal`` to end the conversation
    early (e.g. a ``finish`` tool).

    Args:
        llm: The LLM instance with tools configured.
        executors: Mapping of tool name → callable(**args) → str.
        messages: The conversation messages (modified in place).
        timeout_seconds: Wall-clock budget for the conversation.
        shutdown_warning_seconds: Seconds before deadline to inject the
            shutdown warning message.
        shutdown_message: Message injected when time is nearly up.
            Also used as the forced-finish message if *force_finish_message*
            is not set.
        no_tool_calls_message: If set, injected as a user nudge when the
            LLM responds with text but no tool calls.
        force_finish_llm: Optional LLM instance used for a single forced
            call after the deadline (typically configured with only a finish
            tool).  Skipped if ``None``.
        force_finish_message: User message prepended to the forced finish
            call.  Falls back to *shutdown_message*.
        parallel_tool_execution: If True, execute multiple tool calls from
            a single LLM response concurrently via threads.
        tool_timeout: Max seconds to wait for parallel tool calls to complete.
        quiet: Suppress streaming output and tool previews.
        context_compaction_fn: Optional callback invoked **reactively** when
            an LLM call fails with a context-overflow error.  When provided
            the pre-step ``prune_messages`` call is skipped so the
            conversation grows naturally until the LLM rejects it, at which
            point this callback compacts *messages* in place and the LLM
            call is retried.  At most ``_MAX_COMPACTIONS`` compactions are
            attempted per conversation to prevent infinite loops.
        deadline_credit_fn: Optional callable returning a cumulative number
            of seconds to credit back to the deadline.  For example, time
            spent waiting on a concurrency semaphore should not count
            against the question budget.  Called on every loop iteration.

    Returns:
        An ``AgentConversationResult`` with metadata about how the
        conversation ended.
    """
    start_time = time.monotonic()
    deadline = start_time + timeout_seconds

    step = 0
    tool_cycles = 0
    llm_retries = 0
    shutdown_injected = False
    compaction_count = 0

    def _credit() -> float:
        return deadline_credit_fn() if deadline_credit_fn is not None else 0.0

    with traced_span("agent_conversation", span_type="task") as conversation_span:
        while time.monotonic() < deadline + _credit():
            # Graceful shutdown warning
            credit = _credit()
            if (
                not shutdown_injected
                and shutdown_message
                and (time.monotonic() - start_time - credit)
                >= timeout_seconds - shutdown_warning_seconds
            ):
                shutdown_injected = True
                messages.append(Message(role="user", content=shutdown_message))

            step += 1
            # When a compaction callback is provided, skip the hard-coded
            # prune — context is managed reactively on overflow errors.
            if context_compaction_fn is None:
                prune_messages(messages)

            # LLM call with retry on error
            try:
                full_response, tool_calls = _run_llm_step(
                    llm, messages, step, quiet=quiet
                )
            except Exception as llm_err:
                # Reactive compaction: if the LLM rejects the request
                # because the context is too large, compact and retry.
                if (
                    context_compaction_fn is not None
                    and compaction_count < _MAX_COMPACTIONS
                    and _is_context_overflow_error(llm_err)
                ):
                    compaction_count += 1
                    if not quiet:
                        print(
                            f"\n[compaction] context overflow detected "
                            f"(compaction {compaction_count}/{_MAX_COMPACTIONS}), "
                            "summarising conversation...",
                            flush=True,
                        )
                    context_compaction_fn(messages)
                    continue  # retry immediately — no sleep

                llm_retries += 1
                if not quiet:
                    print(
                        f"\n[warn] LLM error (will retry): {llm_err}",
                        flush=True,
                    )
                time.sleep(5)
                continue

            if not quiet and full_response:
                print()

            # Dispatch tool calls
            if tool_calls:
                tool_cycles += 1
                if parallel_tool_execution and len(tool_calls) > 1:
                    signal = _dispatch_tool_calls_executor_parallel(
                        tool_calls,
                        executors,
                        messages,
                        quiet=quiet,
                        timeout=tool_timeout,
                    )
                else:
                    signal = _dispatch_tool_calls_executor(
                        tool_calls,
                        executors,
                        messages,
                        quiet=quiet,
                    )
                if signal is not None:
                    log_to_span(
                        conversation_span,
                        output=signal.result,
                        metadata={
                            "total_steps": step,
                            "tool_cycles": tool_cycles,
                            "llm_retries": llm_retries,
                            "terminated_by_tool": True,
                        },
                    )
                    return AgentConversationResult(
                        terminated_by_tool=True,
                        tool_cycles=tool_cycles,
                        llm_retries=llm_retries,
                    )
                continue

            # No tool calls — nudge or accept as final response
            if full_response:
                messages.append(Message(role="assistant", content=full_response))
            if no_tool_calls_message:
                messages.append(Message(role="user", content=no_tool_calls_message))
                continue

            # No nudge configured — treat text response as clean completion
            log_to_span(
                conversation_span,
                output=full_response,
                metadata={
                    "total_steps": step,
                    "tool_cycles": tool_cycles,
                    "llm_retries": llm_retries,
                },
            )
            return AgentConversationResult(
                tool_cycles=tool_cycles,
                llm_retries=llm_retries,
            )

        # --- Post-deadline: forced finish -----------------------------------
        elapsed = time.monotonic() - start_time
        if not quiet:
            print(
                f"\n[warn] time limit ({timeout_seconds}s) reached "
                f"after {step} step(s) (elapsed: {elapsed:.1f}s)"
            )

        if force_finish_llm is not None:
            fin_msg = force_finish_message or shutdown_message
            if fin_msg:
                messages.append(Message(role="user", content=fin_msg))
            if context_compaction_fn is None:
                prune_messages(messages)

            # Allow one reactive compaction + retry during forced finish.
            for _attempt in range(2):
                try:
                    full_response, tool_calls = _run_llm_step(
                        force_finish_llm, messages, step + 1, quiet=True
                    )
                    if tool_calls:
                        signal = _dispatch_tool_calls_executor(
                            tool_calls, executors, messages, quiet=quiet
                        )
                        if signal is not None:
                            log_to_span(
                                conversation_span,
                                output=signal.result,
                                metadata={
                                    "total_steps": step + 1,
                                    "tool_cycles": tool_cycles + 1,
                                    "llm_retries": llm_retries,
                                    "terminated_by_tool": True,
                                    "forced_finish": True,
                                },
                            )
                            return AgentConversationResult(
                                terminated_by_tool=True,
                                timed_out=True,
                                tool_cycles=tool_cycles + 1,
                                llm_retries=llm_retries,
                            )
                    elif full_response:
                        messages.append(
                            Message(role="assistant", content=full_response)
                        )
                    break  # success — no retry needed
                except Exception as exc:
                    if (
                        _attempt == 0
                        and context_compaction_fn is not None
                        and compaction_count < _MAX_COMPACTIONS
                        and _is_context_overflow_error(exc)
                    ):
                        compaction_count += 1
                        if not quiet:
                            print(
                                "\n[compaction] context overflow during "
                                "forced finish, compacting...",
                                flush=True,
                            )
                        context_compaction_fn(messages)
                        continue  # retry once
                    if not quiet:
                        print(f"\n[warn] forced finish LLM call failed: {exc}")
                    break

        log_to_span(
            conversation_span,
            metadata={
                "total_steps": step,
                "tool_cycles": tool_cycles,
                "llm_retries": llm_retries,
                "timed_out": True,
            },
        )
        return AgentConversationResult(
            timed_out=True,
            tool_cycles=tool_cycles,
            llm_retries=llm_retries,
        )
