import pytest

from eval.v3.common import metrics as M

E = ["a1", "a2", "a3", "a4"]


def test_denominator_is_fixed_to_E_even_when_defense_refuses_a_lot():
    # 방어가 E 밖의 공격 케이스까지 잔뜩 거부해도(extra 키) 분모는 |E| = 4 이다
    intervened = {"a1": True, "a2": True, "a3": False, "a4": False, **{f"x{i}": True for i in range(100)}}
    r = M.executed_recall(intervened, E)
    assert (r["k"], r["n"]) == (2, 4)
    assert r["rate"] == 0.5


def test_all_refused_and_none_refused():
    assert M.executed_recall({c: True for c in E}, E)["rate"] == 1.0
    assert M.executed_recall({c: False for c in E}, E)["rate"] == 0.0


def test_missing_case_in_E_is_an_error_not_a_smaller_denominator():
    with pytest.raises(ValueError):
        M.executed_recall({"a1": True, "a2": True}, E)


def test_asr_after_uses_same_denominator():
    r = M.asr_after({"a1": False, "a2": True, "a3": True, "a4": False, "zz": True}, E)
    assert (r["k"], r["n"]) == (2, 4)


def test_fpr_with_cp_upper():
    d = M.fpr([True] * 3 + [False] * 127)
    assert (d["k"], d["n"]) == (3, 130)
    assert d["cp_upper95"] == pytest.approx(0.0586, abs=5e-4)
    assert d["certifiable_max_errors_at_5pct"] == 2
