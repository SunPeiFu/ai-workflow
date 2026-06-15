# Douyin Image Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a complete Douyin image-post package workflow that converts an existing dissected content project into Douyin-specific copy, ordered images, a publish checklist, and manageable history.

**Architecture:** Reuse the existing remix package grouping and Xiaohongshu image materialization helpers, but create a separate `douyin-note` package type and platform-specific copy builders. Extend the existing tabbed history UI with a Douyin tab and route generation/open-folder/delete actions through the same content IDs.

**Tech Stack:** Python standard library backend, vanilla JavaScript, HTML/CSS, `unittest`, macOS Finder `open`.

---

### Task 1: Douyin Package Generator

**Files:**
- Modify: `tests/test_web_app.py`
- Modify: `workflow/web_app.py`

- [ ] Write failing tests proving that generation creates `抖音图文.md`, `图片顺序.md`, `发布清单.md`, copied images, concise platform copy, and one current `douyin-note` package per source.
- [ ] Run `python3 -m unittest discover -s tests -p 'test_web_app.py' -v` and verify failure because `start_douyin_note_generation` is missing.
- [ ] Implement source-package resolution, Douyin title/body/tag normalization, image materialization, package replacement, and result metadata.
- [ ] Run the focused test file and verify all tests pass.

### Task 2: Folder Action And API

**Files:**
- Modify: `tests/test_web_app.py`
- Modify: `workflow/web_app.py`

- [ ] Write failing tests proving the folder action prefers `douyin-note` and falls back to the latest remix source package.
- [ ] Run the focused tests and verify failure because `open_douyin_content_folder` is missing.
- [ ] Implement the safe Finder-open helper and add `/api/remix/content/douyin-generate` plus `/api/remix/content/douyin-open-folder`.
- [ ] Run the focused tests and verify all tests pass.

### Task 3: Douyin Tab And History

**Files:**
- Modify: `web/remix.html`
- Modify: `web/remix.js`
- Modify: `web/app.css`

- [ ] Add an independent `抖音图文` tab using the existing compact panel and paginated history visual system.
- [ ] Add `douyin-note` filtering, package status, group labels, six-item pagination, generation/regeneration, open-folder, and delete actions.
- [ ] Add a `生成抖音图文` action beside the existing platform generation actions after source analysis.
- [ ] Run `node --check web/remix.js` and verify syntax passes.

### Task 4: Regression And Browser Verification

**Files:**
- Verify: `tests/`
- Verify: `web/remix.html`

- [ ] Run `python3 -m unittest discover -s tests -v`.
- [ ] Run `node --check web/remix.js`, `python3 -m py_compile workflow/web_app.py`, and `git diff --check`.
- [ ] Restart the local server and verify in the in-app browser that the Douyin tab displays projects, generates a package, and opens its folder without console errors.
- [ ] Commit all changes to the temporary feature branch without merging or pushing `main`.
