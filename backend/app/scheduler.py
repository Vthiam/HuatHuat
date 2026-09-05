"""Runs check-sso automatically on a schedule, in-process, so the whole
system is self-contained -- no external cron needed, works the same
whether run locally or deployed.

Schedule: every 30 minutes 9am-5pm Singapore time, every 3 hours outside
that window. This is a DELIBERATE OVERRIDE of SSO's Terms of Use clause
13(d), which states automated extraction is only permitted 3am-7am
Singapore time (see services/sso_client.py's should_run_now(), which
still implements that stated window and still gates the CLI/API's manual
--live check unless --override-schedule is passed).

This module's schedule was chosen explicitly, fully aware of that
tradeoff: it trades ToU compliance and some rate-limiting risk (SSO
throttled this project once already during development, after enough
rapid requests) for much fresher detection of legislative changes than a
once-daily 3-7am check would give. It calls sync_live with
override_schedule=True unconditionally -- should_run_now()'s gate is
bypassed here on purpose, not accidentally.
"""
import asyncio
import datetime
import logging
import zoneinfo

from . import cli
from .config import TRACKED_ACTS
from .db import SessionLocal

logger = logging.getLogger(__name__)

SGT = zoneinfo.ZoneInfo("Asia/Singapore")

BUSY_HOURS_INTERVAL_SECONDS = 30 * 60
QUIET_HOURS_INTERVAL_SECONDS = 3 * 60 * 60
BUSY_HOURS_START = 9
BUSY_HOURS_END = 17


def next_interval_seconds(now_sgt: datetime.datetime) -> int:
    if BUSY_HOURS_START <= now_sgt.hour < BUSY_HOURS_END:
        return BUSY_HOURS_INTERVAL_SECONDS
    return QUIET_HOURS_INTERVAL_SECONDS


def run_scheduled_check() -> None:
    """One pass: check every tracked Act, live, regardless of SSO's
    stated automated-extraction window (see module docstring). Never lets
    an exception kill the scheduler loop -- a bad run should be logged and
    retried next interval, not take the whole background task down."""
    db = SessionLocal()
    try:
        for _act_config in TRACKED_ACTS:
            # cmd_check_sso already loops over all of TRACKED_ACTS itself.
            result = cli.cmd_check_sso(db, live=True, simulate=False, clause_ref=None, override_schedule=True)
            if not result.ok:
                logger.warning("Scheduled check-sso refused: %s", result.message)
            break  # cmd_check_sso covers every tracked act in one call
    except Exception:
        logger.exception("Scheduled check-sso run failed -- will retry next interval")
    finally:
        db.close()


async def run_scheduler_loop() -> None:
    while True:
        # run_scheduled_check does blocking network I/O (requests, not
        # httpx/async) -- calling it directly here would freeze the
        # entire async event loop, meaning the whole API (every request,
        # from every user) hangs for the duration of every scheduled
        # check. asyncio.to_thread runs it on a separate thread instead,
        # so the server keeps serving requests while a check is in
        # flight. Found by actually starting the server and observing it
        # become briefly unresponsive, not assumed.
        await asyncio.to_thread(run_scheduled_check)
        now_sgt = datetime.datetime.now(tz=datetime.timezone.utc).astimezone(SGT)
        delay = next_interval_seconds(now_sgt)
        logger.info("Next scheduled check-sso in %d seconds", delay)
        await asyncio.sleep(delay)
