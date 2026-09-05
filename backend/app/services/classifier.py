"""Reads raw document text and figures out (a) what genre it is, and (b)
what it depends on -- this is the "AI agent" part of the pipeline: it
reads unstructured text and infers structure, rather than just storing
data someone already structured for it.

Uses OpenAI (this team's hackathon key) when OPENAI_API_KEY is set, always
falls back to free local heuristics otherwise. Every result is tagged with
`source` so callers/UI can show which path produced it. Deliberately its
own self-contained module (not a shared llm.py) so feature/graph-impact's
own AI-calling code never touches this file -- avoids a merge-conflict
hotspot between the two branches.

Cost note: this hackathon's OpenAI budget is a hard $15 cap. Prompts are
kept short and the heuristic path is what runs by default -- only flip on
a real key for spot-checks, not routine dev-loop runs.
"""
import json
import re
from dataclasses import dataclass
from typing import List, Optional

from ..config import OPENAI_API_KEY, OPENAI_MODEL
from ..models import DocumentGenre, ReasoningSource

_client = None
if OPENAI_API_KEY:
    import openai

    _client = openai.OpenAI(api_key=OPENAI_API_KEY)


@dataclass
class ClassificationResult:
    genre: DocumentGenre
    confidence: float
    source: ReasoningSource


@dataclass
class CitationMatch:
    target_type: str  # 'clause' | 'document'
    act_id: Optional[str]
    clause_ref: Optional[str]
    document_id: Optional[int]
    excerpt: str
    confidence: float
    source: ReasoningSource


# --- classification -----------------------------------------------------

_STATUTE_KEYWORDS = [
    "part i", "part 1", "part ii", "part 2",
    "an act to", "revised edition", "short title",
    "comes into operation", "in this act, unless the context",
]
_NUMBERED_SECTION_RE = re.compile(r"(?m)^\s*\d+\.\s+\S")


def _heuristic_classify(text: str) -> ClassificationResult:
    lower = text.lower()
    keyword_hits = sum(1 for kw in _STATUTE_KEYWORDS if kw in lower)
    numbered_sections = len(_NUMBERED_SECTION_RE.findall(text))

    if keyword_hits >= 1 or numbered_sections >= 3:
        confidence = min(0.55 + 0.12 * keyword_hits + 0.05 * numbered_sections, 0.95)
        return ClassificationResult(DocumentGenre.STATUTE, confidence, ReasoningSource.HEURISTIC)

    confidence = 0.65 if numbered_sections == 0 else 0.55
    return ClassificationResult(DocumentGenre.TEMPLATE, confidence, ReasoningSource.HEURISTIC)


def _call_openai_classify(text: str, filename: str) -> Optional[ClassificationResult]:
    if _client is None:
        return None
    try:
        resp = _client.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=50,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify a law firm's document as STATUTE (official legislation or "
                        "regulation text) or TEMPLATE (the firm's own checklist, workflow, or "
                        'advisory). Respond with strict JSON only: '
                        '{"genre": "STATUTE"|"TEMPLATE", "confidence": 0.0-1.0}'
                    ),
                },
                {"role": "user", "content": f"Filename: {filename}\n\n{text[:2000]}"},
            ],
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        genre = DocumentGenre.STATUTE if str(data["genre"]).upper() == "STATUTE" else DocumentGenre.TEMPLATE
        confidence = float(data["confidence"])
        return ClassificationResult(genre, confidence, ReasoningSource.OPENAI)
    except Exception:
        # Any API failure (bad key, rate limit, network, malformed JSON)
        # falls back rather than breaking ingestion.
        return None


def classify_document(text: str, filename: str = "") -> ClassificationResult:
    result = _call_openai_classify(text, filename)
    if result is not None:
        return result
    return _heuristic_classify(text)


# --- citation / dependency detection ------------------------------------

_SECTION_REF_RE = re.compile(r"\bs(?:ection)?s?\.?\s*(\d+[A-Za-z]?)\b", re.IGNORECASE)


