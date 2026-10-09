"""c2_extract.py의 프롬프트 해시 검증 단위 테스트. API 호출 없음."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import eval.mech_search.c2_extract as c2_extract  # noqa: E402
from eval.mech_search.c2_extract import load_extract_prompt, PromptHashMismatch, actual_prompt_hash  # noqa: E402


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
