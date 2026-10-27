"""no_defense: 방어 없이 기존 챗봇 그대로 (CONTRACT §6.3)."""
from __future__ import annotations

from typing import List

from eval.v3.interfaces import Case, DefenseResult, RunContext


class NoDefense:
    name = "no_defense"

    def fit(self, calib_cases: List[Case], ctx: RunContext) -> None:
        return None

    def run(self, case: Case, ctx: RunContext) -> DefenseResult:
        answer = ctx.chatbot.answer(case.query, case.chunks)
        return DefenseResult(final_answer=answer, llm_calls=1)
