"""Script for generating high-level questions from company overview and initiatives.

Produces questions answerable from broad organizational context rather than specific
documents. Candidates are generated in batch, then validated by an LLM agent with
corpus exploration tools to reject any question answerable from a single document.
These questions carry no expected document IDs since the answer is distributed across
the corpus.

Usage:
    python -m src.scripts.data_gen_stage_3_generate_questions.step_9_generate_high_level_questions [OPTIONS]

Args:
    --count            Number of validated questions to produce (default: 10)
    --num-candidates   Number of candidate queries to generate before filtering (default: 20)
    --parallelism      Number of parallel workers for answer generation (default: 1)
    --skip-validation  Skip the tool-based validation step
    --quiet            Suppress LLM output streaming
"""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.llm import Message, ToolCall, get_llm
from src.paths import (
    COMPANY_OVERVIEW_PATH,
    INITIATIVES_PATH,
    QUESTIONS_PATH,
    SOURCES_DIR,
)
from src.prompts.high_level_questions import (
    HIGH_LEVEL_QUESTIONS_EVALUATION_PROMPT,
    HIGH_LEVEL_QUESTIONS_PROMPT,
    USER_PROMPT,
    VALIDATE_NO_POINT_QUERY_PROMPT,
)
from src.tools import GLOB_TOOL, GREP_TOOL, LS_TOOL, READ_TOOL
from src.tools.runner import ToolRunner
from src.tools.tool_implementations import GlobTool, GrepTool, LsTool, ReadTool
from src.utils import (
    count_existing_questions,
    extract_answer_facts,
    extract_json_from_response,
    get_directory_tree,
    get_next_question_id,
    load_file,
    save_question,
)

STEP_OVERVIEW = """\
Generates questions answerable from the company overview and initiatives but
not from any single corpus document. An LLM agent validates each candidate by
searching the corpus; questions answerable from a single document are rejected.
These carry no expected document IDs.
"""


# =============================================================================
# Query Generation
# =============================================================================


def generate_queries(
    company_overview: str,
    initiatives: str,
    num_queries: int,
    quiet: bool = False,
) -> list[str]:
    """
    Generate a batch of high-level queries from company overview and initiatives.

    Returns:
        List of query strings.
    """
    system_prompt = HIGH_LEVEL_QUESTIONS_PROMPT.format(
        company_overview=company_overview,
        initiatives=initiatives,
    )
    user_prompt = USER_PROMPT.format(num_queries=num_queries)

    llm = get_llm(tools=None, quiet=quiet)
    messages: list[Message] = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user_prompt),
    ]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            if not quiet:
                print(chunk, end="", flush=True)
            response += chunk

    if not quiet:
        print()

    response = response.strip()

    # Parse JSON response
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        try:
            response = extract_json_from_response(response)
            data = json.loads(response)
        except Exception:
            return []

    if not isinstance(data, dict):
        return []

    # Extract queries from numbered keys
    queries: list[str] = []
    for key in sorted(data.keys(), key=lambda k: int(k)):
        query = data[key]
        if isinstance(query, str) and query.strip():
            queries.append(query.strip())

    return queries


# =============================================================================
# Query Validation
# =============================================================================


MAX_VALIDATION_TOOL_CYCLES = 8


