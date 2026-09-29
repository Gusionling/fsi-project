"""LLM 호출 단일 진입점.

프로젝트의 모든 LLM 호출은 call_llm 을 통해서만 한다. 같은 인터페이스에 아래 세 가지를 얹는다.
  (a) 테스트용 가짜 클라이언트 — 단위 테스트가 API 없이 돈다
  (b) 디스크 캐시(.llm_cache/) — 평가 반복 시 비용 방지
  (c) 오프라인 재생 모드 — 데모의 --offline 과 동일한 경로
"""
from typing import Any


def call_llm(prompt: str, json_mode: bool = False) -> Any:
    """json_mode=True 이면 파싱된 dict 를, 아니면 문자열을 반환한다."""
    raise NotImplementedError
