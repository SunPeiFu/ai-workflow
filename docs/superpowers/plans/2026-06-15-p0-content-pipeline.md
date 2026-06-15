# P0 Content Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a five-step image-commerce pipeline for batch source intake, product scoring, platform rewrites, image arrangement, and pre-publish quality control.

**Architecture:** Add a focused `workflow/content_pipeline.py` domain module that persists lightweight project state under the ignored `uploads/content-pipeline.json` file and derives source content from existing remix packages. Expose JSON APIs through `workflow/web_app.py`, then add one `图文生产线` tab whose step navigation updates a shared project list and focused work area.

**Tech Stack:** Python standard library, vanilla JavaScript, HTML/CSS, local LM Studio integration through existing rewrite APIs, `unittest`.

---

### Task 1: Batch Material Pool

**Files:**
- Create: `workflow/content_pipeline.py`
- Create: `tests/test_content_pipeline.py`
- Modify: `workflow/web_app.py`

- [ ] Write failing tests for batch link parsing, URL deduplication, persistent status, and package-backed pool listing.
- [ ] Run `python3 -m unittest discover -s tests -p 'test_content_pipeline.py' -v` and verify the missing module failure.
- [ ] Implement `add_pool_links`, `list_pool_items`, `update_pool_item`, and JSON persistence.
- [ ] Add `/api/remix/pipeline` GET and `/api/remix/pipeline/add` POST endpoints.
- [ ] Run the focused tests and verify they pass.

### Task 2: Product Selection Score

**Files:**
- Modify: `workflow/content_pipeline.py`
- Modify: `tests/test_content_pipeline.py`
- Modify: `workflow/web_app.py`

- [ ] Write failing tests for commission, sales, rating, store quality, refund risk, coupon, and asset-completeness scoring.
- [ ] Implement a transparent 100-point score with component breakdown and recommendation grade.
- [ ] Add `/api/remix/pipeline/product` to save product metrics and recalculate the score.
- [ ] Run focused tests and verify they pass.

### Task 3: Batch Platform Rewrites

**Files:**
- Modify: `workflow/content_pipeline.py`
- Modify: `tests/test_content_pipeline.py`
- Modify: `workflow/web_app.py`

- [ ] Write failing tests proving one source creates distinct Xiaohongshu and Douyin title/body/tag variants.
- [ ] Implement deterministic platform drafts with light, medium, and deep rewrite levels while preserving product facts.
- [ ] Add `/api/remix/pipeline/rewrite` for one or multiple selected projects.
- [ ] Run focused tests and verify they pass.

### Task 4: Image Arrangement Workspace

**Files:**
- Modify: `workflow/content_pipeline.py`
- Modify: `tests/test_content_pipeline.py`
- Modify: `workflow/web_app.py`
- Modify: `web/remix.js`

- [ ] Write failing tests for image ordering, cover selection, deletion, and persistence.
- [ ] Implement normalized image arrangement state and `/api/remix/pipeline/images`.
- [ ] Build draggable image cards with cover selection and delete controls.
- [ ] Verify reordered images feed both platform drafts.

### Task 5: Pre-Publish Quality Control

**Files:**
- Modify: `workflow/content_pipeline.py`
- Modify: `tests/test_content_pipeline.py`
- Modify: `workflow/web_app.py`

- [ ] Write failing tests for missing images, excessive title length, platform terms, absolute claims, missing product data, and publish-ready status.
- [ ] Implement issue severity, quality score, blocking reasons, and `ready_to_publish`.
- [ ] Add `/api/remix/pipeline/audit`.
- [ ] Run focused tests and verify they pass.

### Task 6: Five-Step Production UI

**Files:**
- Modify: `web/remix.html`
- Modify: `web/remix.js`
- Modify: `web/app.css`

- [ ] Add a `图文生产线` top-level tab with five step buttons and a compact project queue.
- [ ] Implement batch link input, selection, filtering, and status display.
- [ ] Implement product score form and score breakdown.
- [ ] Implement batch rewrite controls and platform draft previews.
- [ ] Implement image arrangement and quality report panels.
- [ ] Preserve responsive behavior and avoid horizontal overflow.

### Task 7: Regression Verification

**Files:**
- Verify: `tests/`
- Verify: `web/remix.html`

- [ ] Run `python3 -m unittest discover -s tests -v`.
- [ ] Run `node --check web/remix.js`, `python3 -m py_compile workflow/content_pipeline.py workflow/web_app.py`, and `git diff --check`.
- [ ] Restart the local server and verify the full five-step flow in the in-app browser.
- [ ] Commit the implementation on `codex/p0-content-pipeline` without merging `main`.
