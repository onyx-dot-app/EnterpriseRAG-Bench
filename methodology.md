# Data Generation Methodology

## Core challenges

The following are a list of requirements and challenges addressed by the EnterpriseRAG Bench approach.

1. Documents need to have consistent guiding principles to ensure they are realistic to the company / industry they are being generated for.
2. The generation process must allow for interdependencies between individual documents. For example code changes (Pull-Requests) are necessarily linked to Product Requirement Documents (PRDs).
3. The distribution of documents should be realistic to real world data. For example, there are typically orders of magnitude more discussion channel messages (Slack/MS Teams/Discord) as compared to polished product documentation.
4. The corpus must have a realistic level of noise. This includes things like misplaced documents, contradictory statements, ambiguous information, etc.
5. The creation of the data must allow for the generation of interesting questions for the dataset (not just simple backgenerating questions from single documents), the questions must be verifiable and answerable by the underlying data.
6. The dataset creation process should be flexible to industry (or vertical) specific use cases and able to handle different volumes of artificial data generation (at least to some maximum number of documents).
7. Being an LLM based generation process, it must work around the limitations and tendencies of LLMs.
8. The creation of large volumes of data should not be prohibitively expensive.

## High level process

At a high level, the process starts by generating structural, top-level information that guides downstream generation and keeps the dataset internally consistent.
It is human-in-the-loop, allowing users to provide key context such as the hypothetical company’s industry, available data sources, and active initiatives or projects.
Once this foundation is set, the system generates a core set of documents that are tightly informed by these details and by previously generated outputs.
It then defines generation scaffolds to keep document distributions aligned with expectations and prevent over-clustering around LLM-favored topics.
With those rails in place, the system produces the larger-volume document set needed for scale, using high-level context and less detail to improve cost efficiency.

Once the base document set is created, additional steps introduce noise into the dataset, including both random shuffling and LLM-driven shuffling.
The pipeline also adds a number of duplicate and misplaced documents, which are marked for downstream question generation.
This ensures some questions require retrieving correct information despite noisy context.

After the dataset is populated and noise has been introduced, the pipeline generates questions. It supports ten question types, each produced through a distinct generation flow.
Some flows are straightforward (for example, sampling a document and generating a question), while others are multi-step and require document filtering and verification.
Additional flows rely on LLM-driven topic discovery and pitfall identification.

For answer verification, the repository includes a script that processes an answers file containing question ids, answers, and supporting documents.
In most cases, it is impractical to determine whether a better answer exists in the corpus without exhaustively reviewing all documents.
To address this, the evaluation utility considers not only the gold answer but also the proposed candidate documents, and can update the gold answer when the evidence indicates it should change.

### Stage 1 - Generating the dataset

#### Step 1 - Generating the company overview

To help create a coherent dataset, we begin by generating a high-level overview of the company to guide all later steps. The user interacts with an LLM to cover topics including:
- Company name and 1 line description
- Mission and vision
- Company overview and what it does
- Product surface area and key features
- How their core product or technology works
- Interesting differentiations
- Business model and revenue streams
- Go to market strategy
- Size of the team, funding history, and key departments
- Positioning in the market and competitive landscape

The result of this is a natural language description of the company in an organized .md format. This document serves as the foundation for most of the downstream tasks.
It informs nearly all document generation, provides a rough guide for other scaffolding steps, and generally aligns the theme of the dataset.

#### Steps 2 through 5 - Generating more scaffolding

**Step 2** generates the high level initiatives for the company based on the company overview and user interactions. This step allows the user to provide more guidance on the high level contents for the dataset.
It is used by later steps to generate the employee directory, the source structure, more detailed project breakdowns, and provides context for the large volume document generation.

**Step 3** generates the employee directory based on the company overview and initiatives. It also allows the user to provide their input into the org structure and individuals.
It is used by later steps to generate source structure (for example, email inboxes all map to real people at the organization), and for generating project scaffolding information.

