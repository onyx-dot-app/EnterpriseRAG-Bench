# Answer Generation

As discussed in the Evaluation section of the [methodology](methodology.md), the repository provides two retrieval approaches to help refine the gold question set.
By pooling results from structurally different retrievers, questions whose gold documents were incomplete or incorrect are more likely to be surfaced and corrected through the evaluation pipeline.

## Vector Search

The vector search approach is a straightforward embed-and-retrieve pipeline. All source documents are embedded using OpenAI's `text-embedding-3-large` model (3072 dimensions) and stored in a Qdrant collection.
Chunking is intentionally minimal: each document's title and content fields are concatenated into a single embedding. If it exceeds the maximum limit, it is simply split at the last possible complete word.
Most generated documents fall within the model's token limit, so there is no sliding window, overlap, or multi-chunk logic.

At query time, the question is embedded with the same model and a single cosine-similarity search retrieves the top 10 results (configurable). No re-ranking, query expansion, or filtering is applied.
The retrieved documents are then formatted into a prompt and passed to an LLM, which generates an answer grounded only in the provided context.

This approach serves as a fast, inexpensive baseline. It performs well on questions where the query and the relevant document share strong semantic overlap, but struggles with questions that are more complex.

## Agent-Based Retrieval

The agent-based approach replaces the fixed retrieval pipeline with an LLM agent that explores the corpus interatively in an agent-loop.
Rather than relying on pre-computed embeddings, the agent navigates the document directory structure directly — searching, reading, and reasoning about files in real time using shell commands.

The agent is given a shell execution tool with access to standard Unix utilities (`rg`, `grep`, `find`, `jq`, `cat`, `head`, `tail`, etc.) and a document selection tool for tracking which files it considers relevant to the answer.
Its working directory is set to the corpus root, so it operates relative to the source directory structure. The agent iteratively searches for documents, reads their contents, evaluates relevance, and refines its search strategy based on what it finds.
This loop continues until the agent produces a final answer or a per-question time limit is reached, at which point it is prompted to answer with whatever information it has gathered so far.

To manage context window constraints, a presentation layer sits between the raw command output and the LLM.
Output exceeding a line or character threshold is truncated, with the full result saved to a temporary file that the agent can navigate with subsequent commands.
Additional signals — such as repeat-command detection, zero-result counters with directory navigation hints, and null-field guidance for JSON inspection — help the agent avoid common dead ends.

This approach is significantly more expensive and slower than vector search, but it can handle question types which require variable numbers of documents to answer,
multi-hop or complex queries, or questions where the source directory structure contains critical information.
