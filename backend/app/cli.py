"""The actual entry point tying every branch together.

    python -m app.cli scan
    python -m app.cli check-sso --live [--override-schedule]
    python -m app.cli check-sso --simulate --clause-ref 4
    python -m app.cli review [--status pending]

Each subcommand is backed by a plain function (cmd_scan, cmd_check_sso,
cmd_review) that returns a structured result rather than only printing --
feature/api-ui's routers call these exact same functions, so the API and
the CLI share one orchestration path instead of duplicating it.
"""
import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from . import impact_service, library_scanner, notifier, report, statute_sync
from .config import TRACKED_ACTS
from .db import Base, SessionLocal, engine
from .library_scanner import InboxScanResult, TemplateScanResult
from .models import ChangeEvent, DependencyEdge, Flag, FlagStatus
from .services import document_editor
from .services.docx_commenter import add_comment_to_docx
from .services.pdf_highlighter import highlight_flag_in_pdf
from .services.sso_client import should_run_now


@dataclass
class ScanCommandResult:
    inbox_result: InboxScanResult
    template_result: TemplateScanResult
    report_path: Path


def cmd_scan(db) -> ScanCommandResult:
    inbox_result = library_scanner.scan_inbox(db)
    template_result = library_scanner.scan_templates(db)
    report_path = report.write_scan_report(inbox_result, template_result)

    print(f"Classified {len(inbox_result.classified)} document(s) from inbox/")
    for c in inbox_result.classified:
        note = " [NEEDS CONFIRMATION]" if c.needs_confirmation else ""
        print(f"  - {c.document.name} -> {c.document.genre.value} ({c.confidence:.0%}){note}")

    print(f"Registered {len(template_result.new_documents)} new template(s)")
    print(f"Detected {len(template_result.edges_created)} new dependency edge(s)")
    print(f"Report written to {report_path}")

    return ScanCommandResult(inbox_result, template_result, report_path)


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


@dataclass
class CheckSsoCommandResult:
    ok: bool
    message: Optional[str] = None  # set when ok=False, explains the refusal
    change_events: List[ChangeEvent] = field(default_factory=list)
    flags: List[Flag] = field(default_factory=list)
    highlighted_pdfs: Dict[int, Path] = field(default_factory=dict)
    commented_docs: Dict[int, Path] = field(default_factory=dict)
    report_path: Optional[Path] = None


def cmd_check_sso(
    db, live: bool, simulate: bool, clause_ref: Optional[str], override_schedule: bool
) -> CheckSsoCommandResult:
    if live == simulate:
        message = "Specify exactly one of --live or --simulate"
        print(message)
        return CheckSsoCommandResult(ok=False, message=message)

    if live and not override_schedule and not should_run_now():
        message = (
            "Refusing to run a live SSO check outside the permitted automated-extraction "
            "window (3am-7am Singapore time, per SSO Terms of Use clause 13(d)). "
            "Pass --override-schedule to run anyway as a deliberate manual/demo override."
        )
        print(message)
        return CheckSsoCommandResult(ok=False, message=message)

    if simulate and not clause_ref:
        message = "--simulate requires --clause-ref"
        print(message)
        return CheckSsoCommandResult(ok=False, message=message)

    all_events = []
    for act_config in TRACKED_ACTS:
        if live:
            events = statute_sync.sync_live(db, act_config)
        else:
            events = statute_sync.sync_simulated(db, act_config, clause_ref)
        all_events.extend(events)

    flags = impact_service.process_all(db, all_events)

    highlighted_pdfs: Dict[int, Path] = {}
    commented_docs: Dict[int, Path] = {}
    for flag in flags:
        # Prefer the AI's verified conflicting_sentence (the specific
        # sentence it identified inside this document) over the generic
        # dependency-edge excerpt when available -- it's a more precise
        # target for both the highlight and the comment anchor.
        target_text = flag.original_sentence or _excerpt_for_flag(db, flag)

        pdf_path = highlight_flag_in_pdf(flag.document, flag, target_text)
        if pdf_path is not None:
            highlighted_pdfs[flag.id] = pdf_path

        if flag.original_sentence:
            docx_path = add_comment_to_docx(flag.document, flag, flag.original_sentence)
            if docx_path is not None:
                commented_docs[flag.id] = docx_path

    report_path = report.write_check_report(all_events, flags, highlighted_pdfs)

    print(f"Detected {len(all_events)} statute change(s)")
    print(f"Raised {len(flags)} flag(s)")
    for pdf_path in highlighted_pdfs.values():
        print(f"  Highlighted PDF: {pdf_path}")
    for docx_path in commented_docs.values():
        print(f"  Commented DOCX: {docx_path}")
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

    return CheckSsoCommandResult(
        ok=True,
        change_events=all_events,
        flags=flags,
        highlighted_pdfs=highlighted_pdfs,
        commented_docs=commented_docs,
        report_path=report_path,
    )


def cmd_review(db, status: str = "pending", auto_answers: Optional[List[str]] = None) -> None:
    """auto_answers lets tests (and any future scripted use) drive this
    without real stdin: a list of 'a'/'r'/'s' consumed in order instead of
    calling input(). A reject can carry a self-edit as 'r:my replacement
    text' (used both by the scripted form and parsed the same way here);
    interactively, rejecting prompts for optional self-edit text instead."""
    flags = db.query(Flag).filter_by(status=FlagStatus(status)).order_by(Flag.created_at).all()
    if not flags:
        print(f"No flags with status={status}.")
        return

    answers: Optional[Iterator[str]] = iter(auto_answers) if auto_answers is not None else None

    for flag in flags:
        print(f"\n[{flag.id}] {flag.document.name} ({flag.flag_type.value})")
        print(f"  {flag.recommendation_text}")
        if flag.original_sentence:
            print(f'  Flagged sentence: "{flag.original_sentence}"')
        if flag.suggested_replacement:
            print(f'  AI suggests: "{flag.suggested_replacement}"')

        if answers is not None:
            answer = next(answers, "s")
        else:
            answer = input("  [a]ccept / [r]eject / [s]kip: ").strip()

        answer_lower = answer.lower()
        if answer_lower == "a":
            impact_service.resolve_flag_accept(db, flag)
            note = " (document edited)" if flag.document_edited else ""
            print(f"  -> accepted{note}")
        elif answer_lower.startswith("r"):
            human_text = None
            if ":" in answer:
                human_text = answer.split(":", 1)[1]
            elif answers is None and flag.original_sentence:
                typed = input(
                    f'  Reject noted. Type your own replacement for "{flag.original_sentence[:60]}..." '
                    "(or press Enter to skip editing): "
                ).strip()
                human_text = typed or None
            impact_service.resolve_flag_reject(db, flag, human_edit_text=human_text)
            note = " (your edit applied)" if flag.document_edited else ""
            print(f"  -> rejected{note}")
        else:
            continue


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
            result = cmd_check_sso(db, args.live, args.simulate, args.clause_ref, args.override_schedule)
            return 0 if result.ok else 1
        if args.command == "review":
            cmd_review(db, status=args.status)
            return 0
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
