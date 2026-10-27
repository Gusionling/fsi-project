"""진단용 DSNT. 실제 호출은 주입받은 챗봇과 RunContext.llm에 한정한다."""
from dataclasses import replace
from math import fsum

from eval.v3.interfaces import DefenseResult
from .conformal import can_decide, p_value
from .distance import distances
from .skeleton import skeleton

BLOCK_MESSAGE = "문서 간 답변 일관성을 확인하기 어려워 안내를 보류합니다. 공식 상담 채널에서 확인해 주세요."


class DSNTDefense:
    name = "dsnt"

    def __init__(self, alpha: float = 0.05):
        if not 0 < alpha < 1:
            raise ValueError("alpha는 0과 1 사이여야 합니다")
        self.alpha = alpha
        self.calibration_scores: tuple[float, ...] = ()
        self.calibration_llm_calls = 0
        self._fit_signature = None

    def _settings(self, ctx):
        k = ctx.config.get("donors_k", 5)
        kind = ctx.config.get("dist_kind", "edit")
        alpha = ctx.config.get("alpha", self.alpha)
        if type(k) is not int or k < 1 or kind not in {"edit", "embed"}:
            raise ValueError("donors_k는 양의 정수, dist_kind는 edit/embed여야 합니다")
        can_decide(0, alpha, warn=False)  # alpha 검증만 수행
        return k, kind, alpha

    def _signature(self, ctx):
        k, kind, _ = self._settings(ctx)
        entities = tuple((key, tuple(sorted(values))) for key, values in sorted(ctx.trusted.official_entities().items()))
        return (k, kind, ctx.seed, ctx.config.get("embedding_model", "text-embedding-3-small"),
                ctx.chatbot_model, ctx.chatbot_system_prompt, entities)

    def _score(self, case, ctx, original_answer=None):
        k, kind, _ = self._settings(ctx)
        targets = [i for i, c in enumerate(case.chunks) if c.role == "target"]
        if not targets:
            raise ValueError("DSNT에는 target 청크가 필요합니다")
        excluded = [c.chunk_id for c in case.chunks]
        pools = []
        for offset, _ in enumerate(targets):
            donors = ctx.donors.sample(case.topic, k, excluded, ctx.seed + offset)
            if len(donors) != k or len({d.chunk_id for d in donors}) != k or any(d.chunk_id in excluded for d in donors):
                raise ValueError("동일 주제의 중복·입력 겹침 없는 donor k개가 필요합니다")
            pools.append(donors)
        calls = 0
        if original_answer is None:
            original_answer = ctx.chatbot.answer(case.query, case.chunks)
            calls += 1
        entities = ctx.trusted.official_entities()
        shapes = [skeleton(original_answer, entities)]
        for j in range(k):
            chunks = list(case.chunks)
            for i, pool in zip(targets, pools):
                chunks[i] = replace(pool[j], role="target")
            shapes.append(skeleton(ctx.chatbot.answer(case.query, chunks), entities))
            calls += 1
        ds, embed_calls = distances(shapes, kind, ctx)
        return fsum(ds) / k, shapes, calls + embed_calls

    def fit(self, calib_cases, ctx):
        cases = list(calib_cases)
        # 입력 전체를 먼저 검증: dev/공격/sealed를 부분적으로라도 보정에 쓰지 않는다.
        if any(c.split != "calib" or c.label != "normal" for c in cases):
            raise ValueError("calib 정상 케이스만 fit에 사용할 수 있습니다")
        if len({c.case_id for c in cases}) != len(cases):
            raise ValueError("중복 보정 케이스 id")
        signature = self._signature(ctx)
        scores, calls = [], 0
        # gate로 정상 보정 표본을 선택하지 않는다. 모든 정상의 raw s를 같은 방식으로 계산.
        for case in cases:
            s, _, n = self._score(case, ctx)
            scores.append(s)
            calls += n
        self.calibration_scores = tuple(scores)
        self.calibration_llm_calls = calls
        self._fit_signature = signature
        can_decide(len(scores), self._settings(ctx)[2])

    def run(self, case, ctx):
        k, kind, alpha = self._settings(ctx)
        flags = {"s": None, "p": None, "donors_k": k, "dist_kind": kind,
                 "skeletons": [], "m": len(self.calibration_scores), "alpha": alpha}
        calls = 0
        if ctx.config.get("stack_b1", True):
            gate = ctx.gates.b1_chunk_gate(case, ctx)
            calls += gate.llm_calls
            flags["b1"] = {"blocked": gate.blocked, "score": gate.score}
            if gate.blocked:
                flags["dsnt_skipped"] = "b1"
                return DefenseResult(BLOCK_MESSAGE, blocked=True, flags=flags, llm_calls=calls)
        answer = ctx.chatbot.answer(case.query, case.chunks)
        calls += 1
        gate = ctx.gates.v4_answer_gate(case, answer, ctx)
        calls += gate.llm_calls
        flags["v4"] = {"blocked": gate.blocked, "score": gate.score}
        if gate.blocked:
            flags["dsnt_skipped"] = "v4"
            return DefenseResult(BLOCK_MESSAGE, blocked=True, flags=flags, llm_calls=calls)
        if self._fit_signature is not None and self._signature(ctx) != self._fit_signature:
            raise ValueError("보정 후 점수 설정이 변경되었습니다. 같은 설정으로 다시 fit하세요")
        if not can_decide(len(self.calibration_scores), alpha):
            flags["dsnt_skipped"] = "insufficient_calibration"
            return DefenseResult(answer, flags=flags, llm_calls=calls)
        s, shapes, n = self._score(case, ctx, answer)
        p = p_value(s, self.calibration_scores)
        flags.update(s=s, p=p, skeletons=shapes)
        # p <= alpha: alpha를 낮추면 차단이 줄어든다.
        blocked = p <= alpha
        return DefenseResult(BLOCK_MESSAGE if blocked else answer, blocked=blocked,
                             scores={"risk": 1 - p}, flags=flags, llm_calls=calls + n)
