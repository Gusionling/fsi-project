"""C2 추출기 — 프롬프트 파일 로더 + 해시 검증.

추출 프롬프트는 eval/mech_search/c2_extract_prompt.txt 단일 파일에서 읽는다.
문서(docs/decision_protocol_v3.md §1.2)는 본문을 복사해 두지 않고 파일 경로와
바이트 기준 SHA-256만 적는다 — 본문과 해시가 따로 보관되다가 어긋나는 사고
(2026-10-10 erratum, §10)를 구조적으로 막기 위함이다.

실행(추출기 API 호출) 전에 반드시 load_extract_prompt()로 해시를 확인하고,
다르면 API 호출을 하지 않고 즉시 중단한다.
"""
import hashlib
from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parent / "c2_extract_prompt.txt"

# docs/decision_protocol_v3.md §1.2에 기재된 값과 반드시 같아야 한다. 이 상수와
# 파일이 어긋나면 프롬프트가 동결 시점과 달라졌다는 뜻이므로 API를 호출하지 않는다.
EXPECTED_PROMPT_HASH = "3ee5390c3789fc071d3ade061473e691f23d1d2f4ae4891ec94449892f4464e1"


class PromptHashMismatch(RuntimeError):
    """c2_extract_prompt.txt의 해시가 문서 기재값과 다를 때 발생시킨다 — API 호출 전 중단용."""


def actual_prompt_hash() -> str:
    return hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()


def load_extract_prompt(verify: bool = True) -> str:
    """프롬프트 텍스트를 반환한다. verify=True(기본)면 해시가 다르면 예외를 던진다."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    if verify:
        actual = actual_prompt_hash()
        if actual != EXPECTED_PROMPT_HASH:
            raise PromptHashMismatch(
                f"{PROMPT_PATH.name} 해시가 문서 기재값과 다르다 "
                f"(기대: {EXPECTED_PROMPT_HASH}, 실제: {actual}). API 호출 전에 중단한다."
            )
    return text
