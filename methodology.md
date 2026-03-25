# Data Generation Methodology

## Core challenges

The following are a list of requirements and challenges addressed by the IndustryRAG Bench approach.

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

Note: there are some acknowledged drawbacks of the high volume generation approach which would be in conflict with cost savings and time needed per document.
- To save cost, this step is given minimal flexibility/tools that the LLM can call. The documents are therefore not aware of the people in the org or information about their roles.
Many of the documents will have made up authors, commenters, etc. which do not exist in the employee directory. Note that for the questions provided with the dataset, this is not an issue.
- Since documents are only aware of each other at a surface level and only within leaf topics, there is no guarantee that contents within the files do not contradict each other.
While some amount of this is desirable, it is unclear if this happens more frequently than in real world corpuses.

### Stage 2 - Adding noise

> Note: The documents that have been shuffled or created by noise generation steps have an additional field called "dataset_noise_document" which has a value of true.

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

Basic questions are generated by sampling a random document and then prompting the LLM to generate a query for it. Some of the guiding statements for it are:
- Avoid long and exact phrase matches which would make retrieval trivial
- Avoid complex multi-part questions
- Use varied language so that not every question is a "What is" type question.

Additionally some examples are provided for what good and bad queries look like to ensure the questions loosely fall in the same distribution in terms of length and detail.

A separate flow validates that the query is conformant to the requirements and a gold answer is generated.

Finally based on the query and answer, a fact extraction step is run to generate the `answer_facts` list.

#### Type 2: Semantic Questions

Semantic questions are generated in a very similar way to basic questions but with different guidance. The steps of generating a question, validating / gold answer generation, and extracting facts are the same as Type 1.
The guidance which is different include:
- Avoid keyword matches where possible
- Limit qualifiers and scoping details
- 