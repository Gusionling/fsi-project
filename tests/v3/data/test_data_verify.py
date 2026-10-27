import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import json

import pytest

from data_fixtures import full_dataset, write_data
from eval.v3.data import data_lib as D
from eval.v3.data import verify_counts as V


@pytest.fixture()
def dataset():
    return full_dataset()


def write_manifest(tmp, sealed):
    from collections import Counter
    path = tmp / D.CASE_FILES["test_sealed"]
    hn = Counter(r["normal"]["hard_negative_type"] for r in sealed)
    D.write_json(tmp / D.SEALED_MANIFEST, {"n": len(sealed), "labels": {"normal": len(sealed)}, "hn": dict(hn), "size_bytes": path.stat().st_size})


def test_full_dataset_meets_contract(tmp_path, dataset, monkeypatch):
    dev, calib, sealed, donors = dataset
    write_data(tmp_path, dev, calib, donors, sealed)
    write_manifest(tmp_path, sealed)
    monkeypatch.delenv("V3_ALLOW_SEALED", raising=False)
    rep = V.check(tmp_path)
    assert rep.ok, [r for r in rep.rows if not r[3]]
    assert any("manifest" in r[0] for r in rep.rows)  # sealed 는 열지 않고 manifest 로 확인


def test_sealed_checked_from_file_when_allowed(tmp_path, dataset, monkeypatch):
    dev, calib, sealed, donors = dataset
    write_data(tmp_path, dev, calib, donors, sealed)
    monkeypatch.setenv("V3_ALLOW_SEALED", "1")
    rep = V.check(tmp_path)
    assert rep.ok and any("(file)" in r[0] for r in rep.rows)


def test_manifest_size_mismatch_is_failure(tmp_path, dataset, monkeypatch):
    dev, calib, sealed, donors = dataset
    write_data(tmp_path, dev, calib, donors, sealed)
    write_manifest(tmp_path, sealed)
    with open(tmp_path / D.CASE_FILES["test_sealed"], "a") as f:
        f.write("\n")
    monkeypatch.delenv("V3_ALLOW_SEALED", raising=False)
    assert not V.check(tmp_path).ok


@pytest.mark.parametrize("mutate,expected", [
    (lambda d, c, s, dn: d.pop(0) and None, "dev 공격"),                                  # 공격 하나 제거
    (lambda d, c, s, dn: [r.update(author_model="gpt-4o-mini") for r in d if r["label"] == "attack"], "직접 쓴 비율"),
    (lambda d, c, s, dn: [r["attack"].pop("clean_twin_case_id", None) for r in d if r["label"] == "attack"], "짝 케이스"),
    (lambda d, c, s, dn: dn.pop(), "donors"),
    (lambda d, c, s, dn: c.pop(), "calib 정상"),
])
def test_shortfall_is_detected(tmp_path, dataset, monkeypatch, mutate, expected):
    dev, calib, sealed, donors = dataset
    mutate(dev, calib, sealed, donors)
    write_data(tmp_path, dev, calib, donors, sealed)
    write_manifest(tmp_path, sealed)
    monkeypatch.delenv("V3_ALLOW_SEALED", raising=False)
    rep = V.check(tmp_path)
    assert not rep.ok and any(expected in r[0] and not r[3] for r in rep.rows), [r for r in rep.rows if not r[3]]


def test_missing_sealed_fails(tmp_path, dataset, monkeypatch):
    dev, calib, _, donors = dataset
    write_data(tmp_path, dev, calib, donors, None)
    monkeypatch.delenv("V3_ALLOW_SEALED", raising=False)
    assert not V.check(tmp_path).ok
