"""Shared utilities for question generation scripts."""

import json
import os

from src.llm import Message, get_llm
from src.paths import QUESTIONS_PATH
from src.prompts.answer_generation import SINGLE_DOCUMENT_ANSWER_GENERATION
from src.prompts.question_fact_extraction import (
    ANTI_HALLUCINATION_FACT_VALIDATOR_PROMPT,
    FACT_EXTRACTION_PROMPT,
)
from src.utils.document_content import DocumentFieldError, extract_document_content
from src.utils.file_io import load_json_file
from src.utils.json_extraction import extract_json_from_response
from src.utils.path_resolver import sources_resolver


def load_document(
    doc_path: str,
) -> tuple[bool, str, str | None, str | None, str | None]:
    """
    Load a document and extract its UUID, title, and content.

    Args:
        doc_path: Path to the document relative to SOURCES_DIR.

    Returns:
        (success, message, dataset_doc_uuid, title, content) tuple.
        On failure, dataset_doc_uuid, title, and content are None.
    """
    full_path = sources_resolver.to_absolute(doc_path)

    try:
        doc_data = load_json_file(full_path)
    except Exception as e:
        return (False, f"Error loading document: {e}", None, None, None)

    dataset_doc_uuid = doc_data.get("dataset_doc_uuid")
    if not dataset_doc_uuid:
        return (False, "Document missing 'dataset_doc_uuid'", None, None, None)

    try:
        title, content = extract_document_content(doc_data)
    except DocumentFieldError as e:
        return (False, str(e), None, None, None)

    return (True, "OK", dataset_doc_uuid, title, content)


