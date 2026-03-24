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

To help create a cohere dataset, we begin by generating high level overview about the company to guide all later steps. The user interacts with an LLM to cover topics including:
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

Step 2 generates the high level initiatives for the company based on the company overview and user interactions. This step allows the user to provide more guidance on the high level contents for the dataset.
It is used by later steps to generate the employee directory, the source structure, more detailed project breakdowns, and provides context for the large volume document generation.

Step 3 generates the employee directory based on the company overview and initiatives. It also allows the user to provide their input into the org structure and inviduals.
It is used by later steps to generate source structure (for example, emails inboxes all map to real people at the organization), and for generating project scaffolding information.

Step 4 generates the source structure (things like Google Drive, Salesforce, Zoom, etc.) as well as the nested directory structures with them.
This step is also guided by the user to specify which sources they are interested in and the structure of the sources.
It takes into account the company overview and initiatives and can pull in relevant parts of the employee directory as needed.

Step 5 generates agents.md files in different directories to guide the format and contents of the documents that exist within them.
These files which are created with user input allow the user to specify what kind of data they would like to be generated for the given sources.
For example, for GitHub in the released dataset, the documents all represent pull-requests (code change descriptions) along with their comments.
This approach of creating agents.md file which are pulled into document generation steps allow the user to specify in natural language exactly how different areas of the dataset should look like.
This allows for as much or as little oversight from the user in creating the dataset.

#### Steps 6 through 8 - Generating core high fidelity documents

Step 6 generates the scaffolding for projects at the company. Projects are smaller efforts which are described in the prompts as `tasks, projects, workstreams, campaigns, etc. and are not limited to technical deliverables`,
and these `efforts should reflect the full breadth of company operations (including things like technical work, go-to-market, customer-facing, operational, and internal functions)`.
The difference is that initiatives are higher level and generally too broad to guide a document generation process where the files are strongly aware of one another. Projects break them down into smaller sets of around 100 documents each.

The stages of generating the process are as follows:
1. Based on the company overview, initiatives, and directory structure, a list of projects is proposed and refined with the user input. These are grouped into major business/functional areas of the company.
2. For each of the projects individually, a separate flow is run to enrich them. This means generating a longer description as well as a list of documents to be created for this project.
This step is done also with context of the company and initiatives. For example, an engineering project might have requirement docs, internal meeting transcripts, discussion threads, and code changelogs.
Additionally, a set of LLM useable tools are provided such as "glob", "tree" etc. to allow exploring the file directory and agents.md files.
This prevents the LLM from hallucinating for example GitHub issues for that source type when the agents.md explains clearly that the GitHub source type only contains pull-requests.
3. The projects are then further enriched with people information using the employee directory. The most relevant people are attached to the project and their roles for the project are outlined.

Step 7 generates the actual project documents based on the scaffolding above. Each project file is aware of:
- It's own file name/path and description of what to cover
- The company overview
- The enriched project description with all of the files and descriptions
- The agent.md files in its path
- Access to a read tool to read other related project documents if additional details are needed outside of the overview

Step 8 generates documents 