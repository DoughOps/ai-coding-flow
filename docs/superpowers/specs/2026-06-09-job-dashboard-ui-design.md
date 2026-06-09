# Job Dashboard UI Enhancement Design

**Date:** 2026-06-09  
**Status:** Approved

## Problem

The current job dashboard (`docs_site/jobs.html`) shows a plain table with five columns — Status, Issue, Engine, Created, PR — and no way to filter, search, or inspect details. Now that the system supports multiple repos, the `repo_url` column is missing entirely, making it impossible to tell which repo a job belongs to. With growing job histories, the table also needs pagination to stay usable.

## Selected Features

User-selected during brainstorming:

1. **Repo column** — show `owner/repo` extracted from `repo_url`
2. **Status filter** — filter tabs: All / Queued / Processing / Done / Failed
3. **Search** — live text filter on issue title and repo slug
4. **Stats bar** — total / running / done / failed counters
5. **Job detail modal** — click a row to see full details: issue body is not stored in DB so we show all available fields: `error_msg`, `updated_at`, `engine`, `platform`, `repo_url`, `pr_url`
6. **Pagination** — "Load more" button; initial page = 50 jobs, each load adds 50 more

## Architecture

All filtering, searching, and stats computation are client-side (the full fetched page is kept in memory). Pagination fetches additional pages from the server. The only backend change is adding an `offset` query param to `/api/jobs`.

### Backend: `store.py` + `server.py`

`list_jobs` gains an `offset: int = 0` parameter:

```python
def list_jobs(db_path: str, limit: int = 50, offset: int = 0) -> list[dict]:
    ...
    conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
```

`/api/jobs` accepts `?limit=50&offset=0` query params (FastAPI `Query` defaults):

```python
@app.get("/api/jobs")
async def api_jobs(request: Request, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    ...
    return store.list_jobs(settings.db_path, limit=limit, offset=offset)
```

### Frontend: `docs_site/jobs.html`

**State model** (JS variables):
- `allJobs` — flat array of all jobs fetched so far (accumulates on "load more")
- `currentOffset` — current fetch offset
- `PAGE_SIZE = 50` — rows per page
- `activeStatus` — current status filter (`""` = All)
- `searchQuery` — current search string

**Stats bar** — rendered above the toolbar, computed from `allJobs`:
```
Total: 42  •  Running: 3  •  Done: 35  •  Failed: 4
```

**Toolbar** — search input on the left, status filter buttons in the middle, Refresh on the right.

**Table** — adds a **Repo** column between Issue and Engine, showing `owner/repo` extracted from `repo_url` via `_repoSlug(url)`:
```js
function _repoSlug(url) {
  try {
    return new URL(url).pathname.replace(/^\//, '').replace(/\.git$/, '');
  } catch { return url; }
}
```

**Filtering** — `_filtered()` returns `allJobs` filtered by `activeStatus` and `searchQuery` (case-insensitive match on `issue_title` + `_repoSlug(repo_url)`).

**Pagination** — below the table:
- "Load more" button visible when last fetch returned exactly `PAGE_SIZE` rows
- Clicking it fetches `?limit=50&offset=currentOffset`, appends to `allJobs`, re-renders

**Detail modal** — clicking any table row opens a `<dialog>` showing:
```
Issue:    #42 — Fix login bug
Repo:     owner/repo
Platform: github
Status:   failed
Engine:   aider
PR:       https://... (link) or —
Error:    <pre>tests failed: ...</pre>  (only shown when non-empty)
Created:  Jun 9, 2026, 14:32
Updated:  Jun 9, 2026, 14:45
```

Clicking outside the dialog or a close button dismisses it.

## Data Flow

```
page load / Refresh
  → fetch /api/jobs?limit=50&offset=0
  → allJobs = response, currentOffset = 50
  → renderStats(allJobs)
  → renderTable(_filtered())
  → renderPagination(response.length === PAGE_SIZE)

"Load more"
  → fetch /api/jobs?limit=50&offset=currentOffset
  → allJobs = allJobs.concat(response), currentOffset += 50
  → re-render all

status filter click / search input
  → update activeStatus / searchQuery
  → renderTable(_filtered())   (no fetch)

row click
  → openModal(job)

auto-refresh (30 s)
  → same as Refresh
```

## What Does Not Change

- Auth dialog (`X-Admin-Token`) — unchanged
- Dark/light theme — unchanged
- Auto-refresh interval (30 s) — unchanged
- Webhook endpoints, worker, config — no changes
