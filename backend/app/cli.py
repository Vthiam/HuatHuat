"""The actual entry point tying every branch together.

    python -m app.cli scan
    python -m app.cli check-sso --live [--override-schedule]
    python -m app.cli check-sso --simulate --clause-ref 4
    python -m app.cli review [--status pending]

Each subcommand is backed by a plain function (cmd_scan, cmd_check_sso,
cmd_review) so tests call them directly instead of shelling out to a
subprocess.
"""
import argparse
import datetime
import sys
from typing import Iterator, List, Optional

from . import impact_service, library_scanner, notifier, report, statute_sync
from .config import TRACKED_ACTS
from .db import Base, SessionLocal, engine
from .models import DependencyEdge, Flag, FlagStatus
from .services.pdf_highlighter import highlight_flag_in_pdf
from .services.sso_client import should_run_now


def cmd_scan(db) -> None:
    inbox_result = library_scanner.scan_inbox(db)
    template_result = library_scanner.scan_templates(db)
    path = report.write_scan_report(inbox_result, template_result)

    print(f"Classified {len(inbox_result.classified)} document(s) from inbox/")
    for c in inbox_result.classified:
        note = " [NEEDS CONFIRMATION]" if c.needs_confirmation else ""
        print(f"  - {c.document.name} -> {c.document.genre.value} ({c.confidence:.0%}){note}")

    print(f"Registered {len(template_result.new_documents)} new template(s)")
    print(f"Detected {len(template_result.edges_created)} new dependency edge(s)")
    print(f"Report written to {path}")


def _excerpt_for_flag(db, flag: Flag) -> str:
    if flag.via_document_id is None:
        edge = (
            db.query(DependencyEdge)
            .filter_by(from_document_id=flag.document_id, to_clause_id=flag.change_event.clause_id)
            .first()
        )
    else:
        edge = (
            db.query(DependencyEdge)
            .filter_by(from_document_id=flag.document_id, to_document_id=flag.via_document_id, to_clause_id=None)
            .first()
        )
    return edge.excerpt if edge is not None else ""


def cmd_check_sso(
    db, live: bool, simulate: bool, clause_ref: Optional[str], override_schedule: bool
) -> int:
    if live == simulate:
        print("Specify exactly one of --live or --simulate")
        return 1

    if live and not override_schedule and not should_run_now():
        print(
            "Refusing to run a live SSO check outside the permitted automated-extraction "
            "window (3am-7am Singapore time, per SSO Terms of Use clause 13(d)). "
            "Pass --override-schedule to run anyway as a deliberate manual/demo override."
        )
        return 1

    if simulate and not clause_ref:
        print("--simulate requires --clause-ref")
        return 1

    all_events = []
    for act_config in TRACKED_ACTS:
        if live:
            events = statute_sync.sync_live(db, act_config)
        else:
            events = statute_sync.sync_simulated(db, act_config, clause_ref)
        all_events.extend(events)

    flags = impact_service.process_all(db, all_events)

    highlighted_pdfs = {}
    for flag in flags:
        excerpt = _excerpt_for_flag(db, flag)
        output_path = highlight_flag_in_pdf(flag.document, flag, excerpt)
        if output_path is not None:
            highlighted_pdfs[flag.id] = output_path

    report_path = report.write_check_report(all_events, flags, highlighted_pdfs)

    print(f"Detected {len(all_events)} statute change(s)")
    print(f"Raised {len(flags)} flag(s)")
    for pdf_path in highlighted_pdfs.values():
        print(f"  Highlighted PDF: {pdf_path}")
    print(f"Report written to {report_path}")

    if flags:
        notifier.notify(
            title="Statute change detected",
            message=f"{len(flags)} document(s) flagged for review.",
        )
    elif all_events:
        notifier.notify(
            title="Statute change detected",
            message="No dependent documents found in the library.",
        )

    return 0


def cmd_review(db, status: str = "pending", auto_answers: Optional[List[str]] = None) -> None:
    """auto_answers lets tests (and any future scripted use) drive this
    without real stdin: a list of 'a'/'r'/'s' consumed in order instead of
    calling input()."""
    flags = db.query(Flag).filter_by(status=FlagStatus(status)).order_by(Flag.created_at).all()
    if not flags:
        print(f"No flags with status={status}.")
        return

    answers: Optional[Iterator[str]] = iter(auto_answers) if auto_answers is not None else None

    for flag in flags:
        print(f"\n[{flag.id}] {flag.document.name} ({flag.flag_type.value})")
        print(f"  {flag.recommendation_text}")

        if answers is not None:
            answer = next(answers, "s")
        else:
            answer = input("  [a]ccept / [r]eject / [s]kip: ").strip().lower()

        if answer == "a":
            flag.status = FlagStatus.ACCEPTED
        elif answer == "r":
            flag.status = FlagStatus.REJECTED
        else:
            continue

        flag.resolved_at = datetime.datetime.utcnow()
        db.commit()
        print(f"  -> {flag.status.value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan")

    check = sub.add_parser("check-sso")
    mode = check.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--simulate", action="store_true")
    check.add_argument("--clause-ref", default=None)
    check.add_argument("--override-schedule", action="store_true")

    review = sub.add_parser("review")
    review.add_argument("--status", default="pending")

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if args.command == "scan":
            cmd_scan(db)
            return 0
        if args.command == "check-sso":
            return cmd_check_sso(db, args.live, args.simulate, args.clause_ref, args.override_schedule)
        if args.command == "review":
            cmd_review(db, status=args.status)
            return 0
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
