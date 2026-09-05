"""Bootstraps the tracked statute(s) from a real historical SSO snapshot.

Run once per fresh clone/DB (backend/data/app.db is gitignored, so every
teammate needs to run this themselves):

    cd backend && venv/bin/python -m app.dev_seed

This deliberately seeds from 2013, not today's text, so the first
`statute_sync.sync_live()` afterwards (via feature/cli-reports-review's
"check now" command, once that lands) produces a genuine redline against
real historical amendments -- not fabricated demo data. See
statute_sync.seed_from_historical's docstring for why.
"""
from .config import TRACKED_ACTS
from .db import Base, SessionLocal, engine
from . import statute_sync

# A known historical consolidation of PDPA 2012, confirmed live on SSO:
# /Act/PDPA2012/Historical/20130102?DocDate=20121203&ValidDate=20130102
PDPA_HISTORICAL_VALID_DATE = "20130102"
PDPA_HISTORICAL_DOC_DATE = "20121203"


def seed_all():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for act_config in TRACKED_ACTS:
            if act_config["act_id"] == "PDPA2012":
                events = statute_sync.seed_from_historical(
                    db, act_config, PDPA_HISTORICAL_VALID_DATE, PDPA_HISTORICAL_DOC_DATE
                )
            else:
                events = statute_sync.sync_live(db, act_config)
            print(f"Seeded {act_config['name']} ({len(events)} change events on first seed, expected 0)")
    finally:
        db.close()


if __name__ == "__main__":
    seed_all()
