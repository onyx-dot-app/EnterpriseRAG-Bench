Provide python cli commands to run the different steps
Release artifacts + link in quickstart
Paper link in quickstart
Readme shields: license(MIT), website(onyx), dataset(huggingface), leaderboard(onyx page?), arXiv






Notes and known limitations:
- Hard to avoid LLM artifacts, it likes to use things like 1234567 etc. for timestamps, ACME for company names, etc.
- agents.md files should mention things like user can specify what is a document, such as Slack being a thread, or metadata like titles for Fireflies is what the meeting title.
- Gmail is only for leaders, managers and sales, others are not indexed
- Note documents are flattened jsons for ease of use and to reduce parsing for downstream tasks. This may not exactly match nested structures for all data types but the LLM can approximate it reasonably well.
- Did not include people tool for the largest volume generation
- Slack in this case contains more meaningful docs
- At scale there will be some some number of docs that do not conform to the instructions set out for the source type, including some paths which do not make sense