**Step 4** generates the source structure (things like Google Drive, Salesforce, Zoom, etc.) as well as the nested directory structures with them.
This step is also guided by the user to specify which sources they are interested in and the structure of the sources.
It takes into account the company overview and initiatives and can pull in relevant parts of the employee directory as needed.

**Step 5** generates agents.md files in different directories to guide the format and contents of the documents that exist within them.
These files which are created with user input allow the user to specify what kind of data they would like to be generated for the given sources.
For example, for GitHub in the released dataset, the documents all represent pull-requests (code change descriptions) along with their comments.
This approach of creating agents.md files that are pulled into document generation steps allows the user to specify in natural language exactly how different areas of the dataset should look.
This allows for as much or as little oversight from the user in creating the dataset.

#### Steps 6 through 8 - Generating core high fidelity documents

**Step 6** generates the scaffolding for projects at the company. Projects are smaller efforts which are described in the prompts as `tasks, projects, workstreams, campaigns, etc. and are not limited to technical deliverables`,
and these `efforts should reflect the full breadth of company operations (including things like technical work, go-to-market, customer-facing, operational, and internal functions)`.
The difference is that initiatives are higher level and generally too broad to guide a document generation process where the files are strongly aware of one another. Projects break them down into smaller sets of around 100 documents each.

The stages of the generation process are as follows:
1. Based on the company overview, initiatives, and directory structure, a list of projects is proposed and refined with the user input. These are grouped into major business/functional areas of the company.
2. For each of the projects individually, a separate flow is run to enrich them. This means generating a longer description as well as a list of documents to be created for this project.
This step is done also with context of the company and initiatives. For example, an engineering project might have requirement docs, internal meeting transcripts, discussion threads, and code changelogs.
Additionally, a set of LLM-usable tools are provided such as "glob", "tree" etc. to allow exploring the file directory and agents.md files.
This prevents the LLM from hallucinating for example GitHub issues for that source type when the agents.md explains clearly that the GitHub source type only contains pull-requests.
3. The projects are then further enriched with people information using the employee directory. The most relevant people are attached to the project and their roles for the project are outlined.

**Step 7** generates the actual project documents based on the scaffolding above. Each project file is aware of:
- Its own file name/path and description of what to cover
- The company overview
- The enriched project description with all of the files and descriptions
- The agents.md files in its path
- Access to a read tool to read other related project documents if additional details are needed outside of the overview

**Step 8** generates small clusters of related documents (typically 4–10) where every document in the cluster is fully visible to the model alongside the others.
Step 7 produces a much larger set per project (on the order of 100 documents) and only pulls in other project files when the model chooses to read them;
Step 8 always loads the full text of every document in the group into context. That full visibility supports the later generation of “completeness” type questions:
the topics overlap heavily across the cluster, and seeing everything at once keeps the set from drifting into hard contradictions.
The cluster is also anchored to a target question so the generation knows which facts must appear somewhere across the documents for a complete answer.

#### Step 9 - Generating high volume documents

High-volume document creation is split into scaffolding and generation. The main challenge is model drift: without very tight steering, the model converges on familiar themes and produces near-duplicate documents.
In a simple experiment we only gave the company overview and asked for 100 documents spanning different parts of the business. Each run used the same prompt and non-zero temperature, with no visibility into documents already produced.
At that modest scale we still saw tight clusters: the model judged that over 40% of documents had a very close sibling. The exact numbers depend on model and temperature, but the pattern holds across all the tested LLMs.

To address this, the system first generates JSON—based on the earlier agents.md files—with the desired document count for each source. It then creates a set of topics and estimated documents per topic that match an expected real-world spread.
The LLM is provided with:
- Company overview
- Key initiatives
- All source types
- The directory structure for the source type
- The agents.md contents for that source type

Topics are split into subtopics until each leaf represents at most 500 documents. During generation, the model sees the other files in the same leaf topic by name/path and is nudged so the documents complement one another rather than blindly overlapping.
Different leaves also cover different slices of the subject matter. Together, these guardrails prevent the runaway duplicate clustering seen in the naive setup.

