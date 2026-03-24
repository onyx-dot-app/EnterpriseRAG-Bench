Provide python cli commands to run the different steps
Agents.md explanations at the top of the script before starting
Explain project enrichment, what is going on?
Project phases explain more in detail, not super clear
Release artifacts + link in quickstart
Paper link in quickstart
Readme shields: license(MIT), website(onyx), dataset(huggingface), leaderboard(onyx page?), arXiv






Notes and known limitations:
- Hard to avoid LLM artifacts, it likes to use things like 1234567 etc. for timestamps, ACME for company names, etc.
- agents.md files should mention things like user can specify what is a document, such as Slack being a thread, or metadata like titles for Fireflies is what the meeting title.
- Gmail is only for leaders, managers and sales, others are not indexed
- Note documents are flattened jsons for ease of use and to reduce parsing for downstream tasks. This may not exactly match nested structures for all data types but the LLM can approximate it reasonably well.
- Did not include people tool for the largest volume generation
- The documents are too on-topic, it's very difficult to have it create realistic conversations with noise, people misunderstanding the topic, etc.
- It's not very good at small talk, need to provide significant rails to prevent all smalltalk being the same stuff, hard to get this one realistic
- Slack in this case contains more meaningful docs
- At scale there will be some some number of docs that do not conform to the instructions set out for the source type, including some paths which do not make sense
- Some places there's a limit to model output (like employee directory all at once), and some places that don't scale well
- At scales some docs will fail, checks can catch many of the issues but some will still be conformant to json but just be empty etc.


Possible directions for justifying the dataset validity:
- Check lengths of docs
- Check word frequency curves
- Check clustering
- Check vector directions
- Average maybe 70 docs out of 100 being strong overlap with at least 1 other (very very close topically), average cluster size of 5 ish

## 1) Lexical / surface statistics (fast, very diagnostic)
These catch a lot of “looks real but isn’t” issues.

- **Token/character distributions**
  - Avg chars per sentence, sentences per doc, punctuation rates, capitalization patterns.
  - Ratio of numbers, symbols, bullet characters (`-`, `•`), headings (`#`, `:`), code fences, table pipes (`|`).
- **Zipf / word frequency curve**
  - Compare top‑N unigram frequency distribution; synthetic text often over/under-uses “glue” words and underproduces rare domain terms.
- **Type-token ratio / vocabulary growth**
  - Synthetic corpora often have *too much* lexical variety (or weirdly repetitive phrases).
- **Duplication / near-duplication**
  - Measure exact duplicates + near-duplicates (MinHash / simhash). Synthetic sets sometimes accidentally template-repeat.
- **Boilerplate & template prevalence**
  - If your real corpus has recurring headers/footers, confidentiality notices, ticket signatures, etc., check if those appear with similar frequency and variability.

**How to compare:** compute feature vectors per doc and compare distributions via **KL/JS divergence**, **Wasserstein distance**, or two-sample tests (KS test for 1D features).

---

## 2) Structural + formatting realism (company docs are “shaped”)
Embeddings can miss layout-ish signals.

- **Section structure**
  - Frequency and ordering of sections like *Background / Proposal / Decision / Alternatives / Risks / Rollout / Owners*.
  - Heading depth distribution (H1/H2/H3), average section length.
- **List/table density**
  - Number of bullet lists, list item lengths, table row/column counts, table density per doc type.
- **Inline artifacts**
  - Links, issue IDs (Jira-style), PR references, Slack mentions, file paths, stack traces, error codes.
- **Doc-type mixture**
  - Real corpora are a mixture: specs, RFCs, runbooks, postmortems, meeting notes, tickets, FAQs, onboarding, etc.
  - Synthetic data often collapses into one “generic doc” style.

A good move: **train a lightweight “doc-type classifier” on real** (even weak labels via heuristics), then see if synthetic doc types land in similar proportions and confidence profiles.

---

## 3) Domain/entity distribution checks (semantic without “truth” requirements)
You can validate whether the synthetic set “talks about the right things” without checking factual correctness.

- **Named entity patterns**
  - People names vs teams vs projects vs services vs vendors.
  - Distribution of **entity categories** and **co-occurrence graph** properties.
