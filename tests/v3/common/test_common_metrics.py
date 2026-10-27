import math

import pytest

from eval.v3.common import metrics as M


def test_clopper_pearson_known_values():
    assert M.clopper_pearson_upper(3, 130) == pytest.approx(0.0586, abs=5e-4)
    assert M.clopper_pearson_upper(0, 59) <= 0.05
    assert M.clopper_pearson_upper(0, 58) > 0.05  # 59 가 0 오탐으로 인증되는 최소 n
    assert M.clopper_pearson_upper(130, 130) == 1.0
    assert M.clopper_pearson_upper(0, 130) == pytest.approx(0.0228, abs=5e-4)  # IDEAS §11.2 표


@pytest.mark.parametrize("n,expected", [(130, 2), (200, 4), (300, 8), (400, 12), (500, 16)])
def test_certifiable_max_errors(n, expected):
    assert M.certifiable_max_errors(n) == expected


def test_certifiable_max_errors_too_small_n():
    assert M.certifiable_max_errors(10) == -1  # 오탐 0건이어도 5% 이하를 인증할 수 없다


def test_min_p_value():
    assert M.min_p_value(19) == pytest.approx(0.05)
    assert M.min_p_value(199) == pytest.approx(0.005)


def test_split_conformal_pvalue():
    calib = [1.0, 2.0, 3.0, 4.0]
    assert M.split_conformal_pvalue(calib, 3.0) == pytest.approx((1 + 2) / 5)  # 3, 4 가 >= 3
    assert M.split_conformal_pvalue(calib, 10.0) == pytest.approx(1 / 5)  # 하한 = 1/(m+1)
    assert M.split_conformal_pvalue(calib, 0.0) == pytest.approx(1.0)


def test_calibrated_threshold():
    assert M.calibrated_threshold([1.0] * 5) is None  # m=5: min_p=1/6 > 0.05
    calib = list(range(19))  # m=19: min_p = 0.05, 어떤 점수보다 커야 p=0.05
    t = M.calibrated_threshold([float(c) for c in calib])
    assert t == float("inf")
    calib = [float(c) for c in range(100)]  # m=100: #{>=t} <= 0.05*101-1 = 4.05 → t=96
    t = M.calibrated_threshold(calib)
    assert t == 96.0
    assert M.split_conformal_pvalue(calib, t) <= 0.05 < M.split_conformal_pvalue(calib, 95.0)


def test_wilson_known_values():
    lo, hi = M.wilson_interval(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = M.wilson_interval(5, 10)
    assert (lo, hi) == (pytest.approx(0.2366, abs=1e-3), pytest.approx(0.7634, abs=1e-3))
    lo, hi = M.wilson_interval(10, 10)
    assert hi == pytest.approx(1.0) and lo == pytest.approx(0.7225, abs=1e-3)
    assert all(math.isnan(v) for v in M.wilson_interval(0, 0))


def test_rate_dict_empty_is_json_safe():
    d = M.rate_dict(0, 0)
    assert d["rate"] is None and d["wilson_lo"] is None


def test_roc_auc():
    assert M.roc_auc([3, 4], [1, 2]) == 1.0
    assert M.roc_auc([1, 2], [3, 4]) == 0.0
    assert M.roc_auc([1, 1], [1, 1]) == 0.5  # 동점은 0.5
    assert M.roc_auc([2, 3], [1, 2]) == pytest.approx((1 + 1 + 0.5 + 1) / 4)
    assert math.isnan(M.roc_auc([], [1]))


def test_paired_bootstrap_is_deterministic():
    a = [1, 1, 1, 0, 1, 0, 1, 1, 0, 1]
    b = [0, 1, 0, 0, 1, 0, 0, 1, 0, 0]
    r1 = M.paired_bootstrap(a, b, n_boot=2000, seed=7)
    r2 = M.paired_bootstrap(a, b, n_boot=2000, seed=7)
    assert r1 == r2
    assert r1["diff"] == pytest.approx(0.4)
    assert r1["lo"] <= r1["diff"] <= r1["hi"]
    assert r1["n_boot"] == 2000


def test_paired_bootstrap_identical_has_zero_width():
    r = M.paired_bootstrap([1, 0, 1], [1, 0, 1], n_boot=500)
    assert r["diff"] == 0 and r["lo"] == 0 and r["hi"] == 0


def test_paired_bootstrap_length_mismatch():
    with pytest.raises(ValueError):
        M.paired_bootstrap([1, 0], [1])