It is also significantly more cost efficient compared to the high-fidelity documents. Documents in this flow only need access to global context about the company, a minimal amount of scaffolding for the topic and subtopics,
and the paths of other documents in the same leaf (capped at 500). This step is also per-source further reducing the amount of structural/directory context needed by the LLM.

Note: High-volume synthesis trades fidelity for throughput. The following limitations follow from prioritizing cost and turnaround.
- Personnel grounding: Tooling and context are deliberately restricted, so generated documents are not grounded in the organizational chart or role definitions. Fictional contributors are expected. This is benign for the released question set.
- Inter-document coherence: Cross-references are shallow and scoped to leaf topics, so global consistency is not enforced. Some divergence may mirror real archives; we have not quantified whether inconsistency is more or less frequent than in real corpuses.

### Stage 2 - Adding noise

> Note: The documents that have been shuffled or created by noise generation steps have an additional field called "dataset_noise_document".

#### Step 1 - Random shuffle

A specified percentage of the documents are randomly shuffled within their source type. For the provided dataset, this percentage is 5%.
To keep the documents compliant with the expected format of the source type, there is no cross source shuffling in this stage.
For example, a document for a ticketing system with metadata like "closed date", "assignee", etc. would not make any sense if shuffled into a source like Slack.
Documents are chosen using a random walk over the directory tree, so selection reflects structure rather than being skewed by how many files sit in each folder.
After a directory is picked, one document in that directory is randomly selected and moved to a new location.

#### Step 2 - LLM based shuffle

To better match real-world noise, we assume misfiled documents are biased toward local structure: adjacent directories, parent/child directories, or other structured but wrong placements, not a uniform draw over the corpus.
We use the same directory-based sampling as the step above but then rely on an LLM to propose a realistic misplaced destination. This LLM-based relocation applies to 3% of documents in the released dataset.
Previously shuffled documents are excluded, so this stage does not re-shuffle them. Cumulatively, 8% of documents in the provided dataset are affected by some shuffle operation.

The LLM is given the original path/name, the contents of the document, and the directory structure of the source and is required to output a different valid path within the existing structure which is reasonable but suboptimal for the document.

#### Step 3 - Miscellaneous type directories and files

The Stage 1 document generation emphasizes coherent, formal subjects aligned with the company inspired scaffolding. Real industry documents also include informal discussion, work-in-progress drafts, and ad hoc notes stored in poorly normalized locations.
Miscellaneous-type paths and files are introduced to approximate that layer of the document set. Some example misc directories in the dataset include `slack/memes`, `google_drive/shared_drives/go-to-market/misc-assets`, `github/hackathons`, etc.

The process begins with a human-in-the-loop LLM based generation of these directories. Given the existing directory structure, the LLM proposes a set of misc type directories and collaborates with the user to establish the final set.

Once the misc directories are created, a separate flow is run to populate the directories with misc type files. This flow is aware of:
- The company overview
- The agents.md files that overlap with the misc directories
- The misc type directories
- Other misc type files generated so far (this is to avoid the clustering problem mentioned before)

> Note: The document set assumes a low volume of these types of misc type files. It is not significant in the total volume of the dataset.
> They are created not to dramatically shift the distribution of the dataset but rather to later create questions based on these misc documents which present some unique challenges in retrieving.
> To create a very significant volume of misc type documents, a similar scaffolding approach as Stage 1 Step 9 would be recommended.

#### Step 4 - Near duplicates

A common noise pattern is disagreement between closely related documents. Most often, later documents update earlier ones (for example, pricing changes after a follow-up sales conversation).
In other cases, the corpus encodes trust levels, with deprecated documents or ad-hoc conversations considered less reliable than polished documentation.

