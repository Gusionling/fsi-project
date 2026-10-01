"""B3 — 정적 엔티티 화이트리스트. LLM 호출 없음.

공식 목록(whitelist)은 dev set의 정상 청크에서 실제로 나온 엔티티 값으로 구성한다
(docs/decision_protocol.md 1번 항목에 명시한 대로, 이 때문에 dev set에 유리한 상한값이다).
"""
from .common import free_text_of, normalize_core


def build_whitelist(dev_items: list[dict]) -> set:
    whitelist = set()
    for item in dev_items:
        if item["ground_truth_label"] != "normal":
            continue
        text = free_text_of(item["schema_type"], item["chunk"])
        for pattern_name, matches in _all_matches(text):
            whitelist.update((pattern_name, v) for v in matches)
    return whitelist


def _all_matches(text: str):
    from .common import URL_RE, ACCOUNT_RE, PHONE_RE

    yield "url", URL_RE.findall(text)
    yield "account", ACCOUNT_RE.findall(text)
    yield "phone", PHONE_RE.findall(text)


def flag_chunk(item: dict, whitelist: set) -> bool:
    """화이트리스트에 없는 엔티티가 하나라도 있으면 True(flag). 엔티티가 아예 없으면 False."""
    text = free_text_of(item["schema_type"], item["chunk"])
    for pattern_name, matches in _all_matches(text):
        for v in matches:
            if (pattern_name, v) not in whitelist:
                return True
    return False
