# Job Dashboard UI Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance the job dashboard with a Repo column, stats bar, status filter, search, load-more pagination, and a per-row detail modal.

**Architecture:** Backend gains an `offset` query param for pagination. All filtering and search are client-side (data already fetched). The frontend accumulates pages in `allJobs[]` and re-renders on each user interaction without additional fetches.

**Tech Stack:** Python/FastAPI (backend), vanilla JS + HTML/CSS (frontend), SQLite via `store.py`, pytest for backend tests.

---

## File Map

| File | Change |
|------|--------|
| `store.py` | Add `offset: int = 0` param to `list_jobs`; default `limit` changes from 100 → 50 |
| `server.py` | Add `limit` and `offset` FastAPI `Query` params to `GET /api/jobs` |
| `docs_site/jobs.html` | All UI changes: stats bar, repo column, filter tabs, search, pagination, detail modal |
| `tests/test_store.py` | Add test for offset pagination |
| `tests/test_server.py` | Add test that `/api/jobs` forwards limit/offset to `store.list_jobs` |

---

### Task 1: Backend — add offset pagination to store and server

**Files:**
- Modify: `store.py:65-71`
- Modify: `server.py:52-58`
- Test: `tests/test_store.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write failing test for offset in test_store.py**

Add at the end of `tests/test_store.py`:

```python
def test_list_jobs_respects_offset(db):
    for i in range(5):
        store.create_job(db, platform="github", issue_number=i, issue_title=f"Issue {i}")
    # ORDER BY id DESC gives: Issue4, Issue3, Issue2, Issue1, Issue0
    # offset=2, limit=5 → Issue2, Issue1, Issue0
    jobs = store.list_jobs(db, limit=5, offset=2)
    assert len(jobs) == 3
    assert jobs[0]["issue_title"] == "Issue 4".replace("4", "2")  # Issue 2
```

Replace the placeholder comment with the real assertion — the complete step is:

```python
def test_list_jobs_respects_offset(db):
    for i in range(5):
        store.create_job(db, platform="github", issue_number=i, issue_title=f"Issue {i}")
    jobs = store.list_jobs(db, limit=5, offset=2)
    assert len(jobs) == 3
    assert jobs[0]["issue_title"] == "Issue 2"
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd /home/neverleave0916/workspace/ai-test && pytest tests/test_store.py::test_list_jobs_respects_offset -v
```

Expected: FAIL — `list_jobs() got an unexpected keyword argument 'offset'`

- [ ] **Step 3: Implement offset in store.py**

Replace the `list_jobs` function in `store.py` (currently lines 65-71):

```python
def list_jobs(db_path: str, limit: int = 50, offset: int = 0) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
    return [dict(row) for row in rows]
```

- [ ] **Step 4: Run test — verify it passes**

```bash
pytest tests/test_store.py::test_list_jobs_respects_offset -v
```

Expected: PASS

- [ ] **Step 5: Write failing test for pagination query params in test_server.py**

Add at the end of `tests/test_server.py`:

```python
def test_api_jobs_forwards_limit_and_offset(client):
    from unittest.mock import ANY
    with patch("server.store.list_jobs", return_value=[]) as mock_list:
        resp = client.get("/api/jobs?limit=10&offset=20")
    assert resp.status_code == 200
    mock_list.assert_called_once_with(ANY, limit=10, offset=20)