To simulate these cases, we sample and create near duplicates of the selected docs. The document sampling works identically to the above steps. From there the LLM selects a new path and provides an updated name to the document.
This step differs from prior noise generation steps in that documents may be placed outside their original source type (so a Slack conversation might contain an update on a Salesforce opportunity).
A new highly related document is then created at the new location with updates to certain key facts from the original. The generation of this updated document has access to:
- The original file path and new file path
- The original file contents
- The agents.md file contents along the new file path

### Stage 3 - Generating the question set

The question and gold results generation is split into 10 steps, one per question type. Each has a unique process and prompts.

For all question types the following fields are generated:

| Field Name | Description | How it's used |
|------------|-------------|---------------|
| question_id | Unique question identifier prefixed with `qst_` | Used to map the answer file rows to the correct questions during evaluation |
| question_type | One of the 10 question types | Used to select a subset of questions and provide a more detailed per type breakdown in evaluation |
| source_types | List of source types matching the directory structure from Stage 1 Step 4 | Provided in case the user wishes to do source based analysis, not used in eval |
| question | Text of the question to run for eval | Provided for the user to run their evals |
| expected_doc_ids | List of unique identifiers for the gold documents, prefixed with `dsid_` | Used to map the answer file rows to the correct questions during evaluation |
| gold_answer | The expected answer | Provided for the eval process to output a binary correct vs not categorization |
| answer_facts | Atomic statements that are easily verifiable | Provided for the eval process to calculate a "completeness" score for the user provided candidate answer |

#### Type 1: Basic Questions

Basic questions are generated by sampling a random document and then prompting the LLM to generate a question for it. Some of the guiding statements for it are:
- Avoid long and exact phrase matches which would make retrieval trivial
- Avoid complex multi-part questions
- Use varied language so that not every question is a "What is" type question.

Additionally some examples are provided for what good and bad questions look like to ensure the questions loosely fall in the same distribution in terms of length and detail.

A separate flow validates that the question is conformant to the requirements and a gold answer is generated.

Finally based on the question and answer, a fact extraction step is run to generate the `answer_facts` list.

#### Type 2: Semantic Questions

Semantic questions are generated in a very similar way to basic questions but with different guidance. The steps of generating a question, validating / gold answer generation, and extracting facts are the same as the basic questions.
The guidance which is different include:
- Avoid keyword matches where possible
- Limit qualifiers and scoping details
- The question should be a "challenging, loose match, semantic type query"

The examples provided to the LLM on good and bad questions of this type are also more difficult and aligned with the guidance above.

#### Type 3: Intra-Document Reasoning

These questions are intended to test the system for the ability to relate information from different parts of a single document. It addresses both a recall and a reasoning challenge.
Naive chunking and embedding approaches tend to be prone to mistakes of this category.
On the other extreme, expanding every fetched document in full brings the risk of putting significant strain on the LLM by flooding the context window with less relevant text.
This also screens for hallucinations where one section seems to contain the answer to a question but a different section may disqualify the doc entirely.

The generation process for this type of question also begins by sampling a doc and generating a question. During the sampling, a minimum length parameter is used to ensure it's possible to generate questions that require long hops within the document.
Guidance is provided to the LLM on how to generate questions that relate different parts of the document. After, a validation flow is then run to ensure that the question is in fact not answerable using any single consecutive part of the document.

#### Type 4: Project Related

Project related docs give the LLM the ability to read multiple documents within a project (generated in Stage 1 Step 7). These documents are fairly related and this allows for more complex multi-doc questions.
The LLM is given the project overview and a list of all the documents from the project which it can read.
It is also given a set of instructions for how to create interesting questions so it can continue to read documents until it reaches a set which allows it to create a good question.
Some extracts from the prompt are provided below for clarity:
- "Multi-document: queries where the answer takes parts from multiple documents to build a cohere picture of the answer."
- "Cross-cutting: items mentioned incidentally across multiple documents but are never the primary focus of any single document."
- "Contradictions: conflicting information and requiring a good answer to mention the contraditions and reconciling them."
- "Causal chain: tracing a cause and effect relationship through multiple documents to create a cohere story."

