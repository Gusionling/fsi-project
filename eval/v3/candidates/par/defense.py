"""PARDefense — 근거 증명 답변 렌더러 (Proof-carrying Answer Renderer), CONTRACT §6.1 의 게이트 조합.

    b1_chunk_gate(입구, stack_b1) → 구조화 생성 → 증거 바인딩·leak 감시 → 렌더 → v4_answer_gate(출구)

설정 (러너가 --set key=value 로 ctx.config 에 넣는다; 생성자는 인자를 받지 않는다)
  stack_b1   기본 true   입구 B1 게이트를 쓸지
  leak_check 기본 true   info 세그먼트로 새는 위험 행위를 감시할지 (false 면 '구조화 선언만'의 효과를 분리해 볼 수 있다)

설계 문서: design.md. 이 파일은 eval/v3/common 을 import 하지 않는다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from eval.v3.candidates.par import acts, evidence, leak, render
from eval.v3.candidates.par.acts import COMPLETION_CLAIM, CREDENTIAL_REQUEST, KIND_ACT, Segment
from eval.v3.candidates.par.render import Piece
from eval.v3.interfaces import Case, DefenseResult, RunContext

GEN_MAX_TOKENS = 1024


def _flag(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off", "")
    return bool(value)


class PARDefense:
    name = "par"

    def fit(self, calib_cases: List[Case], ctx: RunContext) -> None:
        return None  # 임계값이 없다: 판정은 코드가 하는 조회 결과뿐이다

    # ------------------------------------------------------------------ 생성
    def _generate(self, case: Case, ctx: RunContext, allowed: List[str]):
        """(segments | None, 오류 사유, 통계, LLM 호출 수, 재시도 여부). I9: 파손되면 한 번 재시도하고, 그래도 안 되면 None."""
        system = (ctx.chatbot_system_prompt + "\n\n" if ctx.chatbot_system_prompt else "") + acts.SYSTEM_SUFFIX
        user = ctx.chatbot.build_user_prompt(case.query, case.chunks) + acts.user_note(allowed)
        calls = 0
        for attempt in (0, 1):
            raw = ctx.llm.complete(system=system, user=user + (acts.RETRY_NOTE if attempt else ""), model=ctx.chatbot_model,
                                   temperature=0.0, max_tokens=GEN_MAX_TOKENS, json_mode=True, tag="par_gen")
            calls += 1
            segs, err, stats = acts.parse_segments(raw)
            if segs is not None:
                return segs, "", stats, calls, bool(attempt)
        return None, err, stats, calls, True

    # ------------------------------------------------------------------ 실행
    def run(self, case: Case, ctx: RunContext) -> DefenseResult:
        stack_b1 = _flag(ctx.config.get("stack_b1"), True)
        leak_check = _flag(ctx.config.get("leak_check"), True)
        flags: Dict[str, Any] = {
            "prompt_version": acts.PROMPT_VERSION, "leak_prompt_version": leak.LEAK_PROMPT_VERSION,
            "stack_b1": stack_b1, "leak_check": leak_check,
            "acts_declared": 0, "acts_licensed": 0, "acts_rejected": 0, "leak_detected": 0, "leak_rejected": 0,
            "parse_failed": False, "parse_retry_used": False, "rejected_acts": [], "licensed_evidence": [],
        }
        calls = 0

        # 1) 입구
        if stack_b1:
            g = ctx.gates.b1_chunk_gate(case, ctx)
            calls += g.llm_calls
            flags["b1"] = {"score": g.score, "blocked": g.blocked}
            if g.blocked:
                return DefenseResult(final_answer=render.GATE_BLOCKED_ANSWER, blocked=True, scores={"risk": 1.0},
                                     flags={**flags, "blocked_by": "b1", "risk_source": "gate"}, llm_calls=calls)

        # 2) 구조화 생성 (I5, I9)
        allowed = sorted(((case.trusted_fixture or {}).get("application_status") or {}).keys())
        segs, err, stats, gen_calls, retried = self._generate(case, ctx, allowed)
        calls += gen_calls
        flags["parse_retry_used"] = retried
        if segs is None:
            flags.update(parse_failed=True, parse_error=err)
            return DefenseResult(final_answer=render.PARSE_FAILED_ANSWER, fallback_used=True, scores={"risk": 0.0},
                                 flags={**flags, "risk_source": "parse_failed"}, llm_calls=calls)
        flags["segments"] = len(segs)
        flags["ignored_field_count"] = stats["ignored_field_count"]   # 모델이 보낸 evidence 류 필드: 읽지 않고 센 것뿐 (I1)
        flags["unknown_act_type"] = stats["unknown_act_type"]

        # 3) 선언된 act 의 증거 바인딩 (I1·I3) — 증거는 코드가 ctx.trusted 로만 만든다
        state: Dict[int, Optional[str]] = {}   # 세그먼트 번호 → None(그대로) | 대체할 act_type
        licensed_ids: Dict[int, str] = {}
        for i, seg in enumerate(segs):
            if seg.kind != KIND_ACT:
                continue
            flags["acts_declared"] += 1
            ev, why = evidence.bind(case, ctx, seg.act_type, seg.subject_key)
            if ev is not None:
                licensed_ids[i] = ev.evidence_id
                state[i] = None
            else:
                state[i] = seg.act_type
                flags["acts_rejected"] += 1
                flags["rejected_acts"].append(self._rejected("declared", seg.act_type, seg.subject_key, why, seg.text))

        # 4) info 로 새는 act 감시 (I6): info 전부 + 증거가 인정된 act(선언한 종류와 실제 문장이 같은지)
        if leak_check:
            targets = [i for i, s in enumerate(segs) if s.kind != KIND_ACT or i in licensed_ids]
            verdicts, lerr, lcalls = leak.detect(ctx.llm, ctx.chatbot_model, case.query, [segs[i].text for i in targets], allowed)
            calls += lcalls
            if lerr:
                flags["leak_parse_failed"] = lerr   # 감시기 응답이 깨지면 누출 없음으로 취급한다 (설계 결정 표 참고)
            for pos, i in enumerate(targets):
                v = verdicts.get(pos)
                if v is None:
                    continue
                seg = segs[i]
                if seg.kind == KIND_ACT:  # 증거가 인정된 completion act — 실제로는 인증정보 요구인 경우만 잡는다
                    if v.requests_credentials_in_chat:
                        del licensed_ids[i]
                        state[i] = CREDENTIAL_REQUEST
                        flags["acts_rejected"] += 1
                        flags["leak_detected"] += 1
                        flags["rejected_acts"].append(self._rejected("act_type_mismatch", CREDENTIAL_REQUEST, seg.subject_key, "credential_never_licensed", seg.text))
                    continue
                if v.requests_credentials_in_chat:
                    state[i] = CREDENTIAL_REQUEST
                    flags["leak_detected"] += 1
                    flags["leak_rejected"] += 1
                    flags["rejected_acts"].append(self._rejected("leak", CREDENTIAL_REQUEST, None, "credential_never_licensed", seg.text))
                elif v.claims_completion:
                    flags["leak_detected"] += 1
                    ev, why = evidence.bind(case, ctx, COMPLETION_CLAIM, v.completion_subject_key)
                    if ev is not None:
                        licensed_ids[i] = ev.evidence_id    # 새어 나온 완료 단정이라도 코드 조회가 인정하면 출력한다 (L2 와 같은 규칙)
                    else:
                        state[i] = COMPLETION_CLAIM
                        flags["leak_rejected"] += 1
                        flags["rejected_acts"].append(self._rejected("leak", COMPLETION_CLAIM, v.completion_subject_key, why, seg.text))
        flags["acts_licensed"] = sum(1 for i, s in enumerate(segs) if s.kind == KIND_ACT and i in licensed_ids)
        flags["licensed_evidence"] = sorted(set(licensed_ids.values()))

        # 5) 렌더 (I4): 인정된 것만 그대로, 나머지는 고정 템플릿
        pieces = [Piece(replace_type=state[i]) if state.get(i) else Piece(text=s.text) for i, s in enumerate(segs)]
        answer = render.assemble(pieces)
        rejected_total = flags["acts_rejected"] + flags["leak_rejected"]
        flags["rejected_total"] = rejected_total

        # 6) 출구 (I7) — 계좌·URL·전화는 V4 게이트가 본다
        v4 = ctx.gates.v4_answer_gate(case, answer, ctx)
        calls += v4.llm_calls
        if v4.blocked:
            return DefenseResult(final_answer=render.GATE_BLOCKED_ANSWER, blocked=True, fallback_used=rejected_total > 0,
                                 scores={"risk": 1.0}, flags={**flags, "blocked_by": "v4", "risk_source": "gate", "withheld_answer": answer},
                                 llm_calls=calls)
        return DefenseResult(final_answer=answer, fallback_used=rejected_total > 0,
                             scores={"risk": 1.0 if rejected_total > 0 else 0.0},
                             flags={**flags, "risk_source": "rejected_acts" if rejected_total else "none"}, llm_calls=calls)

    @staticmethod
    def _rejected(source: str, act_type: Optional[str], key: Optional[str], reason: str, text: str) -> Dict[str, Any]:
        return {"source": source, "act_type": act_type, "subject_key": key, "reason": reason, "text": text[:160]}
