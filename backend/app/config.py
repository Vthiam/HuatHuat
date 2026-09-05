import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
LAW_LIBRARY_DIR = BASE_DIR.parent / "law_library"

# Drop any document into INBOX_DIR and feature/ingestion-citations auto-classifies
# it (statute vs template) and files it into STATUTES_DIR / TEMPLATES_DIR itself.
# Placing a file directly in STATUTES_DIR / TEMPLATES_DIR (skipping the inbox)
# remains supported too -- that's a human classification, no AI involved, and
# is why Document.classification_source/confidence are nullable (see models.py).
INBOX_DIR = LAW_LIBRARY_DIR / "inbox"
STATUTES_DIR = LAW_LIBRARY_DIR / "statutes"
TEMPLATES_DIR = LAW_LIBRARY_DIR / "templates"
REPORTS_DIR = LAW_LIBRARY_DIR / "reports"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")

# feature/ingestion-citations uses OpenAI rather than Claude for its
# classify/detect-citations calls (team's hackathon key is OpenAI). Both
# providers are optional -- with neither key set, everything falls back to
# free, local, heuristic logic. Keep real-key calls to spot-checks only;
# this hackathon's OpenAI budget is a hard $15 cap.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Below this, an auto-classified document still gets filed into its
# best-guess folder, but is reported as needing human confirmation.
CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.6

# SSO Terms of Use clause 13(d): automated extraction only 3am-7am Singapore time.
SSO_SCRAPE_WINDOW_START_HOUR_SGT = 3
SSO_SCRAPE_WINDOW_END_HOUR_SGT = 7

SSO_BASE_URL = "https://sso.agc.gov.sg"
SSO_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Acts this firm's library tracks. clause_refs limits scraping/diffing to the
# sections we actually ingest (SSO lazy-loads an Act's other Parts via an
# internal SPA endpoint we deliberately don't reverse-engineer here -- see
# README "Known limitations"). local_filename is where the mirror lives
# under STATUTES_DIR -- feature/sso-diff-history reads/writes this file
# directly; the DB's Document.file_path should match it.
TRACKED_ACTS = [
    {
        "act_id": "PDPA2012",
        "name": "Personal Data Protection Act 2012",
        "clause_refs": ["1", "2", "3", "4"],
        "local_filename": "PDPA2012.txt",
    }
]
