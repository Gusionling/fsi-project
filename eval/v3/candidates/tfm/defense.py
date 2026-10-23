"""TFM-S/TFM-T 최소판: B1 → 청크별 추출 → 허가 → 표 답변 → V4."""
from collections import Counter
from eval.v3.interfaces import DefenseResult
from . import answerer
from .extractor import extract
from .licensing import license_rows, load_ontology

FALLBACK = "제공된 자료에서 확인 가능한 정보를 확보하지 못했습니다. 공식 상담 채널에서 확인해 주세요."
BLOCK_MESSAGE = "자료 또는 답변의 안전성을 확인하기 어려워 안내를 보류합니다. 공식 상담 채널에서 확인해 주세요."


class TFMDefense:
    name = "tfm"

    def __init__(self, mode="S"):
        if mode not in {"S", "T"}:
            raise ValueError("mode는 S/T여야 합니다")
        self.mode = mode

    def fit(self, calib_cases, ctx):
        # 거부 행 비율은 보조 신호일 뿐: calib으로 온톨로지/프롬프트/차단 임계값을 튜닝하지 않는다.
        return None

    def run(self, case, ctx):
        mode = ctx.config.get("mode", self.mode)
        if mode not in {"S", "T"}:
            raise ValueError("mode는 S/T여야 합니다")
        calls, total, failed = 0, 0, 0
        reasons, rows, errors = Counter(), [], Counter()
        flags = {"mode": mode, "risk_is_secondary": True, "n_rows": 0, "n_rejected": 0,
                 "rejection_reasons": {}, "extract_failed": False, "n_extract_failed": 0,
                 "n_accepted": 0, "n_forwarded": 0}
        if ctx.config.get("stack_b1", True):
            gate = ctx.gates.b1_chunk_gate(case, ctx)
            calls += gate.llm_calls
            flags["b1"] = {"blocked": gate.blocked, "score": gate.score}
            if gate.blocked:
                flags["tfm_skipped"] = "b1"
                return DefenseResult(BLOCK_MESSAGE, blocked=True, flags=flags, llm_calls=calls)
        ontology = load_ontology()
        for chunk in case.chunks:
            extraction = extract(chunk, ctx, mode, ontology)
            calls += 1
            if extraction.failed:
                failed += 1
                errors[extraction.error] += 1
                continue
            total += len(extraction.rows)
            licensed, rejected = license_rows(extraction.rows, chunk, ctx.trusted, mode, ontology)
            rows.extend(licensed)
            reasons.update(rejected)
        n_rejected = sum(reasons.values())
        risk = n_rejected / total if total else 0.0
        flags.update(n_rows=total, n_rejected=n_rejected, rejection_reasons=dict(reasons),
                     extract_failed=bool(failed), n_extract_failed=failed, extraction_errors=dict(errors),
                     n_chunks=len(case.chunks), n_accepted=len(rows))
        # 하나라도 파손되면 부분 문맥만으로 확정 답변하지 않는다. fallback은 개입으로 집계된다.
        fallback = bool(failed) or not rows
        if fallback:
            final = FALLBACK
            flags["fallback_reason"] = "extraction_failed" if failed else "no_licensed_rows"
        else:
            final = answerer.answer(case.query, rows, ctx)
            calls += 1
            flags["n_forwarded"] = len(rows)
        gate = ctx.gates.v4_answer_gate(case, final, ctx)
        calls += gate.llm_calls
        flags["v4"] = {"blocked": gate.blocked, "score": gate.score}
        return DefenseResult(BLOCK_MESSAGE if gate.blocked else final, blocked=gate.blocked,
                             fallback_used=fallback, scores={"risk": risk}, flags=flags, llm_calls=calls)
