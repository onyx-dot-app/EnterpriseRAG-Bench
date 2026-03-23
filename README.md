# IndustryRAG-Bench

## 📖 Overview

IndustryRAG Bench provides a dataset for company internal documents as well as a way of generating similar datasets for different industries, scales of companies, etc.

The dataset simulates a company called "Redwood Inference" that provides AI model inference as a service. The dataset consists of **~500,000 documents** spread across the following sources:

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

The dataset comes with **500 questions** (see [questions.jsonl](generated_data/questions.jsonl)) broken up into 10 categories:

| # | Category | Count | Description |
|---|----------|-------|-------------|
| 1 | Basic | 200 | Simple questions with a single ground truth document. |
| 2 | Semantic | 100 | Similar to Basic but more roundabout, with less keyword/phrase overlap and without giveaway-type keywords. |
| 3 | Single Doc Multi-hop | 50 | Requires combining information from several distant sections of a single longer document. |
| 4 | Project Related | 40 | Aggregate knowledge from related documents from a single project/initiative within the company. |
| 5 | Constrained | 30 | Questions with multiple relevant documents but with qualifiers that disqualify all but one answer. |
| 6 | Conflicting Info | 20 | Questions where documents directly contradict each other. Requires the system to give a complete and correct answer. |
| 7 | Completeness | 10 | Questions that require fetching all relevant documents (no more than 10) to be able to provide a correct answer. |
| 8 | Misplaced | 20 | Questions requiring finding documents which are not optimally placed within the knowledge base. |
| 9 | High Level | 10 | High level questions where the answer is not located in any single document. Note: these do not have any ground truth documents. |
| 10 | Info Not Found | 20 | Questions where the answer is not available. Note: these do not have any ground truth documents. |

Additionally 100 questions are provided outside of the benchmark which require parsing the metadata of the documents to answer correctly.
This is included to enable teams that need it for real world use cases but omitted from the benchmark since it is harder to standardize.

Existing Retrieval Augmented Generation (RAG) and Information Retrieval (IR) datasets largely focus on publically accessible document sets (Bing searches, Stack Overflow forums, etc.).
Up until now, there hasn't been a publically accessible dataset which focuses entirely on company internal data. This dataset/repo aims to provide that.

## Using the dataset

> [!TIP]
> For more info on getting started refer to the [Quickstart Guide](quickstart.md)

The dataset is downloadable from the release notes and also under export_data. To get the entire dataset as a single zip file, download [all_documents.zip](export_data/all_documents.zip).

The question set can be found in [questions.jsonl](export_data/questions.jsonl).

## Key Considerations

To make this dataset as realistic as possible, the generation begins by gathering high level information about the company, initiatives, applications used, etc.
Documents are generated with both high level knowledge and other documents to ensure they are meaningfully connected and coherent (as they would be in a real company).

Noise is also introduced after the initial generation through steps like shuffling documents, creating near duplicates, etc. These steps act to simulate the imperfect nature of real company data.

To keep custom dataset generation realistic for users, the process is designed with cost efficiency as a core constraint:
while some documents may need stronger interconnections to support richer question types (where extra cost is acceptable),
requiring full cross-document awareness at million-document scale would be prohibitively expensive, so smarter and more efficient ways of sharing knowledge between documents are necessary.

For more details on the process, refer to [methodology.md](methodology.md)

## Benchmark

The IndustryRAG Benchmark leaderboard will be released soon; because Onyx also offers an LLM and RAG-based product, we will exclude ourselves to avoid any conflict of interest.

To provide a submission for the leaderboard please reach out to joachim@onyx.app. Submissions are required to provide a method of verification.
- For open source applications, please provide a guide for reproducing results.
- For closed source applications, please provide a sandbox or URL where the questions can be sent for verification.

## Citation

If you use IndustryRAG Bench in your research, please cite our paper: TBD
