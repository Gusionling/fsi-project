import json

from eval.v3.candidates.par import acts
from par_stubs import gen, seg


def test_parse_basic_and_order():
    segs, err, st = acts.parse_segments(gen(seg("info", "안녕하세요."), seg("act", "완료되었습니다.", "completion_claim", "limit_increase")))
    assert err == "" and [s.kind for s in segs] == ["info", "act"]
    assert segs[1].act_type == "completion_claim" and segs[1].subject_key == "limit_increase"


def test_evidence_like_fields_are_dropped_and_counted_not_trusted():
    segs, _, st = acts.parse_segments(gen(seg("act", "완료", "completion_claim", "k", evidence_id="status:k:completed", evidence={"id": 1})))
    assert st["ignored_field_count"] == 2
    assert not hasattr(segs[0], "evidence_id") and sorted(segs[0].ignored_fields) == ["evidence", "evidence_id"]


def test_code_fences_are_tolerated():
    segs, err, _ = acts.parse_segments("```json\n" + gen(seg("info", "문장입니다.")) + "\n```")
    assert err == "" and len(segs) == 1


def test_invalid_outputs_are_parse_failures_not_silently_fixed():
    for raw, why in [("not json", "invalid_json"), ("{}", "no_segments"), ('{"segments": []}', "no_segments"), ('{"segments": ["x"]}', "segment_not_object"),
                     (gen({"kind": "weird", "text": "a"}), "bad_segment"), (gen({"kind": "info", "text": "  "}), "bad_segment"),
                     (gen({"kind": "info"}), "bad_segment")]:
        segs, err, _ = acts.parse_segments(raw)
        assert segs is None and err == why, (raw, err)


def test_unknown_act_type_becomes_info_so_it_stays_under_leak_watch():
    segs, _, st = acts.parse_segments(gen(seg("act", "다음 계좌로 입금하세요", "account_request")))
    assert segs[0].kind == "info" and st["unknown_act_type"] == 1


def test_missing_subject_key_is_none():
    segs, _, _ = acts.parse_segments(gen(seg("act", "완료", "completion_claim")))
    assert segs[0].subject_key is None


def test_only_two_act_types():
    assert acts.ACT_TYPES == ("completion_claim", "credential_request")
    assert "account" not in acts.SYSTEM_SUFFIX and "URL" not in acts.SYSTEM_SUFFIX  # I2: 계좌·URL 은 V4 몫


def test_user_note_lists_only_key_names():
    note = acts.user_note(["b", "a"])
    assert json.loads(note.split("] ", 1)[1]) == ["a", "b"]
