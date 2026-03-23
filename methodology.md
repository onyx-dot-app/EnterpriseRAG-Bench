# Data Generation Methodology

## Core challenges

The following are a list of requirements and challenges addressed by the specific approach described in more detail in the sections below.

1. The documents need to have consistent guiding principles behind them to ensure they are realistic to the company / industry they are being generated for.
2. The generation process must allow for interdependencies between individual documents. For example code changes (Pull-Requests) are necessarily linked to Product Requirement Documents (PRDs).
3. The distribution of documents should be realistic to real world data. For example, there are typically orders of magnitude more discussions channel messages (Slack/MS Teams/Discord) as compared to polished product documentation.
4. The creation of the data must allow for the generation of interesting questions for the dataset, the questions must be verifiable and answerable by the underlying data.
5. The dataset creation process should be flexible to industry (or vertical) specific use cases and able to handle different volumes of artificial data generation (at least to some maximum number of documents).
6. Being an LLM based generation process, it must work around the patterns and limitations of LLMs. For example, asking the system to generate 1M documents about a hypothetical company without further guardrails and guidance leads to
many hundreds to thousands of nearly identical documents clustered around a very few select topics. Even if the LLM were aware of all the other documents, this pattern still emerges very early on.
7. The document set must have a realistic level of noise. This includes things like misplaced documents, contradictory statements, ambiguous information, etc.
8. The creation of large volumes of data should not be prohibitively expensive.

## High level process

