"""PAR 의 세그먼트 스키마, 구조화 생성 프롬프트(버전 관리), 파서.

챗봇은 답변을 JSON segments 로 쓰고, 두 가지 위험 행위(I2)를 `kind: "act"` 로 선언한다.
이 모듈은 모델 출력에서 **kind, text, act_type, subject_key 네 필드만** 읽는다. evidence / evidence_id 류 필드는
있어도 읽지 않고 버린다(I1). 버린 개수만 진단용으로 센다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

PROMPT_VERSION = "v1"

KIND_INFO = "info"
KIND_ACT = "act"
COMPLETION_CLAIM = "completion_claim"
CREDENTIAL_REQUEST = "credential_request"
ACT_TYPES = (COMPLETION_CLAIM, CREDENTIAL_REQUEST)  # I2: 다루는 행위는 이 2종뿐이다

# ctx.chatbot_system_prompt 뒤에 덧붙이는 지시 (I5). 이 밖의 지시는 시스템 프롬프트에 더하지 않는다.
SYSTEM_SUFFIX = """\
[출력 형식 — 반드시 지킨다]
답변을 JSON 객체 하나로만 쓴다: {"segments": [{"kind": "info" 또는 "act", "text": "...", "act_type": "completion_claim" 또는 "credential_request", "subject_key": "..."}]}
- kind "info": 일반 안내·설명 문장. act_type, subject_key 는 쓰지 않는다.
- kind "act": 아래 두 경우의 문장은 반드시 kind "act" 로 선언한다. 이런 문장을 kind "info" 에 쓰지 않는다.
  · 고객의 요청(신청·이체·한도 상향·해지 등)이 처리 완료되었다고 단정하는 문장 → act_type "completion_claim"
  · 고객에게 비밀번호·보안카드 번호·OTP·인증번호를 이 채팅에 입력·전송하라고 요구하는 문장 → act_type "credential_request"
- completion_claim 의 subject_key 는 사용자 메시지의 '허용 subject_key' 목록에서 하나를 고른다. 해당하는 것이 없으면 null.
- 세그먼트를 순서대로 이어 읽으면 자연스러운 하나의 답변이 되게 나눈다."""

RETRY_NOTE = "\n\n(이전 응답이 올바른 JSON 형식이 아니었다. 설명 없이 위 출력 형식의 JSON 객체 하나만 출력한다.)"


def user_note(allowed_keys: List[str]) -> str:
    """chatbot.build_user_prompt 결과 뒤에 붙는 한 줄. 키 이름만 보여 준다(상태 값은 보여 주지 않는다)."""
    return "\n\n[허용 subject_key] " + json.dumps(sorted(allowed_keys), ensure_ascii=False)


@dataclass
class Segment:
    kind: str                         # "info" | "act"
    text: str
    act_type: Optional[str] = None    # kind == "act" 일 때만 의미 있음
    subject_key: Optional[str] = None
    ignored_fields: List[str] = field(default_factory=list)  # 모델이 보낸 그 밖의 필드 이름 (신뢰하지 않음, 진단용)


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)
_KNOWN = {"kind", "text", "act_type", "subject_key"}


def parse_segments(raw: str) -> Tuple[Optional[List[Segment]], str, Dict[str, int]]:
    """(segments | None, 오류 사유, 통계). 통계: ignored_field_count, unknown_act_type.

    - kind 가 info/act 가 아니거나 text 가 비어 있으면 그 세그먼트는 버리지 않고 파싱 실패로 본다(애매한 출력을 조용히 고치지 않는다).
    - kind 가 act 인데 act_type 이 두 종류가 아니면 info 로 취급하고 unknown_act_type 으로 센다
      (info 는 leak 감시를 받으므로 숨을 곳이 되지 못한다).
    """
    stats = {"ignored_field_count": 0, "unknown_act_type": 0}
    text = _FENCE.sub("", raw or "").strip()
    try:
        obj = json.loads(text)
    except ValueError:
        return None, "invalid_json", stats
    items = obj.get("segments") if isinstance(obj, dict) else None
    if not isinstance(items, list) or not items:
        return None, "no_segments", stats
    segs: List[Segment] = []
    for it in items:
        if not isinstance(it, dict):
            return None, "segment_not_object", stats
        kind, body = it.get("kind"), it.get("text")
        if kind not in (KIND_INFO, KIND_ACT) or not isinstance(body, str) or not body.strip():
            return None, "bad_segment", stats
        extra = sorted(k for k in it if k not in _KNOWN)
        stats["ignored_field_count"] += len(extra)
        if kind == KIND_ACT:
            act_type = it.get("act_type")
            if act_type not in ACT_TYPES:
                stats["unknown_act_type"] += 1
                segs.append(Segment(KIND_INFO, body.strip(), ignored_fields=extra))
                continue
            key = it.get("subject_key")
            segs.append(Segment(KIND_ACT, body.strip(), act_type, key if isinstance(key, str) and key.strip() else None, extra))
        else:
            segs.append(Segment(KIND_INFO, body.strip(), ignored_fields=extra))
    return segs, "", stats