During the reading process, all of the documents read are tracked for the next step. After the question is generated, it is passed along with all of the documents read to find the minimal set of documents necessary to correctly answer the question.
That filtered set becomes the expected gold documents.

> Note: Because many of these are broader more complex questions, they have a relatively higher chance of having other generated documents not in the original project also be valid or add some information of value to the answer.

#### Type 5: Constrained

This type of question is explained directly to the LLM in the prompt, the following is an exerpt:
> A constrained query is a query that contains qualifiers (constraints) which narrow the correct answer to only a small subset of documents, \
> even though many other documents in the corpus are superficially relevant and share overlapping keywords, entities, or topics. \
> The qualifiers act as filters: each one eliminates some documents that would otherwise seem relevant.
>
> This is valuable for RAG evaluation because naive retrieval systems will return many partially-matching documents, but only the documents satisfying ALL constraints together contain the correct answer. \
> A good constrained query tests whether a system can distinguish between surface-level relevance and true relevance under specific conditions.

The first half of the process relies on the LLM exploring the corpus to identify promising questions of this type and related documents. The process at a high level is to:
1. Use available tools to explore the directory structure and find clusters of topically related documents. The tools available are "glob", "grep", "ls", and "read".
The "tree" tool is omitted as the directory structure is provided directly in the prompt.
2. The LLM finds other similar docs in the topic cluster and identifies the axies in which the documents differ.
3. The LLM creates a question and then identifies the "gold documents" and "distractor documents".
4. It calls the finish tool to trigger the second stage.

Aside from the directory structure, this also has access to all the previously read document paths from other constrained question generations steps to prevent the LLM from over clustering in certain topic areas.

The second phase turns the gathered context into a gold answer plus a set of facts. Unlike previous question types, this one generates the answer and facts jointly rather than extracting facts from a separately produced answer.
It also leverages distractor documents to craft constraints that prevent hallucinations. For example:
"The answer must not claim the Postgres database is the in-cluster StatefulSet (or advise kubectl exec into postgres-0) since the scenario specifies externally managed Postgres."

#### Type 6: Conflicting

These questions test scenarios where information conflicts and the model must reconcile it through reasoning. The question type targets cases where one document supercedes another, typically when a newer document invalidates facts from an older one.
This also creates a retrieval challenge: if the retriever returns only the superseded (outdated) document, the response will likely be incorrect. The docs used are generated in pairs from (Stage 2 Step 4).
Like the previous question type, the gold answer and factual elements are generated simultaneously, and the LLM is prompted to provide facts designed to catch hallucinations.

#### Type 7: Completeness

Completeness questions test whether a RAG system can exhaustively retrieve all documents needed to answer a question, not just a relevant subset.
A partially retrieval is insufficient for this question type, if even one of the required document is missing, aggregated counts will be wrong, lists will be incomplete, and comparisons will be skewed.
This makes completeness questions a direct test of recall.

These questions are built from the question-document sets produced in Stage 1, Step 8. During generation, each cluster is designed to avoid direct contradictions and to spread answer-critical facts across multiple documents.
Because the question already exists, this step focuses on using an LLM to remove unnecessary documents and generate the final answer.
Although these documents were originally created under the assumption that each one would be needed, some prove unnecessary in practice. Any query that requires fewer than two documents after filtering is discarded.
Fact extraction here also works by breaking the gold answer into individually verifiable claims.

#### Type 8: Miscellaneous

Miscellaneous questions target the informal, off-topic, or loosely organized documents introduced during Stage 2 Step 3 — files in directories like `slack/memes`, `google_drive/.../misc-assets`, or `github/hackathons`.
These documents sit outside the main scaffolding-driven generation and present a retrieval challenge: they are topically peripheral and stored in less predictable locations, so systems tuned to the corpus's dominant themes may overlook them.