def validate_query(
    query: str,
    directory_structure: str,
    quiet: bool = False,
) -> bool:
    """
    Validate that a query is truly high-level and not answerable from a single document.

    Uses tools to search the document set. Prints each tool call.
    Returns True if the query is valid (not answerable from a single document).
    """
    prompt = VALIDATE_NO_POINT_QUERY_PROMPT.format(
        directory_structure=directory_structure,
        GLOB_TOOL=GLOB_TOOL,
        GREP_TOOL=GREP_TOOL,
        LS_TOOL=LS_TOOL,
        READ_TOOL=READ_TOOL,
        query=query,
    )

    # Set up tools
    glob_tool = GlobTool(base_dir=SOURCES_DIR)
    grep_tool = GrepTool(base_dir=SOURCES_DIR)
    ls_tool = LsTool(base_dir=SOURCES_DIR)
    read_tool = ReadTool(base_dir=SOURCES_DIR)

    tool_runner = ToolRunner()
    tool_runner.register(glob_tool)
    tool_runner.register(grep_tool)
    tool_runner.register(ls_tool)
    tool_runner.register(read_tool)

    tools = [glob_tool.schema, grep_tool.schema, ls_tool.schema, read_tool.schema]
    llm = get_llm(tools=tools, reasoning_level="high", quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    tool_cycles = 0

    for _ in range(MAX_VALIDATION_TOOL_CYCLES + 5):
        full_response = ""
        tool_calls: list[ToolCall] = []

        for chunk in llm.generate(messages):
            if isinstance(chunk, str):
                full_response += chunk
            elif isinstance(chunk, ToolCall):
                tool_calls.append(chunk)

        if tool_calls:
            tool_cycles += 1

            if tool_cycles > MAX_VALIDATION_TOOL_CYCLES:
                messages.append(
                    Message(
                        role="user",
                        content=(
                            "You have used the maximum number of tool calls. "
                            "Please output 'valid' or 'invalid' now."
                        ),
                    )
                )
                llm = get_llm(tools=None, quiet=quiet)
                continue

            for tc in tool_calls:
                args_str = ", ".join(f"{k}={v!r}" for k, v in tc.args.items())
                print(f"      tool: {tc.name}({args_str})")

                messages.append(Message(role="tool_call", content="", tool_call=tc))
                result = tool_runner.run(tc.name, **tc.args)
                messages.append(
                    Message(role="tool_result", content=result, call_id=tc.call_id)
                )

            continue

        # No tool calls — final response
        if full_response:
            response = full_response.strip().lower()
            return "valid" in response and "invalid" not in response

    return False


# =============================================================================
# Single Question Processing
# =============================================================================


def process_single_query(
    query: str,
    reference_documents: str,
    quiet: bool = False,
) -> tuple[bool, str, dict | None]:
    """
    Process a single query: generate gold answer and extract facts.

    Returns:
        (success, message, question_data) tuple.
        On failure, question_data is None.
    """
    query_label = query[:60]

    # Generate gold answer
    if not quiet:
        print("\n--- Generating Gold Answer ---")

    prompt = HIGH_LEVEL_QUESTIONS_EVALUATION_PROMPT.format(
        reference_documents=reference_documents,
        query=query,
    )

    llm = get_llm(tools=None, reasoning_level="high", quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            if not quiet:
                print(chunk, end="", flush=True)
            response += chunk

    if not quiet:
        print()

    gold_answer = response.strip()
    if not gold_answer:
        return (False, f"{query_label}: Empty gold answer", None)

    if not quiet:
        print(f"\nGold answer: {gold_answer[:200]}...")

    # Extract answer facts
    if not quiet:
        print("\n--- Extracting Answer Facts ---")

    answer_facts = extract_answer_facts(query, gold_answer, quiet=quiet)

    if not answer_facts:
        return (False, f"{query_label}: Answer fact extraction failed", None)

    if not quiet:
        print(f"\nExtracted {len(answer_facts)} facts")

    question_data = {
        "question": query,
        "expected_doc_ids": [],
        "source_types": [],
        "gold_answer": gold_answer,
        "answer_facts": answer_facts,
        "question_type": "high_level",
    }

    return (True, f"{query_label}: Success", question_data)


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate high-level questions from company overview and initiatives."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of validated questions to produce (default: 10)",
    )
    parser.add_argument(
        "--num-candidates",
        type=int,
        default=20,
        help="Number of candidate queries to generate before filtering (default: 20)",
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=1,
        help="Number of parallel workers for answer generation (default: 1, verbose output)",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip the tool-based validation step",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress LLM output streaming",
    )
    args = parser.parse_args()

    print("Step 9: Generate High-Level Questions")
    print("=" * 40)
    print(STEP_OVERVIEW)

    # Check required upstream files
    missing: list[str] = []
    if not os.path.exists(COMPANY_OVERVIEW_PATH):
        missing.append(
            f"  - {COMPANY_OVERVIEW_PATH} (run Stage 1 Step 1: step_1_generate_company_overview)"
        )
    if not os.path.exists(INITIATIVES_PATH):
        missing.append(
            f"  - {INITIATIVES_PATH} (run Stage 1 Step 2: step_2_generate_initiatives)"
        )
    if missing:
        print("Missing required files:")
        for m in missing:
            print(m)
        return

    # Load reference documents
    company_overview = load_file(COMPANY_OVERVIEW_PATH)
    initiatives = load_file(INITIATIVES_PATH)

    reference_documents = (
        f"## Company Overview\n{company_overview}\n\n## Initiatives\n{initiatives}"
    )
    print(
        f"Loaded company overview ({len(company_overview)} chars) and initiatives ({len(initiatives)} chars)."
    )

    # Build directory structure for validation (only needed if validating)
    if not args.skip_validation:
        directory_structure = get_directory_tree(SOURCES_DIR)
    else:
        directory_structure = ""

    # Generate candidate queries in a single batch
    print(f"\n--- Generating {args.num_candidates} Candidate Queries ---")
    candidates = generate_queries(
        company_overview, initiatives, args.num_candidates, quiet=args.quiet
    )

    if not candidates:
        print("No candidate queries generated.")
        return

    print(f"\nGenerated {len(candidates)} candidate queries.")

    # Validate candidates — filter until --count is reached
    if args.skip_validation:
        print("\nSkipping validation (--skip-validation is set).")
        valid_queries = candidates[: args.count]
    else:
        print(f"\n--- Validating Candidates (target: {args.count}) ---")
        valid_queries = []

        for i, query in enumerate(candidates):
            if len(valid_queries) >= args.count:
                break

            print(f"\n  [{i + 1}/{len(candidates)}] Validating: {query[:80]}")
            is_valid = validate_query(query, directory_structure, quiet=True)

            if is_valid:
                valid_queries.append(query)
                print(f"    -> VALID ({len(valid_queries)}/{args.count})")
            else:
                print("    -> INVALID (answerable from single document)")

        print(
            f"\n{len(valid_queries)} valid queries out of {len(candidates)} candidates."
        )

    if not valid_queries:
        print("No valid high-level queries found. Try increasing --num-candidates.")
        return

    if len(valid_queries) < args.count:
        print(
            f"\nWarning: Only {len(valid_queries)} valid queries produced out of "
            f"{args.count} desired. Consider increasing --num-candidates."
        )

    # Load existing question state
    next_question_id = get_next_question_id()
    existing_questions = count_existing_questions()

    if existing_questions > 0:
        print(f"Found existing questions file: {QUESTIONS_PATH}")
        print(f"  Existing questions: {existing_questions}")
        print(f"  Next question ID: qst_{next_question_id:04d}")
        print("  New questions will be appended to this file.")
    else:
        print(f"Questions file not found. Will create: {QUESTIONS_PATH}")

    print()
    print(
        f"Processing {len(valid_queries)} validated queries with parallelism={args.parallelism}."
    )
    print()

    success_count = 0
    fail_count = 0
    errors: list[str] = []

    if args.parallelism <= 1:
        # Sequential mode — verbose output
        for i, query in enumerate(valid_queries):
            print("\n" + "-" * 40)
            print(f"Query {i + 1} of {len(valid_queries)}: {query}")
            print("-" * 40)

            success, message, question_data = process_single_query(
                query, reference_documents, quiet=args.quiet
            )

            if not success or not question_data:
                fail_count += 1
                errors.append(message)
                print(f"\nFailed: {message}")
                continue

            # Assign question ID and save
            question_id = f"qst_{next_question_id:04d}"
            save_question(
                question_id=question_id,
                question=question_data["question"],
                expected_doc_ids=question_data["expected_doc_ids"],
                source_types=question_data["source_types"],
                gold_answer=question_data["gold_answer"],
                answer_facts=question_data["answer_facts"],
                question_type=question_data["question_type"],
            )
            next_question_id += 1
            success_count += 1
            print(f"\nSaved question {question_id}")
    else:
        # Parallel mode — quiet workers, collect results
        results: list[tuple[int, bool, str, dict | None]] = []

        with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
            futures = {
                executor.submit(
                    process_single_query,
                    query,
                    reference_documents,
                    True,  # quiet=True for parallel workers
                ): idx
                for idx, query in enumerate(valid_queries)
            }

            for future in as_completed(futures):
                idx = futures[future]
                try:
                    success, message, question_data = future.result()
                    results.append((idx, success, message, question_data))
                    status = "OK" if success else "FAIL"
                    print(f"  [{idx + 1}/{len(valid_queries)}] {status}: {message}")
                except Exception as e:
                    results.append((idx, False, str(e), None))
                    print(f"  [{idx + 1}/{len(valid_queries)}] ERROR: {e}")

        # Save results in original order to keep question IDs deterministic
        results.sort(key=lambda r: r[0])

        for idx, success, message, question_data in results:
            if not success or not question_data:
                fail_count += 1
                errors.append(message)
                continue

            question_id = f"qst_{next_question_id:04d}"
            save_question(
                question_id=question_id,
                question=question_data["question"],
                expected_doc_ids=question_data["expected_doc_ids"],
                source_types=question_data["source_types"],
                gold_answer=question_data["gold_answer"],
                answer_facts=question_data["answer_facts"],
                question_type=question_data["question_type"],
            )
            next_question_id += 1
            success_count += 1

    print("\n" + "=" * 40)
    print("Summary")
    print("=" * 40)
    print(f"Successfully generated: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"Total questions in file: {count_existing_questions()}")

    if success_count < args.count:
        print(
            f"\nWarning: Only {success_count} questions created out of "
            f"{args.count} desired."
        )

    if errors:
        print()
        print("Errors:")
        for error in errors[:20]:
            print(f"  - {error}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")

    print(
        "\nThis step is complete, go on to step 10 to generate info_not_found questions."
    )


if __name__ == "__main__":
    main()
