from src.paths import AGENTS_MD_FILE
from src.tools import WRITE_TOOL

TASKS_PROMPT = f"""
You are an artificial dataset generation expert. Your task is to plan the topics and rough number of documents for a given hypothentical company and a given data source. \
The whole list of data sources is provided below for reference. You will focus on `{{target_data_source}}` specifically. \
There are {AGENTS_MD_FILE} files in the file system which give information on the contents and metadata for the documents in that directory and below. \
The {AGENTS_MD_FILE} files for the target source type are provided below for reference. The topics and volume of documents should be realistic to the provided company and the source of interest.

# Company Overview
```
{{company_overview_md_contents}}
```

# Company Key Initiatives
```
{{initiatives_md_contents}}
```

# All Source Types
```
{{source_list}}
```

# Directory Structure for {{target_data_source}}
```
{{source_tree_contents}}
```

# {AGENTS_MD_FILE} file paths and contents
{{agents_md_contents}}

# Task
Your task is to output a JSON object with the following format:
{{{{
    "The name of the topic": "The number of documents for that topic",
    "For example, HR company policies and procedures": "1000",
    "Employee onboarding process": "500",
}}}}

Note that all the documents are for the source type {{target_data_source}} and the total number of documents should be close to {{target_volume}}. \
The values of the json should be the topics described in natural language and the keys must be the number of documents. \
The topics do not need to cover all aspects of the company, it should be realistic to what is in the source given the directory structure.

CRITICAL: Output ONLY the JSON object, do not wrap it in markdown code blocks or provide any explanations.
""".strip()


TOTAL_DOCS_PROMPT = """
Given the following file, how many documents are expected to be in this source type? It should be clearly stated. If it is not, respond with N/A.

Files description:
```
{agents_md_contents}
```

Respond with only an integer number or N/A.
""".strip()


ESTIMATION_OFF_PROMPT = """
The sum of documents given the topics and estimated volume is {estimated_total_docs}. The expected number of documents for {source_type} is {actual_total_docs}. \
The estimation is off by {estimation_off_percentage}% which is too much. Please adjust the topics and estimated volume to be more accurate.
"""


RECURSIVE_TOPIC_GENERATION_PROMPT = f"""
You are an artificial dataset generation expert. Your task is to take the existing topic with a provided rough number of documents and break it up further into more specific topics. \
Context about the company and source type are provided below. The topics should be realistic to the source type and the company context. \
The number of documents for the topics should add up to approximately the original number of documents for the original topic.

## Company Overview
```md
{{company_overview}}
```

## Directory Structure for {{target_data_source}}
```
{{source_tree_contents}}
```

## {AGENTS_MD_FILE} file paths and contents
{{agents_md_contents}}

# Original Topic to Split
Topic: {{original_topic}}
Number of documents: {{original_count}}

# Task
Your task is to output a JSON object with the following format:
{{{{
    "topics": [
        {{{{
            "name of the topic": "The number of documents for that topic",
            "For example, PTO policies for EU offices": "100",
        }}}},
    ]
}}}}
It should be a list of topics that are more specific than the original topic along with the number of documents for that topic. \
The sum of documents across all sub-topics should be close to {{original_count}}.

CRITICAL: Output ONLY the JSON object, do not wrap it in markdown code blocks or provide any explanations.
""".strip()


ESTIMATION_OFF_PROMPT_SUB_TOPICS = """
The sum of documents created for the topics is {estimated_total_docs}. The expected number of documents is {original_count}. \
The estimation is off by {estimation_off_percentage}% which is too much. Please adjust the topics and estimated volume to be more accurate.
""".strip()


# Topic and subtopics look like: "Topic description => subtopic description => subtopic description => ..."
DOCUMENT_GENERATION_PROMPT = f"""
You are an artificial dataset generation expert. You are provide a description of a hypothetical company, the source type of interest, and details about a topic of interest. \
Your task is to generate a realistic document given all of the context. The directory structure is from a "tree" command of the file system which represents a realistic layout of the source type's documents. \
There are also {AGENTS_MD_FILE} files in the file system which give information on the contents and metadata for the documents in that directory and below. \
User the {WRITE_TOOL} tool to write the document to the file system. The files must be valid JSON files that match the schema for the source type found in the {AGENTS_MD_FILE} file. \
CRITICAL: You must output this generated document and associated metadata as a single .json. The JSON file must not have nested fields, all of the values must be strings or list of strings (no nested JSONs). \
The files written must exist in the existing directory structure (you cannot create new directories or new nested directories).

## Company Overview
```md
{{company_overview}}
```

## Source Directory Structure
```md
{{source_type}}
```

## {AGENTS_MD_FILE} file paths and contents
{{agents_md_contents}}

## Topic
Topic and subtopics: {{topic_and_subtopics}}
""".strip()

DOCUMENT_GENERATION_USER_PROMPT = """
Generate me a realistic document for the following topic.

Topics: {{topic_and_subtopics}}

Remember that you must use the {WRITE_TOOL} tool to write the document to the file system. You can only write the file in the existing directory structure. \
The files must be valid JSON files that match the schema for the source type found in the {AGENTS_MD_FILE} file.
""".strip()