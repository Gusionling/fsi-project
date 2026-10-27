"""L0 = B1. 청크를 하나씩 LLM 이 0~100 으로 판정하고, 하나라도 70 이상이면 blocked (CONTRACT §6.3)."""
from __future__ import annotations

from typing import List

from eval.v3.interfaces import Case, DefenseResult, RunContext

# 개입(차단/대체) 시 고객에게 나가는 고정 문구. 모든 기준선이 같은 문구를 쓴다.
BLOCKED_ANSWER = "죄송합니다. 이 문의는 안전 점검으로 지금 바로 답변드리기 어렵습니다. 상담원 연결을 통해 안내해 드리겠습니다."


class L0Defense:
    name = "l0"

    def fit(self, calib_cases: List[Case], ctx: RunContext) -> None:
        return None

    def run(self, case: Case, ctx: RunContext) -> DefenseResult:
        b1 = ctx.gates.b1_chunk_gate(case, ctx)
        if b1.blocked:
            return DefenseResult(final_answer=BLOCKED_ANSWER, blocked=True, scores={"risk": b1.score},
                                 flags={"b1": b1.detail}, llm_calls=b1.llm_calls)
        answer = ctx.chatbot.answer(case.query, case.chunks)
        return DefenseResult(final_answer=answer, scores={"risk": b1.score}, flags={"b1": b1.detail},
                             llm_calls=b1.llm_calls + 1)
