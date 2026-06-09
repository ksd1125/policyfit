# Bizinfo Policy Dataset Collection Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a separate project that collects two years of Bizinfo notices in four small-business-adjacent categories, downloads their source materials, and converts the materials into markdown for later normalization analysis.

**Architecture:** The project is split into metadata collection, source download, markdown conversion, and analysis outputs. Raw API responses, raw source files, converted markdown, and human-readable summaries are stored separately so collection failures and source provenance remain traceable.

**Tech Stack:** PowerShell, Node.js, local filesystem project structure, Bizinfo API, HTML/PDF/HWP-to-Markdown conversion tooling to be selected during implementation.

---

### Task 1: Project Skeleton And Working Notes

**Files:**
- Create: `projects/bizinfo-policy-dataset/README.md`
- Create: `projects/bizinfo-policy-dataset/wiki/log.md`
- Create: `projects/bizinfo-policy-dataset/outputs/index.html`

- [ ] **Step 1: Create the project README**

Add a README that explains the project purpose, data range, folder structure, and the rule that this project is for collection and analysis first, not end-user answer generation.

- [ ] **Step 2: Create the working log**

Add `wiki/log.md` with dated sections for collection runs, failures, and observations.

- [ ] **Step 3: Create a human-readable outputs landing page**

Add `outputs/index.html` that links to summary files and explains what reviewers should inspect first.

- [ ] **Step 4: Verify files exist**

Run: `Get-ChildItem 'C:\Users\USER\codex-test\projects\bizinfo-policy-dataset' -Recurse | Select-Object FullName`
Expected: the new files appear under `README.md`, `wiki`, and `outputs`.

### Task 2: Collection Manifest Design

**Files:**
- Create: `projects/bizinfo-policy-dataset/wiki/collection-manifest-schema.md`
- Create: `projects/bizinfo-policy-dataset/raw/api/.gitkeep`
- Create: `projects/bizinfo-policy-dataset/raw/html/.gitkeep`
- Create: `projects/bizinfo-policy-dataset/raw/files/.gitkeep`
- Create: `projects/bizinfo-policy-dataset/raw/markdown/.gitkeep`

- [ ] **Step 1: Document manifest fields**

Define the metadata fields and status flags needed for each notice, including:
`notice_id`, `title`, `category`, `source_url`, `detail_html_status`, `print_file_status`, `attachment_status`, `markdown_status`, `download_error`, `conversion_error`, `collected_at`.

- [ ] **Step 2: Add placeholder keep files**

Create `.gitkeep` files so the raw folders remain visible even before data is collected.

- [ ] **Step 3: Verify folder skeleton**

Run: `Get-ChildItem 'C:\Users\USER\codex-test\projects\bizinfo-policy-dataset\raw' -Recurse -Force | Select-Object FullName`
Expected: each raw folder exists and contains a `.gitkeep`.

### Task 3: API Collection Script Design

**Files:**
- Create: `projects/bizinfo-policy-dataset/wiki/api-collection-strategy.md`
- Create: `projects/bizinfo-policy-dataset/raw/api/request-examples.md`

- [ ] **Step 1: Document API collection strategy**

Write how the Bizinfo API will be called by category, paged, deduplicated by `pblancId`, and filtered to the period `2024-06-01` through `2026-06-01`.

- [ ] **Step 2: Document request parameter mapping**

List the category codes and hashtag behavior from the official API page, and record the parameters that will be used:
`crtfcKey`, `dataType=json`, `pageUnit`, `pageIndex`, `searchLclasId`.

- [ ] **Step 3: Document sample request templates without API key**

Store example request patterns using a placeholder like `YOUR_BIZINFO_KEY`, never a real secret.

- [ ] **Step 4: Verify documentation readability**

Run: `Get-Content 'C:\Users\USER\codex-test\projects\bizinfo-policy-dataset\wiki\api-collection-strategy.md' -TotalCount 80`
Expected: the date range, 4 categories, and deduping rule are clearly visible.

### Task 4: Source Download Strategy

