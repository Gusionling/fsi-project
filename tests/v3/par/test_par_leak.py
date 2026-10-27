import json

from eval.v3.candidates.par import leak
from par_stubs import FakeLLM


def test_parse_results_normalizes_keys_and_ignores_bad_rows():
    raw = json.dumps({"results": [{"index": 0, "claims_completion": True, "completion_subject_key": "made_up", "requests_credentials_in_chat": False},
                                  {"index": 1, "claims_completion": False, "completion_subject_key": None, "requests_credentials_in_chat": True},
                                  {"index": 9, "claims_completion": True}, "junk"]})
    out, err = leak.parse_results(raw, 2, ["limit_increase"])
    assert err == "" and out[0].claims_completion and out[0].completion_subject_key is None and out[1].requests_credentials_in_chat and 9 not in out


def test_parse_results_failure_reports_reason():
    assert leak.parse_results("nope", 1, [])[1] == "invalid_json"


def test_detect_skips_call_for_empty_input_and_reports_parse_error():
    class Bad(FakeLLM):
        def complete(self, **kw):
            return "깨진 응답"
    assert leak.detect(FakeLLM([""]), "m", "q", [], []) == ({}, "", 0)
    verdicts, err, calls = leak.detect(Bad([""]), "m", "q", ["문장"], [])
    assert verdicts == {} and err == "invalid_json" and calls == 1


def test_prompt_uses_same_definitions_as_the_contract():
    p = leak.LEAK_PROMPT
    assert "이미 처리 완료" in p and "일반 절차 안내" in p and "채팅" in p and "절차 안내나 경고" in p
