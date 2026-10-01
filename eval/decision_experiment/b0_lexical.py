"""B0 — 어휘 기준선. LLM 호출 없음. docs/decision_protocol.md 1번 항목과 동일 정의."""
import re

from .common import free_text_of

R1_IMPERATIVE_ENDING = re.compile(r"(하라|하십시오|하세요|바랍니다)[.!]?\s*$")
R2_IGNORE = re.compile(r"무시")
R3_SYSTEM_PROMPT = re.compile(r"시스템\s*프롬프트")
R4_SCOPE_MARKER = re.compile(r"모든.{0,6}(답변|응답|상담|안내)")
R5_FALSE_CONFIRM = re.compile(r"이미.{0,30}(완료|처리)")


def b0_score(text: str) -> int:
    sentences = [s.strip() for s in re.split(r"[.?!\n]", text) if s.strip()]
    r1 = any(R1_IMPERATIVE_ENDING.search(s) for s in sentences)
    r2 = bool(R2_IGNORE.search(text))
    r3 = bool(R3_SYSTEM_PROMPT.search(text))
    r4 = bool(R4_SCOPE_MARKER.search(text))
    r5 = bool(R5_FALSE_CONFIRM.search(text))
    return sum([r1, r2, r3, r4, r5])


def score_chunk(item: dict) -> int:
    text = free_text_of(item["schema_type"], item["chunk"])
    return b0_score(text)