**Files:**
- Create: `projects/bizinfo-policy-dataset/wiki/source-download-strategy.md`
- Create: `projects/bizinfo-policy-dataset/wiki/source-priority-rules.md`

- [ ] **Step 1: Document source download order**

Define the order:
1. detail page HTML
2. print file
3. each attachment file

- [ ] **Step 2: Define filename rules**

Document a deterministic naming convention such as:
`<notice_id>__detail.html`
`<notice_id>__print.pdf`
`<notice_id>__attach_01.pdf`

- [ ] **Step 3: Define duplicate and missing-source handling**

Write what happens when a notice has no attachment, no print file, or repeated attachment URLs.

- [ ] **Step 4: Verify strategy documents**

Run: `Get-Content 'C:\Users\USER\codex-test\projects\bizinfo-policy-dataset\wiki\source-download-strategy.md' -TotalCount 80`
Expected: download order and naming rules are explicit.

### Task 5: Markdown Conversion Strategy

**Files:**
- Create: `projects/bizinfo-policy-dataset/wiki/markdown-conversion-strategy.md`
- Create: `projects/bizinfo-policy-dataset/wiki/conversion-failure-codes.md`

- [ ] **Step 1: Document per-format conversion policy**

Describe separate handling for HTML, PDF, and HWP and state that each converted file remains separate from the others.

- [ ] **Step 2: Define markdown output naming**

Document naming such as:
`<notice_id>__detail.md`
`<notice_id>__print.md`
`<notice_id>__attach_01.md`

- [ ] **Step 3: Define failure codes**

Add a compact failure code set such as:
`DOWNLOAD_FAIL`
`EMPTY_FILE`
`UNSUPPORTED_HWP`
`OCR_NEEDED`
`ENCODING_ISSUE`

- [ ] **Step 4: Verify conversion docs**

Run: `Get-Content 'C:\Users\USER\codex-test\projects\bizinfo-policy-dataset\wiki\markdown-conversion-strategy.md' -TotalCount 80`
Expected: source-separate markdown rule is explicit.

### Task 6: Analysis Output Design

**Files:**
- Create: `projects/bizinfo-policy-dataset/wiki/field-observation-template.md`
- Create: `projects/bizinfo-policy-dataset/wiki/analysis-questions.md`
- Create: `projects/bizinfo-policy-dataset/outputs/collection-summary-template.md`

- [ ] **Step 1: Create a field observation template**

Add a reusable template for noting whether each notice clearly exposes:
`지원대상`, `신청기간`, `지원내용`, `신청방법`, `제출서류`, `문의처`, `제외조건`, `유의사항`.

- [ ] **Step 2: Create analysis questions**

Write the questions reviewers must answer after collection, including which fields are consistently available and which depend on attachments.

- [ ] **Step 3: Create a summary template**

Prepare a markdown template for reporting total notices, raw source coverage, markdown conversion coverage, and major failure types.

- [ ] **Step 4: Verify analysis templates**

Run: `Get-Content 'C:\Users\USER\codex-test\projects\bizinfo-policy-dataset\wiki\analysis-questions.md' -TotalCount 80`
Expected: the project’s “what can we safely learn from the data?” questions are visible.

### Task 7: Initial Collection Readiness Check

**Files:**
- Modify: `projects/bizinfo-policy-dataset/wiki/log.md`

- [ ] **Step 1: Record readiness checklist in the log**

Add a dated checklist covering:
project folders ready, design doc ready, plan ready, API key not stored, output paths ready.

- [ ] **Step 2: Run a folder readiness command**

Run: `Get-ChildItem 'C:\Users\USER\codex-test\projects\bizinfo-policy-dataset' -Recurse | Select-Object FullName`
Expected: all project folders and planning documents exist.

- [ ] **Step 3: Review against the design doc**

Check that the created files support:
metadata collection, raw source downloads, markdown conversion, and post-collection analysis.

- [ ] **Step 4: Mark the project ready for implementation**

Add a note in `wiki/log.md` saying the project is ready for collection script implementation and first-run testing.
