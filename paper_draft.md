# IndustryRAG-Dataset

## Abstract
**Retrieval-Augmented Generation (RAG)** has become the standard approach for grounding large language models in information that was not available during training. While many existing datasets and benchmarks focus on web or other public sources, there is still no widely adopted dataset that realistically reflects the nature of internal company knowledge. Meanwhile, startups, enterprises, and researchers are increasingly developing Agents designed to operate over exactly this kind of proprietary data. To help close this gap, we introduce a new dataset that simulates enterprise knowledge environments and provide a flexible framework for extending and tailoring the data to specific use cases.

Key considerations:
1. **Enterprise data varies widely** across industries, company stages, and organizational structures; therefore, any dataset-generation framework must be sufficiently general to support diverse real-world settings.
2. To better mirror real usage, documents should be **meaningfully connected** through shared initiatives, recurring themes, overlapping topics, common authorship, and other organizational relationships.
3. Real-world enterprise corpora are often **imperfect and noisy**, including misfiled or poorly organized documents, duplicates, and partially conflicting or outdated information; a representative dataset should capture these characteristics rather than assuming a clean, curated knowledge base.


## Methodology
NOTE: The stuff below needs a rewrite.

We begin with a list of the main challenges addressed in the different stages of the dataset creation

Phase 1: Creating the clean data.
1. The documents need to have consistent guiding principles behind them to ensure they are realistic to the company / industry they are being generated for.
2. The generation process must allow for interdependencies between individual documents. For example code changes (Pull-Requests) are necessarily linked to Product Requirement Documents (PRDs).
3. The distribution of documents should be realistic to real world data. As a basic example, there is likely to be orders of magnitude more discussions channel messages (Slack/MS Teams/Discord) as compared to polish product documentation.
4. The creation of the data must allow for the generation of interesting questions for the dataset, the questions must be verifiable and answerable by the underlying data.
5. The dataset creation process should be flexible to industry (or vertical) specific use cases and able to handle different volumes of artificial data generation (at least to some maximum number of documents).
6. The creation of large volumes of data should not be prohibitively expensive.

Phase 2: Adding noise to the data