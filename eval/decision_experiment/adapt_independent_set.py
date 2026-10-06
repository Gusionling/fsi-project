"""independent_set.json(별도 세션·별도 모델이 생성한 최종 평가 전용 세트)을
human_written_template.json과 같은 스키마로 변환하는 어댑터.

이 세트는 "사람이 직접 작성한" 것이 아니다 — 문서/코드의 "human_written" 개념은
전부 "independent_generated"(별도 세션·별도 모델 생성)로 대체됐다. 내용(공격 문구,
엔티티, 표현 패턴)은 설계·프롬프트·규칙 튜닝에 전혀 참고하지 않는다 — 이 스크립트는
필드명/구조만 바꾸는 순수 포맷 변환이며, `text` 필드의 문장 자체는 수정하지 않는다.
최종 평가(동결된 탐지기로 한 번만 실행)에만 쓴다.

필드 매핑(independent_set.json → human_written 스키마):
  kind(attack/normal)  -> ground_truth_label (attack=optimized_injection, normal=normal)
  intent(또는 "none")  -> intent (none이면 null)
  style                -> style (신규 메타 필드로 그대로 보존)
  text                 -> chunk.clause_text (schema_type=terms_clause로 감싼다 —
                           independent_set.json에는 schema_type 구분이 없으므로, 자유
                           텍스트 하나만 있으면 스키마를 만족하는 terms_clause를 쓴다.
                           article_no 등 구조 필드는 내용과 무관한 placeholder다.)

scope_marker/attack_class는 사람이 보고 판단하지 않고 1.5절 규칙(정규식)으로 자동
계산한다 — validate_human_written.classify_attack_class와 동일 정의.

실행: python -m eval.decision_experiment.adapt_independent_set
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from eval.decision_experiment.validate_human_written import classify_attack_class  # noqa: E402

SRC_PATH = ROOT / "eval" / "dataset" / "holdout" / "independent_set.json"
OUT_PATH = ROOT / "eval" / "dataset" / "holdout" / "independent_generated.json"

SCOPE_MARKER_RE = re.compile(r"모든.{0,6}(답변|응답|상담|안내)")

KIND_TO_LABEL = {"attack": "optimized_injection", "normal": "normal"}


def adapt_entry(idx: int, src: dict) -> dict:
    kind = src["kind"]
    label = KIND_TO_LABEL[kind]
    is_injection = label != "normal"
    text = src["text"]
    intent = src["intent"] if src["intent"] != "none" else None

    out = {
        "chunk_id": f"ind_{idx:03d}",
        "tier": "independent_generated",
        "intent": intent,
        "group": f"independent_{src['style']}",
        "style": src["style"],
        "schema_type": "terms_clause",
        "ground_truth_label": label,
        "scope_marker": bool(SCOPE_MARKER_RE.search(text)) if is_injection else False,
        "attack_class": classify_attack_class(text) if is_injection else None,
        "chunk": {
            "article_no": "제1조",
            "paragraph_no": "제1항",
            "item_no": "제1호",
            "sub_item": "가목",
            "clause_text": text,
        },
    }
    return out


def main():
    src_items = json.loads(SRC_PATH.read_text(encoding="utf-8"))
    out_items = [adapt_entry(i, s) for i, s in enumerate(src_items, 1)]
    OUT_PATH.write_text(json.dumps(out_items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"변환 완료: {SRC_PATH.name} {len(src_items)}건 -> {OUT_PATH.name} {len(out_items)}건")


if __name__ == "__main__":
    main()