- **Acronym realism**
  - Acronym density and expansion patterns (“XYZ (Xylophone Yield Zone)”).
  - Real companies have a recognizable acronym ecosystem; synthetic can be too “clean” or too random.
- **Terminology overlap**
  - Domain lexicon coverage (top n‑grams from real set) vs synthetic.
  - Watch for “LLM-isms”: overly general product/strategy language and vague nouns (“stakeholders”, “leverage”, “synergy”) at unnatural rates.

---

## 4) Embedding distribution tests (go beyond UMAP plots)
You already mentioned “vector directions and clustering.” A few more *quantitative* variants:

- **Global distribution similarity**
  - Compare means/covariances of embedding vectors, or use **MMD (Maximum Mean Discrepancy)** between real vs synthetic embedding sets.
- **Neighborhood realism**
  - For each synthetic doc, look at kNN distances to real docs: are synthetic docs *too close* (memorization) or *too far* (out-of-domain)?
  - Compare kNN distance distributions: \(d_{k}(x)\) for real and synthetic.
- **Topic coverage**
  - Topic modeling (BERTopic / LDA on embeddings) and compare:
    - number of topics,
    - topic entropy (mixture diversity),
    - topic-word coherence proxies.

---

## 5) Retrieval behavior parity (very practical for search products)
If your goal is “synthetic docs are a good stand-in,” test it by *using them*:

- **Query→doc retrieval similarity**
  - Take a query set (real internal queries or a curated set), run retrieval on:
    1) real corpus
    2) synthetic corpus
  - Compare:
    - score distributions,
    - diversity of top-k,
    - “self-consistency” (do top docs share terms/entities expected by the query?).
- **Rank stability under perturbations**
  - Paraphrase queries or add typos; synthetic corpora sometimes behave oddly because phrasing is too uniform.

If you have labeled relevance, even a small amount, measure nDCG/MRR deltas.

---

## 6) Factual / logical consistency (without requiring true facts)
Even if the synthetic data is intentionally fake, it should be *internally consistent*.

- **Coreference consistency**
  - Does “it/this service” refer coherently across paragraphs?
- **Temporal consistency**
  - Dates, quarters, release sequences: are timelines plausible and consistent within a doc?
- **Numerical sanity**
  - Units, percentages, budgets: do numbers obey basic constraints (no 110% market share, etc.)?
- **Cross-doc consistency (optional)**
  - If synthetic dataset includes “projects,” check whether the same project appears with consistent naming/owners across docs.

---

## 7) “Synthetic tells” / detectability
If you’re worried about generated text being too obviously generated:

- **Perplexity / burstiness**
  - Use a reference LM to compute perplexity; synthetic corpora often have lower perplexity and lower variance (“smoothness”).
- **Repetitive phrasing signatures**
  - Count repeated 4–8 gram phrases across many docs.
- **Classifier detectability**
  - Train a simple discriminator (logistic regression on n-grams / shallow transformer) to classify real vs synthetic.
  - If it gets very high AUC, you’ve found systematic differences worth fixing. (This is basically a “Turing test” but quantified.)

---

## 8) Privacy / memorization risk (if generated from/near real data)
Important if the generator had access to real company docs.

- **Nearest-neighbor overlap**
  - For each synthetic doc, find nearest real docs; flag very high similarity.
- **Canary strings**
  - If you inserted canaries in training, check if they appear.
- **Exact substring matching**
  - Look for long exact matches against real corpus (hash shingles).

This is separate from “validity,” but often the most important *risk* check.

---

# A practical workflow (minimal but effective)
1) **Define doc types** (even heuristically) and compare mixture + structure stats by type.  
2) Compute a **feature suite** per doc: length, headings, list density, numeric density, entity counts, link counts, embedding norms, etc.  
3) Compare **distribution distances** (JS/Wasserstein) and run a **real-vs-synth discriminator** to discover what’s off.  
4) Run **retrieval parity tests** with a fixed query set.

---

## Quick question (to tailor this)
What is “validity” for you here:  
1) *statistical similarity* to real docs,  
2) *retrieval/search behavior parity* (most relevant for Onyx-style evaluation),  
3) *privacy-safe but realistic*, or  
4) *downstream task performance* (e.g., QA, summarization)?

If you tell me which one matters most, I can suggest a tighter metric set + thresholds and a minimal implementation plan.