import math
import pytest
from eval.v3.candidates.dsnt.skeleton import skeleton
from eval.v3.candidates.dsnt.distance import edit_distance, cosine_distance, distances
from eval.v3.candidates.dsnt.conformal import can_decide, minimum_p, p_value, InsufficientCalibrationWarning
from dsnt_stubs import context


@pytest.mark.parametrize("raw, expected", [
    ("값 123과 -4.5%", "값 [NUM]과 [NUM]%"),
    ("2026-11-30, 2026/1/2, 10월 3일", "[DATE], [DATE], [DATE]"),
    ("2026년 10월 3일", "[DATE]"),
    ("수수료 1,000원 / $20.5 / USD 30", "수수료 [MONEY] / [MONEY] / [MONEY]"),
    ("계좌 123-45-678901", "계좌 [ACCT]"),
    ("전화 010-1234-5678 / 02-123-4567 / 1588-1234", "전화 [PHONE] / [PHONE] / [PHONE]"),
    ("https://example.com/a?q=12", "[URL]"),
    ("example.test 안내", "[URL] 안내"),
    ("  수수료\n ５００원 ", "수수료 [MONEY]"),
])
def test_mask_rules(raw, expected):
    assert skeleton(raw) == expected


def test_official_entities_have_precedence_and_regex_escaping():
    assert skeleton("222-33-444444 https://official.test A+B", {"accounts": ["222-33-444444"], "urls": ["https://official.test"], "names": ["A+B"]}) == "[ENT] [ENT] [ENT]"


def test_value_only_attack_is_invisible_to_skeleton():
    assert skeleton("계좌 123-45-678901 입금") == skeleton("계좌 987-65-432109 입금")


@pytest.mark.parametrize("a,b,expected", [("", "", 0), ("a b", "a c", .5), ("a", "a b", .5), ("[NUM] 원", "[DATE] 원", .5), ("", "a", 1)])
def test_token_edit(a, b, expected):
    assert edit_distance(a, b) == expected
    assert edit_distance(b, a) == expected


@pytest.mark.parametrize("a,b,expected", [([1, 0], [1, 0], 0), ([1, 0], [0, 1], 1), ([1, 0], [-1, 0], 2)])
def test_cosine(a, b, expected):
    assert cosine_distance(a, b) == pytest.approx(expected)


@pytest.mark.parametrize("a,b", [([], []), ([0, 0], [1, 0]), ([1], [1, 2]), ([math.nan], [1])])
def test_invalid_vectors_are_not_silent(a, b):
    with pytest.raises(ValueError):
        cosine_distance(a, b)


def test_embedding_uses_context_and_batch():
    ctx = context()
    assert distances(["정상", "정상", "other"], "embed", ctx) == ([0, 1], 1)
    assert len(ctx.llm.calls) == 1


def test_conformal_formula_ties_and_boundary():
    assert p_value(2, [0, 1, 2, 2]) == 3 / 5
    assert p_value(3, [0, 1, 2, 2]) == 1 / 5
    assert p_value(0, [0, 1]) == 1
    assert minimum_p(19) == .05
    assert can_decide(19, .05)
    with pytest.warns(InsufficientCalibrationWarning):
        assert not can_decide(18, .05)
    with pytest.warns(InsufficientCalibrationWarning):
        assert not can_decide(0, .5)
    with pytest.raises(ValueError):
        p_value(float("nan"), [])
    with pytest.raises(ValueError):
        can_decide(20, 0)