def _act_aliases(act: dict) -> List[str]:
    """Names this Act might be referred to by in prose: its configured
    name, its act_id, and the act_id with trailing digits stripped (e.g.
    "PDPA2012" -> "PDPA", the acronym everyone actually types)."""
    aliases = [act["name"].lower(), act["act_id"].lower()]
    stripped = re.sub(r"\d+$", "", act["act_id"]).lower()
    if stripped and stripped not in aliases:
        aliases.append(stripped)
    return aliases


def _heuristic_detect_citations(text: str, tracked_acts: list, other_documents: list) -> List[CitationMatch]:
    matches: List[CitationMatch] = []
    lower_text = text.lower()

    for act in tracked_acts:
        if not any(alias in lower_text for alias in _act_aliases(act)):
            continue
        for m in _SECTION_REF_RE.finditer(text):
            clause_ref = m.group(1)
            if clause_ref not in act["clause_refs"]:
                continue
            start, end = max(0, m.start() - 60), min(len(text), m.end() + 60)
            matches.append(
                CitationMatch(
                    target_type="clause",
                    act_id=act["act_id"],
                    clause_ref=clause_ref,
                    document_id=None,
                    excerpt=text[start:end].strip(),
                    confidence=0.9,
                    source=ReasoningSource.HEURISTIC,
                )
            )

    for doc in other_documents:
        idx = lower_text.find(doc.name.lower())
        if idx == -1:
            continue
        start, end = max(0, idx - 40), min(len(text), idx + len(doc.name) + 40)
        matches.append(
            CitationMatch(
                target_type="document",
                act_id=None,
                clause_ref=None,
                document_id=doc.id,
                excerpt=text[start:end].strip(),
                confidence=0.85,
                source=ReasoningSource.HEURISTIC,
            )
        )

    return matches


def _call_openai_detect_citations(text: str, tracked_acts: list, other_documents: list) -> List[CitationMatch]:
    if _client is None:
        return []
    try:
        acts_desc = "\n".join(f"- {a['act_id']}: sections {', '.join(a['clause_refs'])}" for a in tracked_acts)
        docs_desc = "\n".join(f"- id={d.id}: {d.name}" for d in other_documents) or "(none)"
        resp = _client.chat.completions.create(
            model=OPENAI_MODEL,
            max_tokens=300,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Find places where this firm document relies on one of the listed statute "
                        "sections or other documents, even if not cited explicitly by number or name "
                        '(implicit reliance counts). Respond with strict JSON only: {"citations": '
                        '[{"type": "clause"|"document", "act_id": str|null, "clause_ref": str|null, '
                        '"document_id": int|null, "excerpt": str, "confidence": 0.0-1.0}]}. '
                        "Only include genuine matches; return an empty list if there are none."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Tracked statute sections:\n{acts_desc}\n\n"
                        f"Other documents in the library:\n{docs_desc}\n\n"
                        f"Document text:\n{text[:3000]}"
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        results = []
        for c in data.get("citations", []):
            if c.get("type") == "clause":
                results.append(
                    CitationMatch(
                        "clause", c.get("act_id"), c.get("clause_ref"), None,
                        c.get("excerpt", ""), float(c.get("confidence", 0.5)), ReasoningSource.OPENAI,
                    )
                )
            elif c.get("type") == "document" and c.get("document_id") is not None:
                results.append(
                    CitationMatch(
                        "document", None, None, int(c["document_id"]),
                        c.get("excerpt", ""), float(c.get("confidence", 0.5)), ReasoningSource.OPENAI,
                    )
                )
        return results
    except Exception:
        return []


def detect_citations(text: str, tracked_acts: list, other_documents: list) -> List[CitationMatch]:
    matches = _heuristic_detect_citations(text, tracked_acts, other_documents)
    matches += _call_openai_detect_citations(text, tracked_acts, other_documents)
    return _dedupe(matches)


def _match_key(m: CitationMatch):
    if m.target_type == "clause":
        return ("clause", m.act_id, m.clause_ref)
    return ("document", m.document_id)


def _dedupe(matches: List[CitationMatch]) -> List[CitationMatch]:
    best: dict = {}
    for m in matches:
        key = _match_key(m)
        if key not in best or m.confidence > best[key].confidence:
            best[key] = m
    return list(best.values())
