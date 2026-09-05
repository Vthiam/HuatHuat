"""AI reasoning for the impact pipeline: summarizing what a statute change
means in plain English, and drafting a per-document "here's how this
might affect you" suggestion.

This is deliberately where an LLM belongs, unlike sso_client/diff_engine
(mechanical, exact-match, no LLM) -- both of these are genuine judgment
calls with no single correct answer. Uses OpenAI when OPENAI_API_KEY is
set, always falls back to a free, deterministic heuristic otherwise, and
every result is tagged with `source` so the UI/report can show which path
produced it.

Own file, separate from feature/ingestion-citations' classifier.py, even
though both call OpenAI with the same claude-or-fallback shape -- avoids
two branches editing the same file.

Every recommendation is phrased as a suggestion for a human to evaluate,
never a directive or a conclusion -- and this module never writes to a
document's own content. It only ever returns text for a caller to store.
"""
from typing import List, Optional, Tuple

from ..config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from ..models import ReasoningSource
from .diff_engine import word_diff

_client = None
if OPENAI_API_KEY:
    import openai

    _client = openai.OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL, timeout=20.0, max_retries=1)

_IS_OPENROUTER = bool(OPENAI_BASE_URL) and "openrouter" in OPENAI_BASE_URL


def _call_openai(system: str, user: str, max_tokens: int = 300) -> Optional[str]:
    if _client is None:
        return None
    try:
        kwargs = {}
        if _IS_OPENROUTER:
            # This model does chain-of-thought before answering (visible as
            # `reasoning_tokens` in the response, separate from the final
            # `content`). Without this, it can spend the entire max_tokens
            # budget thinking and return empty content -- a failed call that
            # still burns tokens for zero output. "low" effort is the
            # cheapest setting that still reliably leaves room to answer.
            kwargs["extra_body"] = {"reasoning": {"effort": "low"}}
        resp = _client.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kwargs,
        )
        content = resp.choices[0].message.content
        return content.strip() if content else None
    except Exception:
        # Any API failure (bad key, rate limit, network) falls back rather
        # than breaking the pipeline -- resilience applies to our own tool too.
        return None


def summarize_change(clause_ref: str, heading: str, old_text: str, new_text: str) -> Tuple[str, ReasoningSource]:
    result = _call_openai(
        system=(
            "Legal-tech assistant. Compare OLD vs NEW statute text below word by word. "
            "Base your answer only on the exact wording given -- do not use outside legal "
            "knowledge or invent context. In 2-3 plain-English sentences, state what changed "
            "and why it might matter in practice. Describe the change only, no legal conclusion."
        ),
        user=f"Section {clause_ref} ({heading}) changed.\n\nOLD:\n{old_text}\n\nNEW:\n{new_text}",
        max_tokens=700,
    )
    if result:
        return result, ReasoningSource.OPENAI

    ops = word_diff(old_text, new_text)
    inserted = " / ".join(o.text for o in ops if o.op == "insert" and o.text.strip())
    deleted = " / ".join(o.text for o in ops if o.op == "delete" and o.text.strip())
    parts = [f"Section {clause_ref} ({heading}) text changed."]
    if deleted:
        parts.append(f'Removed: "{deleted[:200]}".')
    if inserted:
        parts.append(f'Added: "{inserted[:200]}".')
    return " ".join(parts), ReasoningSource.HEURISTIC


def recommend_impact(
    document_name: str,
    document_text: str,
    document_excerpt: str,
    clause_ref: str,
    old_clause_text: str,
    new_clause_text: str,
    dependency_path: List[str],
) -> Tuple[str, ReasoningSource]:
    """document_text is the document's FULL content (not just the short
    citation excerpt) so the model can genuinely scan the whole document
    for passages that conflict with the new statute text, not just check
    the one sentence that triggered the dependency edge. document_excerpt
    is kept only for the heuristic fallback, which can't do that kind of
    scan."""
    path_desc = " -> ".join(dependency_path) if len(dependency_path) > 1 else None

    result = _call_openai(
        system=(
            "Legal-tech assistant. Given OLD statute text, NEW (amended) statute text, and a "
            "firm document's full text: find inconsistencies between what the document assumes "
            "(the OLD text) and the NEW text. Quote the exact conflicting sentence(s) from the "
            "document and explain why each conflicts with the NEW text. Base this only on the "
            "text given -- no outside legal knowledge, no invented provisions. If the document "
            "doesn't actually rely on the changed part, say so plainly. Write ~150 words. This "
            "is a suggestion for a human lawyer to evaluate, never an instruction to edit."
        ),
        user=(
            f"OLD statute text (what the document was written against):\n{old_clause_text}\n\n"
            f"NEW statute text (current law):\n{new_clause_text}\n\n"
            f"Firm document '{document_name}' full text:\n{document_text[:2000]}\n\n"
            + (f"Note: this document is affected indirectly, via: {path_desc}\n" if path_desc else "")
        ),
        max_tokens=900,
    )
    if result:
        return result, ReasoningSource.OPENAI

    # The heuristic fallback cannot scan a document for conflicting
    # passages -- that requires actual reasoning. It stays honest about
    # that limit rather than pretending to do the analysis above. Uses the
    # actual diff ops (what was added/removed), not a naive first-N-chars
    # truncation of old vs new -- a change near the end of a long clause
    # (e.g. an appended sentence) would otherwise make truncated old/new
    # text look identical and say nothing useful.
    ops = word_diff(old_clause_text, new_clause_text)
    inserted = " / ".join(o.text for o in ops if o.op == "insert" and o.text.strip())
    deleted = " / ".join(o.text for o in ops if o.op == "delete" and o.text.strip())
    change_desc_parts = []
    if deleted:
        change_desc_parts.append(f'removed "{deleted[:150]}"')
    if inserted:
        change_desc_parts.append(f'added "{inserted[:150]}"')
    change_desc = " and ".join(change_desc_parts) if change_desc_parts else "text changed"

    if path_desc:
        text = (
            f"'{document_name}' depends on this change indirectly via {path_desc}. "
            f"Section {clause_ref} changed: {change_desc}. Automated passage-level comparison "
            f"requires an API key; manual review of '{document_name}' is recommended."
        )
    else:
        text = (
            f"'{document_name}' cites section {clause_ref}, which changed: {change_desc}. "
            f'The cited excerpt was: "{document_excerpt[:150]}". Automated passage-level '
            f"comparison requires an API key; manual review of '{document_name}' is recommended."
        )
    return text, ReasoningSource.HEURISTIC
