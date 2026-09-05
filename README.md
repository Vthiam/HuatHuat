# HuatHuat

An agent that keeps a law firm's local document library resilient to regulatory change. It watches a folder of real firm documents (`.txt`/`.docx`/`.pdf`), tracks a real Singapore statute (currently PDPA 2012, pulled live from [sso.agc.gov.sg](https://sso.agc.gov.sg)), and when that statute changes, walks a dependency graph to find every document that relies on it — directly or transitively — and flags each one with an AI-drafted note explaining how it might be affected. Nothing downstream of the statute's own mirror is ever auto-edited: every flag is a suggestion a human has to accept.

## How it's built

Five parts, each independently tested (70 automated tests, `backend/tests/`), each with a specific job:

| Module | Job |
|---|---|
| `app/models.py` | The data model everything else builds on: `Document`, `Clause`, `ClauseVersion`, `DependencyEdge`, `ChangeEvent`, `Flag` |
| `app/library_scanner.py` + `app/services/classifier.py` | Reads `law_library/inbox/`, classifies a document as statute or template (OpenAI, or a free heuristic if no key is set), files it, and detects what a template cites — a specific statute clause, or another document by name |
| `app/statute_sync.py` + `app/services/sso_client.py` | Fetches real text from SSO, diffs it against what's stored, auto-syncs the local mirror, keeps full history |
| `app/impact_service.py` + `app/services/graph_service.py` + `app/services/llm.py` | Walks the dependency graph from a changed clause (direct → transitive, until nothing new is found) and drafts a per-document recommendation (OpenAI, or an honest "needs manual review" fallback if no key) |
| `app/cli.py` + `app/services/pdf_highlighter.py` + `app/notifier.py` + `app/report.py` | The actual commands you run: ingest, check for changes, review flags — plus real PDF highlighting and desktop notifications |

No LLM in the fetch/diff path (deliberately — that's mechanical, exact-match work where a missed change is the worst possible failure mode). LLM only where genuine judgment is needed: classification and impact analysis.

## Setup

```bash
git clone https://github.com/Vthiam/HuatHuat.git
cd HuatHuat/backend

python3 -m venv venv              # create an isolated Python environment for this project
source venv/bin/activate          # activate it (Windows: venv\Scripts\activate)
pip install -r requirements.txt   # install FastAPI-adjacent deps, SQLAlchemy, requests/bs4, python-docx, PyMuPDF, etc.
```

### Optional: enable real AI reasoning

Everything runs with zero configuration — classification and impact analysis fall back to free, deterministic, local logic with no API calls. To upgrade to real OpenAI reasoning, create `backend/.env`:

```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini   # optional, this is already the default
```

`.env` is gitignored — it will never get committed. Every AI-drafted note in the output is tagged with `source: openai` or `source: heuristic` so it's always clear which path actually produced it. (`config.py` also defines `ANTHROPIC_API_KEY`/`CLAUDE_MODEL`, reserved for future use — no code path currently calls Claude; this project's AI calls all go through OpenAI.)

## Running it

```bash
python -m app.dev_seed
# One-time bootstrap. Pulls PDPA 2012's REAL 2013 text from SSO's own
# historical archive and creates the initial statute + Clause rows.
# Seeding from 2013 (not today's text) means the next command below finds
# a genuine, real amendment -- not a fabricated one.

python -m app.cli scan
# Ingests law_library/inbox/ and law_library/templates/: classifies any
# new document (statute vs template), and detects what each template
# cites -- a specific PDPA clause, or another document by name.

python -m app.cli check-sso --live --override-schedule
# Fetches TODAY's real PDPA text from SSO and diffs it against the 2013
# baseline. Finds real amendments, updates the local statute mirror, and
# flags every document that depends on whatever changed.
#
# --override-schedule is required outside 3am-7am Singapore time: SSO's
# Terms of Use only permit automated extraction in that window (see
# app/services/sso_client.py), so running this live outside it is a
# deliberate, visible override -- not a silent bypass. Omit --live and
# use this instead if you just want a guaranteed, deterministic demo
# with no network call:
#   python -m app.cli check-sso --simulate --clause-ref 4

python -m app.cli review
# Lists every pending flag in the terminal. Type 'a' to accept, 'r' to
# reject, 's' to skip, for each one. Accepting only records your
# decision -- it never rewrites the flagged document's actual content.
```

Every run also writes a timestamped Markdown report to `law_library/reports/`, and — if a flagged document is a real PDF — a highlighted copy with the AI's note attached as an annotation, saved to `law_library/reports/flagged/` (the original PDF is never modified).

## Running the tests

```bash
pytest tests/ -m "not network"   # all 70 tests, no network or API key required
pytest tests/ -m network         # +1 live smoke test against the real SSO site
```

## Known limitations

- Only Part 1 (sections 1-4) of PDPA 2012 is tracked. SSO's Act pages lazy-load other Parts via an internal SPA endpoint that's deliberately not reverse-engineered here — tracking more sections is a `TRACKED_ACTS` config change (`app/config.py`), not an architecture change.
- PDF highlighting is the only format with in-file annotation right now. A flagged `.docx` document still gets its recommendation surfaced in the report/CLI, just without a highlight drawn directly on the file.
- Desktop notifications are macOS-only (`osascript`); every other platform gets a console log line instead of a crash.
- Case-law ingestion isn't built — `Document.genre` already reserves a `CASE` value for it, so adding it later shouldn't require a schema change.
