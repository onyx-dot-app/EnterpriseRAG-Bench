# Data Generation Methodology

## Core challenges

The following are a list of requirements and challenges addressed by the specific approach described in more detail in the sections below.

1. The documents need to have consistent guiding principles behind them to ensure they are realistic to the company / industry they are being generated for.
2. The generation process must allow for interdependencies between individual documents. For example code changes (Pull-Requests) are necessarily linked to Product Requirement Documents (PRDs).
3. The distribution of documents should be realistic to real world data. For example, there are typically orders of magnitude more discussions channel messages (Slack/MS Teams/Discord) as compared to polished product documentation.
4. The document set must have a realistic level of noise. This includes things like misplaced documents, contradictory statements, ambiguous information, etc.
5. The creation of the data must allow for the generation of interesting questions for the dataset (not just simple backgenerating questions from single documents), the questions must be verifiable and answerable by the underlying data.
6. The dataset creation process should be flexible to industry (or vertical) specific use cases and able to handle different volumes of artificial data generation (at least to some maximum number of documents).
7. Being an LLM based generation process, it must work around the limitations and tendencies of LLMs.
8. The creation of large volumes of data should not be prohibitively expensive.

## High level process

At a high level, the process starts by generating structural, top-level information that guides downstream generation and keeps the dataset internally consistent.
It is human-in-the-loop, allowing users to provide key context such as the hypothetical company’s industry, available data sources, and active initiatives or projects.
Once this foundation is set, the system generates a core set of documents that are tightly informed by these details and by previously generated outputs.
It then defines generation guardrails to keep document distributions aligned with expectations and prevent over-clustering around LLM-favored topics.
With those rails in place, the system produces the larger-volume document set needed for scale, using high-level context and less detail to improve cost efficiency.

### Step 1
To help create a cohere dataset, we begin by generating high level overview about the company to guide all later steps. The user interacts with an LLM to cover topics including:
- Company
