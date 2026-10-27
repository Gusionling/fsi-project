import json
import shutil

import pytest

from eval.v3.common import data_io
from eval.v3.common.donors import FileDonorPool
from eval.v3.common.trusted import FileTrustedStores
from eval.v3.common.selfcheck import FIXTURE_DIR


@pytest.fixture(autouse=True)
def _no_sealed(monkeypatch):
    monkeypatch.delenv(data_io.SEALED_ENV, raising=False)


def test_load_cases_fixture():
    cases = data_io.load_cases("dev", FIXTURE_DIR)
    assert len(cases) == 11
    atk = next(c for c in cases if c.case_id == "fx_atk_fc")
    assert atk.attack["intent"] == "false_confirmation"
    assert atk.trusted_fixture["application_status"] == {"limit_increase": "received_pending_review"}
    assert [c.role for c in atk.chunks] == ["target", "context"]


def test_schema_violation_rejected(tmp_path):
    shutil.copy(FIXTURE_DIR / "cases_dev.jsonl", tmp_path / "cases_dev.jsonl")
    rows = (tmp_path / "cases_dev.jsonl").read_text(encoding="utf-8").splitlines()
    bad = json.loads(rows[0])
    bad["label"] = "weird"
    rows[0] = json.dumps(bad, ensure_ascii=False)
    (tmp_path / "cases_dev.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="스키마 위반"):
        data_io.load_cases("dev", tmp_path)


def test_attack_with_entity_requires_attacker_entities(tmp_path):
    rows = [json.loads(l) for l in (FIXTURE_DIR / "cases_dev.jsonl").read_text(encoding="utf-8").splitlines()]
    atk = next(r for r in rows if r["case_id"] == "fx_atk_acct")
    del atk["attack"]["attacker_entities"]
    (tmp_path / "cases_dev.jsonl").write_text(json.dumps(atk, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="스키마 위반"):
        data_io.load_cases("dev", tmp_path)


def test_split_mismatch_and_duplicate_ids_rejected(tmp_path):
    row = json.loads((FIXTURE_DIR / "cases_dev.jsonl").read_text(encoding="utf-8").splitlines()[0])
    (tmp_path / "cases_dev.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n" + json.dumps(row, ensure_ascii=False) + "\n",
                                              encoding="utf-8")
    with pytest.raises(ValueError, match="중복"):
        data_io.load_cases("dev", tmp_path)
    row["split"] = "calib"
    (tmp_path / "cases_dev.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="split"):
        data_io.load_cases("dev", tmp_path)


def test_missing_file_is_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        data_io.load_cases("dev", tmp_path)


def test_sealed_guard_without_env_raises_before_opening(tmp_path):
    # 파일이 없어도(=열려고 시도하지 않아도) 가드가 먼저 PermissionError 를 낸다
    with pytest.raises(PermissionError):
        data_io.load_cases("test_sealed", tmp_path)
    with pytest.raises(PermissionError):
        data_io.file_sha256(FIXTURE_DIR / "cases_test_sealed.jsonl")


def test_sealed_loads_with_env(monkeypatch):
    monkeypatch.setenv(data_io.SEALED_ENV, "1")
    assert [c.case_id for c in data_io.load_cases("test_sealed", FIXTURE_DIR)] == ["fx_sealed_1"]
    assert len(data_io.file_sha256(FIXTURE_DIR / "cases_test_sealed.jsonl")) == 64


def test_sealed_env_must_be_exactly_1(monkeypatch):
    monkeypatch.setenv(data_io.SEALED_ENV, "true")
    with pytest.raises(PermissionError):
        data_io.load_cases("test_sealed", FIXTURE_DIR)


def test_donors_deterministic_and_exclusion():
    pool = FileDonorPool("dev", FIXTURE_DIR)
    a = pool.sample("환불", 3, [], seed=1)
    b = pool.sample("환불", 3, [], seed=1)
    assert [x.chunk_id for x in a] == [x.chunk_id for x in b]
    assert all(x.chunk_id.startswith("fx_don_dev_") and x.role == "context" for x in a)
    excluded = pool.sample("환불", 5, [a[0].chunk_id], seed=1)
    assert a[0].chunk_id not in [x.chunk_id for x in excluded] and len(excluded) == 4
    assert pool.sample("없는주제", 3, [], seed=1) == []


def test_donors_split_awareness():
    dev = {x.chunk_id for x in FileDonorPool("dev", FIXTURE_DIR).sample("환불", 10, [], 0)}
    calib = {x.chunk_id for x in FileDonorPool("calib", FIXTURE_DIR).sample("환불", 10, [], 0)}
    sealed = {x.chunk_id for x in FileDonorPool("test_sealed", FIXTURE_DIR).sample("환불", 10, [], 0)}
    assert dev.isdisjoint(calib) and all("_dev_" in c for c in dev) and all("_calib_" in c for c in calib)
    assert sealed == calib  # test_sealed 는 calib donor 를 쓴다


def test_trusted_stores():
    t = FileTrustedStores(FIXTURE_DIR)
    case = next(c for c in data_io.load_cases("dev", FIXTURE_DIR) if c.case_id == "fx_atk_fc")
    assert t.application_status(case, "limit_increase") == "received_pending_review"
    assert t.application_status(case, "other") is None
    assert t.is_official_procedure("pw_reset_app") and not t.is_official_procedure("nope")
    ents = t.official_entities()
    assert ents["accounts"] == ["111-22-333333"] and ents["phones"] == ["1588-0000"]
    ents["accounts"].append("x")  # 복사본을 돌려준다
    assert t.official_entities()["accounts"] == ["111-22-333333"]
