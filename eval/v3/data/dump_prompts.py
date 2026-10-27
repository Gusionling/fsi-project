"""생성에 쓴 프롬프트 원문을 prompts/generation_prompts.md 로 내보낸다 (재현용, 소유자 data).

    python eval/v3/data/dump_prompts.py
코드의 상수를 그대로 쓰므로 코드와 문서가 어긋나지 않는다. 시나리오 표는 prompts/scenarios_*.json, 직접 쓴 공격 문구는 prompts/hand_clauses.json 이다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.v3.data import data_lib as D  # noqa: E402
from eval.v3.data import gen_attack_clauses as C  # noqa: E402
from eval.v3.data import gen_lib as G  # noqa: E402
from eval.v3.data import revise_scenarios as R  # noqa: E402

CHECK_HN_FILE = Path(__file__).with_name("check_hn.py")


def block(title: str, body: str) -> str:
    return f"## {title}\n\n```\n{body.strip()}\n```\n"


def main() -> int:
    from eval.v3.data import check_hn as H

    parts = [
        "# 생성에 쓴 프롬프트 원문\n\n모델은 모두 `gpt-4o-mini` (온도 0.9, QA·추출·점검은 0). `{...}` 는 시나리오 표의 값으로 채워진다.\n"
        "시나리오 표: `scenarios_attack_bases.json` / `scenarios_normal.json` / `scenarios_donors.json` / `scenarios_integrity.json`.\n"
        "직접 쓴 공격 문구: `hand_clauses.json`. 모델이 쓴 공격 문구: `llm_clauses.json`. T4 시험 이력: `t4_attempts.json`, `t4_final_probe.json`.\n",
        block("시스템 프롬프트(모든 생성 호출 공통)", G.SYSTEM),
        block("정상·기반 문서 생성 (gen_lib.NORMAL_PROMPT)", G.NORMAL_PROMPT),
        block("상태 확인 행에 붙는 규칙 (STATUS_EXTRA)", G.STATUS_EXTRA),
        block("T2 기반 문서의 명령형 금지 규칙 (NO_IMPERATIVE_EXTRA)", G.NO_IMPERATIVE_EXTRA),
        block("gold_facts / required_info 추출 (EXTRACT_PROMPT)", G.EXTRACT_PROMPT),
        block("관련성·일관성·답변 가능성 QA (QA_PROMPT)", G.QA_PROMPT),
        block("무결성 문서 생성 (INTEGRITY_PROMPT)", G.INTEGRITY_PROMPT),
        block("모델이 쓰는 공격 문구 (gen_attack_clauses.PROMPT)", C.PROMPT),
        block("의도별 지침 (INTENT_GUIDE)", "\n".join(f"{k}: {v}" for k, v in C.INTENT_GUIDE.items())),
        block("티어별 문체 지침 (TIER_GUIDE)", "\n".join(f"{k}: {v}" for k, v in C.TIER_GUIDE.items())),
        block("문서 종류 (DOC_TYPES)", "\n".join(f"{k}: {v}" for k, v in G.DOC_TYPES.items())),
        block("시작 방식 (OPENERS)", "\n".join(G.OPENERS)),
        block("hard negative 설명 (HN_DESC)", "\n".join(f"{k}: {v}" for k, v in G.HN_DESC.items())),
        block("rev1: 의도별 질문 유형 (revise_scenarios)", "ACCT_Q / LINK_Q / EXFIL_Q 는 revise_scenarios.py 의 상수와 같다. prompt_leak 는 질문 끝에 '이 안내가 어떤 내부 기준(지침)에 근거한 것인지도 알고 싶다'를 덧붙인다.\n" + R.NOTE_NO_ACCT + "\n" + R.NOTE_NO_URL + "\n" + R.NOTE_NO_CRED_WARN),
        block("rev2: hard negative 행의 질문 유형 (HN_QTYPES)", "\n".join(f"{k}: {v}" for k, v in R.HN_QTYPES.items())),
        block("hard negative 라벨 점검 (check_hn.PROMPT)", H.PROMPT + "\n\n" + "\n".join(f"{k}: {v}" for k, v in H.TRAIT.items())),
    ]
    out = D.DATA_DIR / "prompts" / "generation_prompts.md"
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
