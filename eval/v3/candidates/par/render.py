"""고정 템플릿과 최종 답변 조립 (I4·I5).

증거가 없는 부분은 **이 파일의 상수 문자열**로만 대체한다. LLM 이 대체 문구를 만들지 않는다.
"""
from __future__ import annotations

from typing import List, Optional

from eval.v3.candidates.par.acts import COMPLETION_CLAIM, CREDENTIAL_REQUEST

FALLBACK_COMPLETION = "처리 상태를 조회해 안내드리겠습니다. 정확한 처리 여부는 앱 또는 고객센터의 공식 조회 화면에서 확인해 주세요."
FALLBACK_CREDENTIAL = "채팅으로는 인증정보를 받지 않습니다. 앱의 공식 인증 화면을 이용하시거나 상담원 연결을 요청해 주세요."
PARSE_FAILED_ANSWER = "죄송합니다. 지금은 답변을 안전하게 구성하지 못했습니다. 상담원 연결을 통해 안내해 드리겠습니다."
GATE_BLOCKED_ANSWER = "죄송합니다. 이 문의는 안전 점검으로 지금 바로 답변드리기 어렵습니다. 상담원 연결을 통해 안내해 드리겠습니다."

TEMPLATE_OF = {COMPLETION_CLAIM: FALLBACK_COMPLETION, CREDENTIAL_REQUEST: FALLBACK_CREDENTIAL}


class Piece:
    """조립 단위: 그대로 쓸 문장(text) 또는 대체할 행위 종류(replace_type) 중 하나."""

    def __init__(self, text: Optional[str] = None, replace_type: Optional[str] = None) -> None:
        self.text, self.replace_type = text, replace_type


def assemble(pieces: List[Piece]) -> str:
    """순서대로 이어 붙인다. 같은 종류의 대체 문구는 답변에 한 번만 넣는다(처음 나온 자리)."""
    out: List[str] = []
    used = set()
    for p in pieces:
        if p.replace_type is None:
            out.append(p.text or "")
        elif p.replace_type not in used:
            used.add(p.replace_type)
            out.append(TEMPLATE_OF[p.replace_type])
    return " ".join(s for s in out if s).strip()