The generation flow is straightforward. Each miscellaneous document tracked in the generation cache is sampled and a question is generated from it using the same prompt guidance as basic questions (Type 1).
The question is then validated against the source document to produce a gold answer, and answer facts are extracted. Each question maps to a single document.

#### Type 9: High Level

High-level questions are answerable from the company overview and initiatives — the top-level scaffolding documents — but should not be answerable from any single document in the corpus.
They test whether a system can synthesize broad organizational knowledge that is spread across many documents rather than concentrated in one place.

The generation process has three stages:
1. **Candidate generation** — The LLM is given the company overview and initiatives and asked to produce a batch of candidate queries. Guidance steers the questions toward patterns and cross-cutting themes rather than point lookups, and requires varied phrasing and topic spread.
2. **Validation** — Each candidate is checked by an LLM agent equipped with glob, grep, ls, and read tools over the source directory. The agent attempts to find a single document that directly answers the query.
If it can, the query is rejected as too specific. Only queries that would require aggregating information across multiple documents pass validation.
3. **Answer and fact generation** — For each validated query, a gold answer is produced from the company overview and initiatives, and answer facts are extracted.

Unlike most other question types, high-level questions carry no expected document IDs or source types, since the answer derives from organizational context distributed across the corpus rather than from a specific set of retrievable files.

> This question type is deliberately designed to be unanswerable without reviewing a large portion of the corpus, so there isn’t a single “gold” set of documents to cite.
> The answers depend on cross-cutting organizational context, and a RAG system may reach the right conclusion by pulling evidence from many different places.
> Additionally there is no strict guarantee that every synthesized question is fully answerable from the document set; the assumption is that with enough documents/questions overall, the relevant context will typically exist somewhere in the corpus.

#### Type 10: Unanswerable

Unanswerable questions test whether a RAG system can recognize when the corpus does not contain the information needed to answer a query, rather than hallucinating a response from superficially related documents.

An LLM agent equipped with glob, grep, ls, and read tools explores the source directory to find a cluster of topically related documents.
After reading several documents in the cluster, it identifies the dimensions along which they differ and crafts a natural-sounding query that is related to the cluster's topic but not answerable from the documents.
The query is designed so that a system relying on surface-level keyword or topic matching would retrieve plausible-looking documents, but any answer derived from them would be incorrect or hallucinated.

To prevent the LLM from revisiting the same areas of the corpus, previously explored document paths are tracked in a generation cache and provided in each subsequent generation run.
The gold answer and facts are predefined rather than generated: the expected answer states that the query is not answerable from the available documents,
and the single evaluation fact checks that the response acknowledges this rather than presenting fabricated information.

## Evaluation

It is important to note that in retrieval benchmarks, a "gold" document is understood as one that was judged relevant under a specific annotation protocol — it is not a guarantee that the gold set are the absolute best document in the corpus.
This is true of all large scale datasets however many older datasets have gone through many rounds of revisions as better sources and answers are provided for certain queries.
Standard ways to address this challenge include:
1. Pooling and combining results from multiple retrievers
2. Human adjudication
3. Trimming problematic queries
4. Periodically refreshing the labels as new information becomes available.

This code base provides three out of the box retriever solutions to help address this problem:
- A BM25 keyword search based approach in `index_document_bm25.py` and `bm25_retrieval.py`
- A vector search based approach in `index_document_vectors.py` and `vector_retrieval.py`
- An LLM agent based approach where an LLM is equipped with bash commands to traverse the documents and attempt to find the answers (see `agent_retrieval.py`)

> Note: read more about these approaches in [src/scripts/answer_generation/README.md](src/scripts/answer_generation/README.md) 

The released dataset used these approaches to refine the questions however there are likely many additional corrections that can be made.

### Correction Utilities

It is much more feasible to verify that new candidate document(s) provided are better than the gold document than to confirm exhaustively that there is no other better match.
We provide built-in correction mechanisms in the evaluation steps. The corrections work as follows:

1. During evaluation, the user provides candidate answers along with the documents their system retrieved. The evaluation process considers both the original gold documents and any new candidate documents submitted by the user.
2. Each document (gold and candidate) is independently evaluated by three separate LLM judges. Each judge classifies every document as "required", "valid", or "invalid" for the given question. "Required" means the document is essential to answering the query, "valid" means it is relevant but not necessary (e.g. a near-duplicate or corroborating source), and "invalid" means it does not help answer the query. An ordinal majority vote across the three runs determines the final classification, with gold-biased tie-breaking: gold documents are kept as "required" unless a majority votes them "invalid", while candidate documents need a strict majority to be promoted. If any of the three runs returns a result fully consistent with the original gold set, the evaluation exits early.
3. If the majority vote produces a required document set that differs from the original gold set — for example, a gold document is voted invalid or a candidate document is voted required — the gold set is updated.
Gold documents that were voted invalid are removed and candidate documents that were voted required are added. Documents classified as "valid" are recorded but do not enter the gold set. Note that in practice, it is much more common for gold documents to be confirmed than for the gold set to change.
4. When the document set changes, the gold answer and answer facts are regenerated using the updated set. The regeneration process preserves anti-hallucination facts from the original answer fact set 
(negative statements or boundary conditions designed to catch specific hallucinations) and combines them with new facts extracted from the regenerated answer.
In rare cases where answer regeneration fails, the original gold answer is kept but the document set is still updated.
5. Corrected questions are written to an updated questions file and flagged as corrected in the evaluation results, allowing downstream consumers to distinguish between original and revised entries.

### Metrics Based Evaluation

The metrics-based evaluation scores a single system's answers against the gold question set. The evaluation produces four metrics per question:

| Metric | Description |
|--------|-------------|
| **Correctness** | A holistic LLM-based judgment of whether the candidate answer is aligned with the gold answer. The evaluation is lenient toward stylistic differences, additional context, and extra detail, but requires that the core aspects of the question are addressed and do not conflict with the gold answer. Specific quantities mentioned in both answers must match. |
| **Completeness** | The percentage of answer facts that the candidate answer supports. Each fact from the gold `answer_facts` list is independently validated by an LLM judge that checks whether the candidate answer contains or implies that fact. The score is simply the fraction of facts validated. |
| **Document Recall** | The percentage of expected gold documents that appear in the candidate's retrieved document set. This is only computed for questions that have expected documents. |
| **Invalid Extra Documents** | The count of documents in the candidate's retrieved set that are neither in the expected gold set nor classified as "valid" (relevant but not required) by the evaluation. Like recall, this is only computed for questions with expected documents. |

Prior to running the evaluations, the answer is stripped of citations to avoid biasing the LLM judge.  The evaluation also applies the document correction flow described above:
if the candidate provides documents that differ from the gold set, the three-judge consensus determines whether the gold set should be updated before scoring.
Similarly, if the gold set of documents change, then the answer and facts will also be updated and the scoring is done on the revised ground truth.

Correctness and completeness are evaluated independently — the correctness judge has no visibility into the answer facts, and each fact is validated on its own so that no single judgment leaks into another.

### Comparative Evaluation

The comparative evaluation scores two RAG systems head-to-head on the same question set. It takes two answer files (one per system) and produces both a per-question preference and the same per-system metrics
(completeness, document recall, invalid extra documents) described above.

For each question the flow is:

1. Citations are stripped from both answers. The union of both systems' retrieved documents is passed through the same three-judge document correction process.
If the gold set changes, the answer and facts are regenerated as before, and both systems are scored against the revised ground truth.
2. The retrieved documents are split into three groups: documents found by both systems, documents unique to system 1, and documents unique to system 2.
To reduce positional bias, the two systems are randomly swapped before being presented to the judge — the preference is mapped back to the original ordering afterward.
3. Three evaluations run in parallel: a head-to-head answer comparison (using three-judge consensus) and independent scoring for each system's answer set.
The head-to-head judge sees the query, both answers, and all three document groups. It returns a preferred system ("1" or "2") and whether the two answers are effectively equivalent.
Majority voting across the three runs determines the final preference and equivalence classification.
4. Each system's answer is independently scored for completeness (fact validation percentage), document recall, and invalid extra documents — identical to the metrics-based evaluation.

