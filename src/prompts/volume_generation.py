from src.paths import AGENTS_MD_FILE

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