def generate_question(
    title: str,
    content: str,
    prompt_template: str,
    quiet: bool = False,
) -> str | None:
    """
    Generate a question for a document using the given prompt template.

    Args:
        title: Document title.
        content: Document content.
        prompt_template: Prompt template with {document_title} and {document_contents}.
        quiet: If True, suppress LLM output.

    Returns:
        Generated question string, or None on failure.
    """
    prompt = prompt_template.format(
        document_title=title,
        document_contents=content,
    )

    llm = get_llm(tools=None, quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            if not quiet:
                print(chunk, end="", flush=True)
            response += chunk

    if not quiet:
        print()

    question = response.strip()
    return question if question else None


def validate_question(
    title: str,
    content: str,
    question: str,
    quiet: bool = False,
    answer_prompt_template: str = SINGLE_DOCUMENT_ANSWER_GENERATION,
) -> tuple[bool, str | None]:
    """
    Validate a question against its source document and generate a gold answer.

    Args:
        title: Document title.
        content: Document content.
        question: Generated question to validate.
        quiet: If True, suppress LLM output.
        answer_prompt_template: Prompt template with {document_title},
            {document_contents}, and {query} placeholders.

    Returns:
        (valid, gold_answer) tuple.
        On failure, gold_answer is None.
    """
    prompt = answer_prompt_template.format(
        document_title=title,
        document_contents=content,
        query=question,
    )

    llm = get_llm(tools=None, quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            if not quiet:
                print(chunk, end="", flush=True)
            response += chunk

    if not quiet:
        print()

    response = response.strip()

    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        try:
            response = extract_json_from_response(response)
            data = json.loads(response)
        except Exception:
            return (False, None)

    is_valid = data.get("valid", False)
    if not is_valid:
        return (False, None)

    gold_answer = data.get("gold_answer")
    if not gold_answer or gold_answer == "N/A":
        return (False, None)

    return (True, gold_answer)


def extract_answer_facts(
    question: str,
    gold_answer: str,
    quiet: bool = False,
) -> list[str] | None:
    """
    Extract atomic facts from a gold answer.

    Args:
        question: The question that the gold answer answers.
        gold_answer: The gold answer to extract facts from.
        quiet: If True, suppress LLM output.

    Returns:
        List of fact strings, or None on failure.
    """
    prompt = FACT_EXTRACTION_PROMPT.format(question=question, gold_answer=gold_answer)

    llm = get_llm(tools=None, quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            if not quiet:
                print(chunk, end="", flush=True)
            response += chunk

    if not quiet:
        print()

    response = response.strip()

    try:
        facts = json.loads(response)
    except json.JSONDecodeError:
        try:
            response = extract_json_from_response(response)
            facts = json.loads(response)
        except Exception:
            return None

    if not isinstance(facts, list):
        return None

    return facts


def extract_anti_hallucination_facts(
    facts: list[str],
    quiet: bool = False,
) -> list[str] | None:
    """
    Identify anti-hallucination guard facts from a list of facts.

    These are negation-type statements that prevent hallucinations
    (e.g., "the answer should not mention X").

    Args:
        facts: List of fact strings to filter.
        quiet: If True, suppress LLM output.

    Returns:
        List of anti-hallucination fact strings, or None on failure.
    """
    prompt = ANTI_HALLUCINATION_FACT_VALIDATOR_PROMPT.format(
        fact_list=json.dumps(facts),
    )

    llm = get_llm(tools=None, quiet=quiet)
    messages: list[Message] = [Message(role="user", content=prompt)]

    response = ""
    for chunk in llm.generate(messages):
        if isinstance(chunk, str):
            if not quiet:
                print(chunk, end="", flush=True)
            response += chunk

    if not quiet:
        print()

    response = response.strip()

    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        try:
            response = extract_json_from_response(response)
            result = json.loads(response)
        except Exception:
            return None

    if not isinstance(result, list):
        return None

    return result


def normalize_text(text: str) -> str:
    """Replace special Unicode characters with their ASCII equivalents."""
    replacements = {
        "\u2011": "-",  # non-breaking hyphen → hyphen
        "\u2010": "-",  # hyphen → hyphen-minus
        "\u2012": "-",  # figure dash
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u2015": "-",  # horizontal bar
        "\u2018": "'",  # left single quotation mark
        "\u2019": "'",  # right single quotation mark
        "\u201a": "'",  # single low-9 quotation mark
        "\u201b": "'",  # single high-reversed-9 quotation mark
        "\u201c": '"',  # left double quotation mark
        "\u201d": '"',  # right double quotation mark
        "\u201e": '"',  # double low-9 quotation mark
        "\u201f": '"',  # double high-reversed-9 quotation mark
        "\u2026": "...",  # ellipsis
        "\u00a0": " ",  # non-breaking space
        "\u2003": " ",  # em space
        "\u2002": " ",  # en space
        "\u2009": " ",  # thin space
        "\u200a": " ",  # hair space
        "\u00b7": "*",  # middle dot → asterisk
        "\u2022": "*",  # bullet → asterisk
        "\u2032": "'",  # prime
        "\u2033": '"',  # double prime
    }
    for original, replacement in replacements.items():
        text = text.replace(original, replacement)
    return text


def save_question(
    question_id: str,
    question: str,
    expected_doc_ids: list[str],
    source_types: list[str],
    gold_answer: str,
    answer_facts: list[str],
    question_type: str,
    path: str = QUESTIONS_PATH,
) -> None:
    """
    Save a question entry to the questions JSONL file with standardized field order.

    Fields are always written in this order:
        question_id, question_type, source_types, question, expected_doc_ids,
        gold_answer, answer_facts
    """
    question_data = {
        "question_id": question_id,
        "question_type": question_type,
        "source_types": source_types,
        "question": normalize_text(question),
        "expected_doc_ids": expected_doc_ids,
        "gold_answer": normalize_text(gold_answer),
        "answer_facts": [normalize_text(fact) for fact in answer_facts],
    }
    append_to_jsonl(path, question_data)


def extract_source_type(doc_path: str) -> str:
    """Extract the source type (top-level directory) from a path relative to SOURCES_DIR.

    Example: "gmail/user/doc.json" -> "gmail"
    """
    return doc_path.split(os.sep)[0]


def append_to_jsonl(path: str, data: dict) -> None:
    """Append a JSON object to a JSONL file."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


def count_existing_questions() -> int:
    """Count existing questions in the questions.jsonl file."""
    if not os.path.exists(QUESTIONS_PATH):
        return 0

    count = 0
    with open(QUESTIONS_PATH) as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def get_next_question_id() -> int:
    """Get the next question ID number based on existing questions."""
    if not os.path.exists(QUESTIONS_PATH):
        return 1

    max_id = 0
    with open(QUESTIONS_PATH) as f:
        for line in f:
            if line.strip():
                try:
                    data = json.loads(line)
                    question_id = data.get("question_id", "")
                    if question_id.startswith("qst_"):
                        num = int(question_id.replace("qst_", ""))
                        max_id = max(max_id, num)
                except (json.JSONDecodeError, ValueError):
                    pass

    return max_id + 1


def get_existing_doc_uuids() -> set[str]:
    """Get set of document UUIDs already used in questions (from expected_doc_ids)."""
    uuids: set[str] = set()
    if not os.path.exists(QUESTIONS_PATH):
        return uuids

    with open(QUESTIONS_PATH) as f:
        for line in f:
            if line.strip():
                try:
                    data = json.loads(line)
                    if "expected_doc_ids" in data:
                        for doc_id in data["expected_doc_ids"]:
                            uuids.add(doc_id)
                    elif "dataset_doc_uuid" in data:
                        uuids.add(data["dataset_doc_uuid"])
                except json.JSONDecodeError:
                    pass

    return uuids
