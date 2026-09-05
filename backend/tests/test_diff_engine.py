from app.services.diff_engine import has_changed, word_diff


def test_identical_text_has_no_changes():
    assert has_changed("the quick fox", "the quick fox") is False
    ops = word_diff("the quick fox", "the quick fox")
    assert all(op.op == "equal" for op in ops)


def test_insertion_is_detected():
    ops = word_diff("the fox jumps", "the quick fox jumps")
    inserted = " ".join(op.text for op in ops if op.op == "insert")
    assert "quick" in inserted


def test_deletion_is_detected():
    ops = word_diff("the quick fox jumps", "the fox jumps")
    deleted = " ".join(op.text for op in ops if op.op == "delete")
    assert "quick" in deleted


def test_replace_produces_both_delete_and_insert():
    ops = word_diff("Parts III to VI", "Parts 3, 4, 5 and 6")
    ops_types = {op.op for op in ops}
    assert "delete" in ops_types
    assert "insert" in ops_types


def test_real_pdpa_amendment_shows_both_directions():
    old = "Parts III to VI shall not impose any obligation on an individual."
    new = "Parts 3, 4, 5, 6, 6A and 6B do not impose any obligation on an individual."
    ops = word_diff(old, new)
    assert any(op.op == "delete" for op in ops)
    assert any(op.op == "insert" for op in ops)
