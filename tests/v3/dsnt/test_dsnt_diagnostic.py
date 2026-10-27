import csv
import json
from dataclasses import replace
import pytest
from eval.v3.candidates.dsnt.diagnostic import auroc, diagnose
from dsnt_stubs import case


def record(case_id, s=None, p=None, blocked=False):
    return {"case_id": case_id, "flags": {"s": s, "p": p, "m": 19, "donors_k": 5, "dist_kind": "edit", "alpha": .05},
            "scores": {"risk": 1 - p} if p is not None else {}, "blocked": blocked}


def test_diagnostic_real_records_only_and_missing_scores_not_zero(tmp_path):
    cases = [case("n1"), case("n2"), replace(case("a", label="attack"), normal=None, attack={"tier": "T2", "has_entity": False})]
    records = [record("n1", .1, .8), record("n2", blocked=True), record("a", .9, .05, True)]
    summary = diagnose(records, cases, tmp_path)
    group = summary["groups"]["all"]
    assert group["n_unscored"] == 1
    assert group["auroc_hard_negative_vs_attack"]["T2"]["auroc"] == 1
    assert group["dsnt_fpr_at_alpha_scored_normal_only"]["n"] == 1
    assert group["pipeline_normal_intervention_rate"]["rate"] == .5
    assert "author_model:stub" in summary["groups"]
    with (tmp_path / "score_distribution.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3 and rows[1]["s"] == ""
    assert json.loads((tmp_path / "diagnostic.json").read_text()) == summary


def test_auroc_ties_and_empty_groups():
    assert auroc([1], [1]) == .5
    assert auroc([2], [1]) == 0
    assert auroc([], [1]) is None


def test_diagnostic_refuses_id_mismatch_sealed_and_mixed_settings(tmp_path):
    with pytest.raises(ValueError):
        diagnose([], [case()], tmp_path)
    with pytest.raises(ValueError):
        diagnose([record("s")], [case("s", split="test_sealed")], tmp_path)
    r = record("b", .2, .4)
    r["flags"]["donors_k"] = 10
    with pytest.raises(ValueError):
        diagnose([record("a", .1, .5), r], [case("a"), case("b")], tmp_path)
