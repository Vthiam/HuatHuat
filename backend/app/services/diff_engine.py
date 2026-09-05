"""Word-level diff between an old and new clause text.

Produces a list of ops so a redline can show both insertions and
deletions -- the product spec is explicit that deletions must be visible,
not just additions. `difflib.SequenceMatcher` naturally gives us both.
"""
import difflib
from dataclasses import dataclass
from typing import List


@dataclass
class DiffOp:
    op: str  # 'equal' | 'insert' | 'delete'
    text: str


def word_diff(old_text: str, new_text: str) -> List[DiffOp]:
    old_words = old_text.split(" ")
    new_words = new_text.split(" ")
    matcher = difflib.SequenceMatcher(a=old_words, b=new_words, autojunk=False)

    ops: List[DiffOp] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            ops.append(DiffOp("equal", " ".join(old_words[i1:i2])))
        elif tag == "delete":
            ops.append(DiffOp("delete", " ".join(old_words[i1:i2])))
        elif tag == "insert":
            ops.append(DiffOp("insert", " ".join(new_words[j1:j2])))
        elif tag == "replace":
            ops.append(DiffOp("delete", " ".join(old_words[i1:i2])))
            ops.append(DiffOp("insert", " ".join(new_words[j1:j2])))
    return ops


def has_changed(old_text: str, new_text: str) -> bool:
    return old_text.strip() != new_text.strip()
