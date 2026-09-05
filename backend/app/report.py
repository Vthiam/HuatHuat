"""Renders a plain-language Markdown report for a scan or check-sso run,
saved into law_library/reports/ with a timestamped filename so history
accumulates rather than being overwritten on each run.
"""
import datetime
from pathlib import Path
from typing import Dict, List

from .config import REPORTS_DIR
from .library_scanner import InboxScanResult, TemplateScanResult
from .models import ChangeEvent, Flag


def _timestamp() -> str:
    return datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def write_scan_report(inbox_result: InboxScanResult, template_result: TemplateScanResult) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = _timestamp()
    lines = ["# Library Scan Report", f"Generated: {ts}", ""]

    lines.append("## Classified from inbox/")
    if inbox_result.classified:
        for c in inbox_result.classified:
            note = " -- **needs confirmation**" if c.needs_confirmation else ""
            lines.append(
                f"- {c.document.name} -> {c.document.genre.value} "
                f"({c.confidence:.0%} confidence, {c.document.classification_source.value}){note}"
            )
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## New templates registered")
    if template_result.new_documents:
        for d in template_result.new_documents:
            lines.append(f"- {d.name}")
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Dependencies detected")
    if template_result.edges_created:
        for e in template_result.edges_created:
            if e.to_clause_id:
                target = f"clause {e.to_clause.clause_ref} of {e.to_document.name}"
            else:
                target = e.to_document.name
            lines.append(f'- {e.from_document.name} depends on {target}: "{e.excerpt}"')
    else:
        lines.append("- (none)")
    lines.append("")

    if template_result.needs_confirmation:
        lines.append("## Needs confirmation (low-confidence classification)")
        for d in template_result.needs_confirmation:
            lines.append(f"- {d.name} ({d.classification_confidence:.0%} confidence)")
        lines.append("")

    path = REPORTS_DIR / f"{ts}_scan_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_check_report(
    change_events: List[ChangeEvent], flags: List[Flag], highlighted_pdfs: Dict[int, Path]
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = _timestamp()
    lines = ["# Statute Check Report", f"Generated: {ts}", ""]

    lines.append("## Changes detected")
    if change_events:
        for e in change_events:
            clause = e.clause
            lines.append(f"### Section {clause.clause_ref} ({clause.heading or ''}) -- source: {e.source.value}")
            lines.append(f"- OLD: {e.old_text[:300]}")
            lines.append(f"- NEW: {e.new_text[:300]}")
            if e.legal_effect_summary:
                lines.append(f"- Summary ({e.summary_source.value}): {e.legal_effect_summary}")
            lines.append("")
    else:
        lines.append("- (no changes detected)")
        lines.append("")

    lines.append("## Flags raised")
    if flags:
        for f in flags:
            lines.append(f"### {f.document.name} ({f.flag_type.value}, depth={f.depth})")
            lines.append(f"- {f.recommendation_text}")
            pdf_path = highlighted_pdfs.get(f.id)
            if pdf_path:
                lines.append(f"- Highlighted PDF: `{pdf_path}`")
            lines.append("")
    else:
        lines.append("- (no documents affected)")
        lines.append("")

    path = REPORTS_DIR / f"{ts}_check_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
