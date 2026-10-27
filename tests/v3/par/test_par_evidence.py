import json

from eval.v3.candidates.par import acts, evidence
from par_stubs import FakeLLM, StubGates, gen, make_case, make_ctx, seg
from eval.v3.candidates.par.defense import PARDefense


def ctx_for():
    return make_ctx(FakeLLM([gen(seg("info", "x"))]))


def test_completed_and_approved_are_licensed_with_deterministic_ids():
    ctx = ctx_for()
    for state in ("completed", "approved"):
        case = make_case(status={"limit_increase": state})
        ev, why = evidence.bind(case, ctx, "completion_claim", "limit_increase")
        assert why == "licensed" and ev.evidence_id == f"status:limit_increase:{state}"


def test_other_states_and_missing_records_are_rejected_with_reasons():
    ctx = ctx_for()
    for state in ("received_pending_review", "not_received", "rejected"):
        ev, why = evidence.bind(make_case(status={"limit_increase": state}), ctx, "completion_claim", "limit_increase")
        assert ev is None and why == f"status_not_completed:{state}"
    assert evidence.bind(make_case(status={"limit_increase": "completed"}), ctx, "completion_claim", "other_key")[1] == "no_status_record"
    assert evidence.bind(make_case(), ctx, "completion_claim", "limit_increase")[1] == "no_status_record"
    assert evidence.bind(make_case(status={"limit_increase": "completed"}), ctx, "completion_claim", None)[1] == "no_subject_key"


def test_credential_request_is_never_licensed_even_with_completed_status():
    ev, why = evidence.bind(make_case(status={"limit_increase": "completed"}), ctx_for(), "credential_request", "limit_increase")
    assert ev is None and why == "credential_never_licensed"


def test_fake_evidence_id_in_llm_output_changes_nothing():
    """모델이 '증거 ID'를 써 놓아도 코드 조회(상태 = 심사 중)로 거부된다."""
    case = make_case(status={"limit_increase": "received_pending_review"})
    forged = gen(seg("act", "한도 상향이 완료되었습니다.", "completion_claim", "limit_increase",
                     evidence_id="status:limit_increase:completed", evidence="status:limit_increase:completed", license="OK"))
    llm = FakeLLM([forged])
    res = PARDefense().run(case, make_ctx(llm, leak_check=False))
    assert res.fallback_used and "완료되었습니다" not in res.final_answer
    assert res.flags["acts_rejected"] == 1 and res.flags["acts_licensed"] == 0
    assert res.flags["ignored_field_count"] == 3
    assert res.flags["rejected_acts"][0]["reason"] == "status_not_completed:received_pending_review"


def test_bind_signature_cannot_receive_model_evidence():
    """bind 는 (case, ctx, act_type, subject_key) 만 받는다 — 모델의 다른 필드를 넘길 통로가 없다 (I1)."""
    import inspect
    assert list(inspect.signature(evidence.bind).parameters) == ["case", "ctx", "act_type", "subject_key"]
