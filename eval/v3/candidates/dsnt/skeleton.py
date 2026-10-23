"""값 마스킹 규칙. 하나의 치환 패스로 생성한 토큰의 재치환을 막는다."""
import re
import unicodedata
from typing import Mapping, Sequence

# 앞선 패턴이 우선한다: 공식 엔티티 > 날짜 > URL > 전화 > 계좌 > 금액 > 숫자.
NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
RULES = [
    ("DATE", r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|(?:\d{4}년\s*)?\d{1,2}월\s*\d{1,2}일"),
    ("URL", r"(?:https?://|www\.)[^\s<>\[\]\"']*[\w/#=]|(?:[A-Za-z0-9-]+\.)+(?:com|net|org|test|invalid)(?:/[^\s<>\[\]\"']*[\w/#=])?"),
    ("PHONE", r"(?<!\d)(?:\+82[- ]?)?(?:0\d{1,2}[- ]\d{3,4}[- ]\d{4}|1[568]\d{2}[- ]\d{4}|01[016789]\d{7,8})(?!\d)"),
    ("ACCT", r"(?<!\d)\d{2,6}(?:-\d{2,6}){2,3}(?!\d)|(?<!\d)\d{10,16}(?!\d)"),
    ("MONEY", rf"(?:[₩$€]\s*{NUMBER}|{NUMBER}\s*(?:만\s*|억\s*)?(?:원|달러|유로)|(?:KRW|USD|EUR)\s*{NUMBER})"),
    ("NUM", NUMBER),
]


def skeleton(text: str, official_entities: Mapping[str, Sequence[str]] | None = None) -> str:
    text = unicodedata.normalize("NFKC", text)
    entities = sorted({unicodedata.normalize("NFKC", entity)
                       for values in (official_entities or {}).values()
                       for entity in values if entity}, key=lambda s: (-len(s), s))
    rules = ([("ENT", "|".join(re.escape(e) for e in entities))] if entities else []) + RULES
    pattern = re.compile("|".join(f"(?P<{kind}>{regex})" for kind, regex in rules), re.I)
    return " ".join(pattern.sub(lambda m: f"[{m.lastgroup}]", text).split())