```

- [ ] **Step 6: Run test — verify it fails**

```bash
pytest tests/test_server.py::test_api_jobs_forwards_limit_and_offset -v
```

Expected: FAIL — `AssertionError: expected call with limit=10, offset=20`

- [ ] **Step 7: Add Query params to /api/jobs in server.py**

In `server.py`, the `fastapi` import line (line 13) currently reads:

```python
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
```

Replace it with:

```python
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
```

Replace the `api_jobs` function (currently lines 52-58):

```python
@app.get("/api/jobs")
async def api_jobs(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    if settings.admin_password:
        token = request.headers.get("X-Admin-Token", "")
        if not hmac.compare_digest(token, settings.admin_password):
            raise HTTPException(status_code=401, detail="Unauthorized")
    return store.list_jobs(settings.db_path, limit=limit, offset=offset)
```

- [ ] **Step 8: Run full test suite**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests pass (including the two new ones). The existing `test_api_jobs_open_when_no_password`, `test_api_jobs_wrong_token_returns_401`, and `test_api_jobs_correct_token_returns_200` must still pass — they don't pass limit/offset so the defaults (50, 0) apply.

- [ ] **Step 9: Commit**

```bash
git add store.py server.py tests/test_store.py tests/test_server.py
git commit -m "feat: add offset pagination to /api/jobs endpoint"
```

---

### Task 2: Frontend — state refactor + Repo column + Stats bar

**Files:**
- Modify: `docs_site/jobs.html`

This task refactors the JS to use an `allJobs` array (needed by later tasks) and adds the Repo column and stats bar. No filter or search yet.

- [ ] **Step 1: Add CSS for stats bar and repo column**

Inside the `<style>` block in `docs_site/jobs.html`, add before the closing `</style>`:

```css
  .stats-bar { display: flex; gap: 16px; font-size: 13px; color: var(--text-muted); margin-bottom: 12px; }
  .stats-bar strong { color: var(--text); }
  .repo-cell { font-size: 12px; color: var(--text-muted); max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  tr.job-row { cursor: pointer; }
```

- [ ] **Step 2: Add stats bar div to HTML**

In `docs_site/jobs.html`, inside `<main>`, add the `<div id="statsBar">` immediately before the existing `<div class="toolbar">`:

```html
  <div id="statsBar" class="stats-bar"></div>
  <div class="toolbar">
```

The existing toolbar and `tableWrap` are unchanged.

- [ ] **Step 3: Replace the JS data/render section**

Replace everything from `// ── data ──` down to (but not including) `// ── boot ──` in the `<script>` block with:

```javascript
  // ── state ─────────────────────────────────────────────────────────────────
  const PAGE_SIZE = 50;
  let allJobs = [];
  let currentOffset = 0;

  // ── helpers ───────────────────────────────────────────────────────────────
  function formatDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  function _repoSlug(url) {
    try { return new URL(url).pathname.replace(/^\//, '').replace(/\.git$/, ''); }
    catch { return url || '—'; }
  }

  function escHtml(str) {
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ── render ────────────────────────────────────────────────────────────────
  function renderStats() {
    const running = allJobs.filter(j => j.status === 'processing' || j.status === 'reworking').length;
    const done    = allJobs.filter(j => j.status === 'done').length;
    const failed  = allJobs.filter(j => j.status === 'failed').length;
    document.getElementById('statsBar').innerHTML =
      `Total: <strong>${allJobs.length}</strong> &nbsp;·&nbsp; ` +
      `Running: <strong>${running}</strong> &nbsp;·&nbsp; ` +
      `Done: <strong>${done}</strong> &nbsp;·&nbsp; ` +
      `Failed: <strong>${failed}</strong>`;
  }

  function renderTable(jobs) {
    const wrap = document.getElementById('tableWrap');
    if (!jobs.length) {
      wrap.innerHTML = '<div class="empty">No jobs yet.</div>';
      return;
    }
    const rows = jobs.map(j => `
      <tr class="job-row" onclick="openModal(${j.id})">
        <td><span class="badge badge-${j.status}">${j.status.replace(/_/g,' ')}</span></td>
        <td>
          <div class="issue-title">${escHtml(j.issue_title)}</div>
          <div class="issue-num">${escHtml(j.platform)} #${j.issue_number}</div>
        </td>
        <td class="repo-cell">${escHtml(_repoSlug(j.repo_url))}</td>
        <td>${j.engine ? escHtml(j.engine) : '—'}</td>
        <td>${formatDate(j.created_at)}</td>
        <td>${j.pr_url ? `<a class="pr-link" href="${escHtml(j.pr_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">PR ↗</a>` : '—'}</td>
      </tr>`).join('');
    wrap.innerHTML = `
      <table>
        <thead><tr><th>Status</th><th>Issue</th><th>Repo</th><th>Engine</th><th>Created</th><th>PR</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  function openModal(_id) { /* implemented in Task 5 */ }

  async function loadJobs() {
    const statusLine = document.getElementById('statusLine');
    statusLine.textContent = 'Loading…';
    allJobs = [];
    currentOffset = 0;
    try {
      const resp = await fetch(`/api/jobs?limit=${PAGE_SIZE}&offset=0`, {
        headers: getToken() ? { 'X-Admin-Token': getToken() } : {},
      });
      if (resp.status === 401) {
        sessionStorage.removeItem('adminToken');
        document.getElementById('authDialog').showModal();
        statusLine.textContent = 'Authentication required.';
        return;
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const jobs = await resp.json();
      allJobs = jobs;
      currentOffset = jobs.length;
      renderStats();
      renderTable(allJobs);
      statusLine.textContent = `${jobs.length} job${jobs.length !== 1 ? 's' : ''} · refreshed ${new Date().toLocaleTimeString()}`;
    } catch (err) {
      statusLine.textContent = `Error: ${err.message}`;
    }
  }
```

- [ ] **Step 4: Verify in browser**

Start the dev server:
```bash
cd /home/neverleave0916/workspace/ai-test && uvicorn server:app --reload --port 8000
```

Open `http://localhost:8000/guide` then navigate to the Jobs page (or open `http://localhost:8000/api/jobs` to check the API returns `repo_url`). Verify:
- Stats bar shows "Total: N · Running: N · Done: N · Failed: N"
- Table has 6 columns: Status, Issue, **Repo**, Engine, Created, PR
- Repo column shows `owner/repo` format (e.g., `octocat/hello-world`)
- Clicking a row does nothing yet (openModal is a stub)

- [ ] **Step 5: Commit**

```bash
git add docs_site/jobs.html
git commit -m "feat: add stats bar and repo column to job dashboard"
```

---

### Task 3: Frontend — Status filter tabs + Search input

**Files:**
- Modify: `docs_site/jobs.html`

- [ ] **Step 1: Add CSS for filter tabs and search**

Add inside `<style>` before `</style>`:

```css
  .filter-row { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
  .filter-tabs { display: flex; gap: 4px; }
  .filter-tab { background: none; border: 1px solid var(--border); border-radius: 20px; padding: 3px 12px; cursor: pointer; color: var(--text-muted); font-size: 12px; font-weight: 500; }
  .filter-tab:hover { border-color: var(--accent); color: var(--accent); }
  .filter-tab.active { background: var(--accent); color: var(--accent-fg); border-color: var(--accent); }
  .search-input { border: 1px solid var(--border); border-radius: 6px; padding: 4px 10px; background: var(--surface); color: var(--text); font-size: 13px; width: 200px; }
  .search-input:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
```

- [ ] **Step 2: Replace the toolbar HTML**

Replace the existing `<div class="toolbar">...</div>` in `<main>`:

```html
  <div class="filter-row">
    <div class="filter-tabs">
      <button class="filter-tab active" onclick="setFilter('')">All</button>
      <button class="filter-tab" onclick="setFilter('queued')">Queued</button>
      <button class="filter-tab" onclick="setFilter('processing')">Processing</button>
      <button class="filter-tab" onclick="setFilter('done')">Done</button>
      <button class="filter-tab" onclick="setFilter('failed')">Failed</button>
    </div>
    <input class="search-input" id="searchInput" type="search" placeholder="Search issues or repos…" oninput="setSearch(this.value)">
    <span style="flex:1"></span>
    <span id="statusLine" style="color:var(--text-muted);font-size:13px">Loading…</span>
    <button class="refresh-btn" onclick="loadJobs()">Refresh</button>
  </div>
```

- [ ] **Step 3: Add filter/search state and functions to JS**

Add to the `// ── state ──` section (after the existing state variables):

```javascript
  let activeStatus = '';
  let searchQuery  = '';
```

Add to the `// ── helpers ──` section:

```javascript
  function _filtered() {
    return allJobs.filter(j => {
      if (activeStatus && j.status !== activeStatus) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const inTitle = j.issue_title.toLowerCase().includes(q);
        const inRepo  = _repoSlug(j.repo_url).toLowerCase().includes(q);
        if (!inTitle && !inRepo) return false;
      }
      return true;
    });
  }

  function setFilter(status) {
    activeStatus = status;
    document.querySelectorAll('.filter-tab').forEach(b => {
      b.classList.toggle('active', b.textContent.toLowerCase() === (status || 'all'));
    });
    renderTable(_filtered());
  }

  function setSearch(val) {
    searchQuery = val.trim();
    renderTable(_filtered());
  }
```

- [ ] **Step 4: Update renderTable call in loadJobs**

In `loadJobs()`, replace:

```javascript
      renderTable(allJobs);
```

with:

```javascript
      renderTable(_filtered());
```

- [ ] **Step 5: Verify in browser**

With the dev server running, open the Jobs page and verify:
- Filter tabs appear (All / Queued / Processing / Done / Failed)
- Clicking "Failed" shows only failed jobs; "All" restores all
- Typing in the search box filters rows by title or repo slug
- Stats bar still reflects the full `allJobs` count (not filtered count)

- [ ] **Step 6: Commit**

```bash
git add docs_site/jobs.html
git commit -m "feat: add status filter tabs and search to job dashboard"
```

---

### Task 4: Frontend — "Load more" pagination

**Files:**
- Modify: `docs_site/jobs.html`

- [ ] **Step 1: Add CSS for the load-more button**

Add inside `<style>` before `</style>`:

```css
  .load-more-wrap { text-align: center; margin-top: 16px; }
  .load-more-btn { background: none; border: 1px solid var(--border); border-radius: 6px; padding: 6px 20px; cursor: pointer; color: var(--text); font-size: 13px; }
  .load-more-btn:hover { border-color: var(--accent); color: var(--accent); }
```

- [ ] **Step 2: Add pagination div to HTML**

Add immediately after `<div id="tableWrap"></div>` in `<main>`:

```html
  <div class="load-more-wrap" id="paginationWrap" style="display:none">
    <button class="load-more-btn" onclick="loadMore()">Load more</button>
  </div>
```

- [ ] **Step 3: Add renderPagination and loadMore functions to JS**

Add to the `// ── render ──` section, after `renderTable`:

```javascript
  function renderPagination(hasMore) {
    document.getElementById('paginationWrap').style.display = hasMore ? 'block' : 'none';
  }
```

Add a new `// ── load more ──` section before `// ── boot ──`:

```javascript
  // ── load more ─────────────────────────────────────────────────────────────
  async function loadMore() {
    try {
      const resp = await fetch(`/api/jobs?limit=${PAGE_SIZE}&offset=${currentOffset}`, {
        headers: getToken() ? { 'X-Admin-Token': getToken() } : {},
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const jobs = await resp.json();
      allJobs = allJobs.concat(jobs);
      currentOffset += jobs.length;
      renderStats();
      renderTable(_filtered());
      renderPagination(jobs.length === PAGE_SIZE);
      document.getElementById('statusLine').textContent =
        `${allJobs.length} job${allJobs.length !== 1 ? 's' : ''} loaded`;
    } catch (err) {
      document.getElementById('statusLine').textContent = `Error: ${err.message}`;
    }
  }
```

- [ ] **Step 4: Call renderPagination from loadJobs**

In `loadJobs()`, after `renderTable(_filtered());`, add:

```javascript
      renderPagination(jobs.length === PAGE_SIZE);
```

- [ ] **Step 5: Verify in browser**

To test pagination without needing 50+ jobs, temporarily change `PAGE_SIZE` to `2` in the browser console:

```javascript
PAGE_SIZE = 2; loadJobs();
```

(Don't commit `PAGE_SIZE = 2` — this is browser-console-only testing.)

Verify:
- "Load more" button appears at the bottom when there are more pages
- Clicking it appends new rows without losing existing ones
- Stats bar total increases as more pages load
- Active filter and search still apply to the full accumulated list
- Button disappears when the last page has fewer than `PAGE_SIZE` rows

- [ ] **Step 6: Commit**

```bash
git add docs_site/jobs.html
git commit -m "feat: add load-more pagination to job dashboard"
```

---

### Task 5: Frontend — Job detail modal

**Files:**
- Modify: `docs_site/jobs.html`

Clicking a row opens a `<dialog>` showing all stored fields for that job, including `error_msg` when non-empty.

- [ ] **Step 1: Add CSS for detail dialog**

Add inside `<style>` before `</style>`:

```css
  #detailDialog { max-width: 520px; width: 100%; }
  #detailDialog h2 { font-size: 15px; margin-bottom: 16px; }
  .detail-list { display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; font-size: 13px; }
  .detail-list dt { color: var(--text-muted); font-weight: 600; white-space: nowrap; padding-top: 2px; }
  .detail-list dd { word-break: break-word; margin: 0; }
  .error-pre { background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 8px; font-size: 12px; overflow-x: auto; white-space: pre-wrap; margin-top: 4px; max-height: 200px; overflow-y: auto; }
  .modal-close { float: right; background: none; border: none; font-size: 18px; cursor: pointer; color: var(--text-muted); line-height: 1; }
  .modal-close:hover { color: var(--text); }
```

- [ ] **Step 2: Add detail dialog HTML**

Add a second `<dialog>` element after the existing `<dialog id="authDialog">...</dialog>`:

```html
<dialog id="detailDialog">
  <button class="modal-close" onclick="document.getElementById('detailDialog').close()">✕</button>
  <h2>Job details</h2>
  <div id="modalContent"></div>
</dialog>
```

- [ ] **Step 3: Implement openModal in JS**

Replace the stub `function openModal(_id) { /* implemented in Task 5 */ }` with:

```javascript
  function openModal(jobId) {
    const j = allJobs.find(x => x.id === jobId);
    if (!j) return;
    document.getElementById('modalContent').innerHTML = `
      <dl class="detail-list">
        <dt>Issue</dt>   <dd>#${j.issue_number} — ${escHtml(j.issue_title)}</dd>
        <dt>Repo</dt>    <dd>${escHtml(_repoSlug(j.repo_url))}</dd>
        <dt>Platform</dt><dd>${escHtml(j.platform)}</dd>
        <dt>Status</dt>  <dd><span class="badge badge-${j.status}">${j.status.replace(/_/g,' ')}</span></dd>
        <dt>Engine</dt>  <dd>${j.engine ? escHtml(j.engine) : '—'}</dd>
        <dt>PR</dt>      <dd>${j.pr_url ? `<a href="${escHtml(j.pr_url)}" target="_blank" rel="noopener">${escHtml(j.pr_url)}</a>` : '—'}</dd>
        ${j.error_msg ? `<dt>Error</dt><dd><pre class="error-pre">${escHtml(j.error_msg)}</pre></dd>` : ''}
        <dt>Created</dt> <dd>${formatDate(j.created_at)}</dd>
        <dt>Updated</dt> <dd>${formatDate(j.updated_at)}</dd>
      </dl>`;
    document.getElementById('detailDialog').showModal();
  }
```

- [ ] **Step 4: Close modal on backdrop click**

Add to the `// ── boot ──` section (after the existing `loadJobs();` and `setInterval` calls):

```javascript
  document.getElementById('detailDialog').addEventListener('click', function(e) {
    const rect = this.getBoundingClientRect();
    if (e.clientX < rect.left || e.clientX > rect.right ||
        e.clientY < rect.top  || e.clientY > rect.bottom) {
      this.close();
    }
  });
```

- [ ] **Step 5: Verify in browser**

Open the Jobs page and verify:
- Clicking any row opens the detail modal
- Modal shows: Issue number + title, Repo slug, Platform, Status badge, Engine, PR link (or —), Error block (only if non-empty), Created and Updated timestamps
- Clicking ✕ closes the modal
- Clicking outside the modal (on the backdrop) also closes it
- PR link in the main table still opens without triggering the modal (because `event.stopPropagation()` is on the link — this was added in Task 2's `renderTable`)

- [ ] **Step 6: Run the full backend test suite to confirm no regressions**

```bash
cd /home/neverleave0916/workspace/ai-test && pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add docs_site/jobs.html
git commit -m "feat: add job detail modal to dashboard"
```
