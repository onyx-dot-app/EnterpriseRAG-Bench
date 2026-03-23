# IndustryRAG-Bench

## 📖 Overview

IndustryRAG Bench provides a dataset for company internal documents as well as a way of generating similar datasets for different industries, scales of companies, etc.
Existing Retrieval Augmented Generation (RAG) and Information Retrieval (IR) datasets largely focus on publically accessible document sets (Bing searches, Stack Overflow forums, etc.).
Up until now, there hasn't been a publically accessible dataset which focuses entirely on company internal data. This dataset/repo aims to provide that.

The dataset consists of ~500,000 documents and 500 questions. It simulates a company called "Redwood Inference" that provides AI model inference as a service.

The data sources and rough volumes are as follows:
- Slack: ~275,000 docs
- Gmail: ~120,000 docs
- Linear: ~35,000 docs
- Google Drive: ~25,000 docs
- Hubspot: ~15,000 docs
- Fireflies: ~10,000 docs
- GitHub: ~8,000 docs
- Jira: ~6,000 docs
- Confluence: ~5,000 docs

The corpus provides broad coverage across key areas of business activity including (but not limited to) planning, engineering, documentation, sales, customer success, internal discussions, emails, and more.

## Using the dataset

> [!TIP]
> For more info on getting started refer to the [Quickstart Guide](quickstart.md)

The dataset is downloadable from the release notes and also under export_data. To get the entire dataset as a single zip file, download [all_documents.zip](export_data/all_documents.zip).

The question set can be found in [questions.jsonl](export_data/questions.jsonl).

## Key Considerations

To make this dataset as realistic as possible, the generation begins by gathering high level information about the company, initiatives, applications used, etc.
Documents are generated with both high level knowledge and other documents to ensure they are meaningfully connected and coherent (as they would be in a real company).

Noise is also introduced after the initial generation through steps like shuffling documents, creating near duplicates, etc. These steps act to simulate the imperfect nature of real company data.

Finally to ensure users can realistically generate their own customized datasets, the entire process is designed with cost-optimization in mind.
Some documents need to be more strongly related to answer more interesting question types in which case more cost is acceptable.
But at the scales of many hundreds of thousands of documents, documents cannot all be fully aware of one another without the cost exploding.
More intelligent ways of communicating knowledge between documents is required to accomplish this.

For more details on the process, refer to [methodology.md](methodology.md)

## Benchmark

There will be a leaderboard released for the IndustryRAG Benchmark shortly. As Onyx is also a company which sells a product based around LLMs and RAG, we will not include ourselves on the leaderboard to avoid any conflicts of interest.

To provide a submission for the leaderboard please reach out to joachim@onyx.app. Submissions are required to provide a method of verification.
- For open source applications, please provide a guide for reproducing results.
- For closed source applications, please provide a sandbox or URL where the questions can be sent for verification.

## Citation

If you use IndustryRAG Bench in your research, please cite our paper: TBD