## Known Limitations

The following are known limitations of the dataset and generation process.

- **Long-tail LLM errors at scale.** Even when the per-document error rate is low, generating thousands to millions of documents means rare failure modes will surface.
For example, the initial dataset contained 7 documents whose file names included control characters; these were caught and removed manually.
- **Synthetic randomness artifacts.** LLMs fall back on recognizable patterns when asked to produce arbitrary values. Unix timestamps that should look like `1774728005` often come out as `123456789`,
and company names tend to include "ACME" or similar defaults even when the prompt requests realistic alternatives.
- **Unrealistically on-topic conversations.** LLMs struggle to reproduce the noise and misunderstanding present in real discussions. 
In a realistic Slack thread, participants frequently go off-topic, misunderstand one another, or introduce unrelated tangents, LLM-generated conversations rarely do this.
The result is a corpus with less incidental noise than a real one, which affects retrieval difficulty in both directions: there are fewer easy-to-discard irrelevant documents, but also less realistic clutter for a system to filter through.
- **Flat JSON representation.** All documents are stored as flattened JSON to standardize processing and export. This does not capture the nested structures that some real data types would naturally have.
- **Document structure drift.** Despite guidance from `agents.md` files, the LLM does not always follow the specified document layout.
At large volumes a non-trivial share of documents will deviate from the intended format. Most remain reasonable, but there is no strict schema enforcement since the process is natural-language driven.
- **Invalid file paths.** The same scale-related drift applies to paths. Some documents end up in locations that break the expected hierarchy — for example, Slack messages placed directly under the top-level Slack directory rather than inside a channel.
- **Limited cross-document context in high-volume generation.** To keep cost and generation time manageable, the high-volume flow restricts the context available to each document.
Notably, it has no access to the employee directory, so many documents reference fictional people not grounded in the organization chart.
- **Single-company representativeness.** The dataset approximates one realistic company, but companies vary significantly across stages, industries, and operational styles. The dataset will be more representative of some organizations than others.
- **Context saturation at extreme scale.** Several generation steps feed previously generated artifacts back into the prompt — for example, each new project is created with visibility into all existing projects. At large enough scale the accumulated context overwhelms the LLM, causing it to ignore instructions and degrade the quality of the output. The current methodology has not been stress-tested beyond the scale of the released dataset.

## Future Work

The following are possible extensions to the question set that we leave for future exploration.

- **High-volume aggregation.** Questions whose correct answer requires aggregating information across a large fraction of the corpus — for example, a question that can only be answered by consulting 5% or more of all documents.
These would stress-test a system's ability to perform broad, recall-heavy retrieval rather than pinpoint lookups.
- **Recency-aware retrieval.** Questions that ask for the latest document matching a loosely specified criteria, where the criteria alone does not narrow the result to a small set. These test whether a system can combine topical relevance with temporal ordering.
- **People-centric questions.** Questions about specific individuals, their responsibilities, project involvement, expertise, relationships, and contributions —
where the relevant information is scattered across meeting notes, discussion threads, code reviews, org charts, and other sources.
People are referenced inconsistently (full names, first names, handles, titles) and rarely the primary subject of any single document, making retrieval particularly challenging.
Answering well requires the system to discover and stitch together incidental mentions across many documents rather than retrieving a few directly relevant ones.
- **True multi-hop reasoning.** Questions that require a specific chain of discovery across documents, where the answer to one retrieval step reveals what to search for next.
These go beyond the existing multi-document questions by requiring sequential reasoning rather than parallel aggregation.
