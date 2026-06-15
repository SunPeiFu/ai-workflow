# AI Copy Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-position AI 文案 tab that directly calls local LM Studio through a safe curl wrapper and assists Gemini/ChatGPT web usage through prompt copy and page launch.

**Architecture:** Put prompt construction, curl execution, pasted-result parsing, and ignored local history in a focused `workflow/ai_copy.py` module. Expose thin JSON routes from `workflow/web_app.py`; build one two-column editor in the existing remix frontend and reuse the content-pipeline endpoint for optional project backfill.

**Tech Stack:** Python standard library, curl, LM Studio OpenAI-compatible API, vanilla JavaScript, HTML/CSS, unittest.

---

### Task 1: AI Copy Domain Module

**Files:**
- Create: `workflow/ai_copy.py`
- Create: `tests/test_ai_copy.py`

- [ ] **Step 1: Write failing prompt and parser tests**

Test that `build_ai_copy_prompt()` applies task, strength, emoji, platform, fact-preservation, and JSON-array rules; test that `parse_ai_copy_candidates()` accepts JSON arrays, fenced JSON, numbered lines, and a single pasted answer.

- [ ] **Step 2: Run the focused tests**

Run: `python3 -m unittest discover -s tests -p 'test_ai_copy.py' -v`

Expected: import failure because `workflow.ai_copy` does not exist.

- [ ] **Step 3: Implement prompt and parser functions**

Create:

```python
def build_ai_copy_prompt(text, task, strength, allow_emoji, candidate_count): ...
def parse_ai_copy_candidates(text, candidate_count=3): ...
```

Reject empty input, normalize supported tasks and strengths, and never introduce claims not present in the source.

- [ ] **Step 4: Write failing curl execution tests**

Patch `subprocess.run` and assert:

```python
["curl", "--fail-with-body", "--silent", "--show-error", "--max-time", "180",
 "-H", "Content-Type: application/json", "-H", "Authorization: Bearer lm-studio",
 "--data-binary", "@-", "http://127.0.0.1:1234/v1/chat/completions"]
```

receives JSON through `input`, not command interpolation.

- [ ] **Step 5: Implement LM Studio generation**

Create:

```python
def generate_ai_copy_with_lmstudio(payload, curl_path=None): ...
```

Select the requested model or the current LM Studio default, execute curl, decode the OpenAI-compatible response, parse candidates, and return actionable Chinese errors for missing curl, timeout, HTTP failure, and malformed model output.

- [ ] **Step 6: Write and implement history tests**

Test and implement:

```python
def list_ai_copy_history(root): ...
def save_ai_copy_history(root, payload): ...
def delete_ai_copy_history(root, entry_id): ...
```

Persist atomically to `uploads/ai-copy-history.json`, newest first, with stable generated IDs.

- [ ] **Step 7: Run focused tests**

Run: `python3 -m unittest discover -s tests -p 'test_ai_copy.py' -v`

Expected: all AI copy tests pass.

### Task 2: HTTP API Integration

**Files:**
- Modify: `workflow/web_app.py`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1: Write failing handler-level helper tests**

Test web-prompt payload output contains provider URL:

```python
{"gemini": "https://gemini.google.com/app", "chatgpt": "https://chatgpt.com/"}
```

and rejects unsupported providers.

- [ ] **Step 2: Implement thin API routes**

Add:

```text
GET  /api/remix/ai-copy/history
POST /api/remix/ai-copy/generate
POST /api/remix/ai-copy/web-prompt
POST /api/remix/ai-copy/parse
POST /api/remix/ai-copy/history/save
POST /api/remix/ai-copy/history/delete
```

Routes delegate to `workflow.ai_copy`; they do not duplicate prompt or persistence logic.

- [ ] **Step 3: Run backend regression**

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests pass.

### Task 3: AI Copy Workspace UI

**Files:**
- Modify: `web/remix.html`
- Modify: `web/remix.js`
- Modify: `web/app.css`

- [ ] **Step 1: Add first-position tab and accessible editor markup**

Add `AI 文案` before `图文生产线`, with:

- source textarea
- provider segmented control/select
- task, strength, emoji, candidate count, model controls
- generate/open buttons and progress state
- candidate cards, editable chosen result, pasted web result
- current pipeline project selector
- local history list

- [ ] **Step 2: Implement LM Studio interaction**

Call `/api/remix/ai-copy/generate`, prevent duplicate requests, display progress, render candidates, and keep source text on failure.

- [ ] **Step 3: Implement Gemini and ChatGPT web flow**

Call `/api/remix/ai-copy/web-prompt`, copy the returned prompt with `navigator.clipboard.writeText`, immediately open the provider URL in a new tab from the user click path, and show retry controls if the popup is blocked.

- [ ] **Step 4: Implement pasted-result parsing**

Submit pasted content to `/api/remix/ai-copy/parse`, render normalized candidates, and preserve the raw pasted value when parsing returns one candidate.

- [ ] **Step 5: Implement copy, edit, history, and pool backfill**

Save records through history APIs. Backfill the selected pipeline item through `/api/remix/pipeline/update`, mapping title/body/tags by task and disabling backfill when no project is selected.

- [ ] **Step 6: Implement responsive styling**

Use a compact two-column workbench on desktop and a single column below 860px. Ensure controls have stable dimensions and no horizontal overflow.

### Task 4: Verification and Commit

**Files:**
- Verify all modified files

- [ ] **Step 1: Run static and backend checks**

Run:

```bash
node --check web/remix.js
python3 -m py_compile workflow/ai_copy.py workflow/web_app.py
python3 -m unittest discover -s tests -v
git diff --check
```

Expected: zero syntax errors, zero test failures, zero whitespace errors.

- [ ] **Step 2: Restart and verify in Browser**

Open `http://127.0.0.1:8765/remix.html`, verify:

- AI 文案 is the first top tab.
- LM Studio controls are visible and models load.
- provider switching changes the primary action.
- Gemini and ChatGPT return the correct destination without losing editor state.
- pasted answers render candidates.
- history can save and restore.
- pool backfill updates the selected item.
- 1280px and mobile layouts have no horizontal overflow.
- browser console has no errors.

- [ ] **Step 3: Commit temporary branch**

```bash
git add workflow/ai_copy.py workflow/web_app.py web/remix.html web/remix.js web/app.css tests/test_ai_copy.py tests/test_web_app.py
git commit -m "Add AI copy workspace"
```

Do not merge or push `main` until user confirmation.
