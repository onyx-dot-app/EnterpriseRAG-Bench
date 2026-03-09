Directory:
sources/google_drive

Target number of files:
25000

File name format:
File names should be short and descriptive with words connected with dashes (e.g. mid-term-kpi-planning-wip.json).

Content rules:
- Google Drive is Redwood Inference’s working-area for team-specific documents and in-progress thinking.
- This directory should contain a mix of formal and informal documents, with informal/working docs being the majority.
- Most documents are doc/docx type files with a large majority of just text without too much formatting.
- Common doc types include:
  - Team notes and internal memos (weekly updates, project notes, planning)
  - Brainstorms, outlines, and rough drafts of specs/PRDs
  - User scratchpads and personal notes (especially under users/)
  - Slides/decks converted to text (speaker notes, slide titles, bullets)
  - Spreadsheets represented as tables and short interpretations (metrics, capacity plans, headcount, budgets)
  - Checklists, TODO lists, meeting prep docs, retro notes (less polished than Confluence)
  - Customer-facing drafts (one-pagers, proposals) and internal review copies
- Informal documents may include:
  - Choppy phrases, shorthand, incomplete sentences
  - “Notes to self” sections
  - Unresolved questions and brainstorming fragments
  - Mixed formatting and inconsistent structure
- Polished documents do exist (e.g., finalized plans, exec updates, launch briefs), but they are not the majority.
- Documents should often reflect their context:
  - Which team or function created it (eng subteam, product area, CS, finance/legal, people ops, GTM)
  - Links/references to Confluence pages, Jira/Linear tickets, GitHub PRs, Slack threads, and external docs
- It’s acceptable for Drive docs to overlap in content with Confluence, but Drive tends to show earlier drafts and more iterative collaboration.
- It is very very rare for there to be files under the "users" directory, it is almost always in a shared drive.

Metadata rules:
- Every document must include:
  - title
  - owner: a real Redwood employee name
  - drive_area: shared_drives | users
  - path: a plausible path within Google Drive reflecting the directory tree (e.g., shared_drives/engineering/serving-runtime/…)
  - doc_type: doc | sheet | slides | pdf
  - created_at (YYYY-MM-DD)
  - last_modified (YYYY-MM-DD)
- Optional metadata:
  - collaborators: list of names
  - team: e.g., eng-serving-runtime, eng-sre, product-hosted-api, customer-success
  - status: draft | in_review | final
  - tags: 0–10 short tags
  - linked_artifacts: list of URLs/ids (Confluence page ids, Jira keys, Linear ids, GitHub PR links)
- Dates should be plausible over multiple years; last_modified should be >= created_at.
