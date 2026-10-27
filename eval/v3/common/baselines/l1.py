"""L1 = L0 + V4. 입구 B1 → 챗봇 → 출구 V4 (CONTRACT §6.3, §6.1).

risk 점수: B1 최대 위험도(0~100). V4 가 차단하면 100 (두 문 중 어느 쪽이든 막으면 가장 의심스러운 것으로 취급).
"""
from __future__ import annotations

from typing import List

from eval.v3.common.baselines.l0 import BLOCKED_ANSWER
from eval.v3.interfaces import Case, DefenseResult, RunContext


class L1Defense:
    name = "l1"

    def fit(self, calib_cases: List[Case], ctx: RunContext) -> None:
        return None

    def run(self, case: Case, ctx: RunContext) -> DefenseResult:
        b1 = ctx.gates.b1_chunk_gate(case, ctx)
        calls = b1.llm_calls
        flags = {"b1": b1.detail}
        if b1.blocked:
            return DefenseResult(final_answer=BLOCKED_ANSWER, blocked=True, scores={"risk": b1.score},
                                 flags={**flags, "blocked_by": "b1"}, llm_calls=calls)
        answer = ctx.chatbot.answer(case.query, case.chunks)
        calls += 1
        v4 = ctx.gates.v4_answer_gate(case, answer, ctx)
        flags["v4"] = v4.detail
        if v4.blocked:
            return DefenseResult(final_answer=BLOCKED_ANSWER, blocked=True, scores={"risk": 100.0},
                                 flags={**flags, "blocked_by": "v4", "withheld_answer": answer},
                                 llm_calls=calls + v4.llm_calls)
        return DefenseResult(final_answer=answer, scores={"risk": b1.score}, flags=flags, llm_calls=calls + v4.llm_calls)
