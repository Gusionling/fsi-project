"""c2_extract.py의 프롬프트 해시 검증 단위 테스트. API 호출 없음."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import eval.mech_search.c2_extract as c2_extract  # noqa: E402
from eval.mech_search.c2_extract import (  # noqa: E402
    load_extract_prompt,
    PromptHashMismatch,
    actual_prompt_hash,
    ModelRun,
    ModelDriftError,
)


def test_prompt_file_hash_matches_registered_value():
    """실제 파일의 해시가 문서(§1.2)에 기재된 값과 같아야 한다 — 다르면 이 테스트가 먼저 잡는다."""
    assert actual_prompt_hash() == c2_extract.EXPECTED_PROMPT_HASH


def test_load_extract_prompt_returns_text_when_hash_matches():
    text = load_extract_prompt(verify=True)
    assert "{response}" in text
    assert len(text) > 0


def test_load_extract_prompt_raises_on_hash_mismatch(monkeypatch):
    """해시가 기대값과 다르면 API 호출 전에 PromptHashMismatch로 중단해야 한다."""
    monkeypatch.setattr(c2_extract, "EXPECTED_PROMPT_HASH", "0" * 64)
    try:
        load_extract_prompt(verify=True)
        assert False, "해시가 다른데 예외가 발생하지 않았다"
    except PromptHashMismatch:
        pass


def test_load_extract_prompt_skips_verification_when_disabled():
    """verify=False면 해시를 확인하지 않고 그대로 반환한다(디버깅용, 기본값 아님)."""
    text = load_extract_prompt(verify=False)
    assert len(text) > 0


def test_model_run_accepts_repeated_same_model():
    """같은 실제 모델명이 반복되면 드리프트가 아니다 — API 없이 문자열만으로 검증."""
    run = ModelRun(expected_model="gpt-4.1-mini")
    for _ in range(5):
        run.record("gpt-4.1-mini-2026-01-01")  # alias 뒤 실제 응답이 돌려주는 값 예시
    assert run.seen_models == ["gpt-4.1-mini-2026-01-01"] * 5


def test_model_run_raises_on_drift():
    """실행 중 실제 모델명이 바뀌면 ModelDriftError로 그 실행 전체를 무효 처리한다."""
    run = ModelRun(expected_model="gpt-4.1-mini")
    run.record("gpt-4.1-mini-2026-01-01")
    try:
        run.record("gpt-4.1-mini-2026-02-15")
        assert False, "모델명이 바뀌었는데 예외가 발생하지 않았다"
    except ModelDriftError:
        pass


def test_model_run_first_call_never_drifts():
    """첫 호출은 비교 대상이 없으므로 어떤 값이 와도 드리프트가 아니다."""
    run = ModelRun(expected_model="o4-mini")
    run.record("o4-mini-2026-03-01")
    assert run.seen_models == ["o4-mini-2026-03-01"]


def test_model_constants_do_not_overlap():
    """1차·2차·판정제외(보조) 모델은 서로 달라야 한다 — §8 역할 분리가 코드에서도 지켜지는지."""
    assert c2_extract.PRIMARY_MODEL != c2_extract.SECONDARY_MODEL
    assert c2_extract.PRIMARY_MODEL != c2_extract.EXCLUDED_AUX_MODEL
    assert c2_extract.SECONDARY_MODEL != c2_extract.EXCLUDED_AUX_MODEL
