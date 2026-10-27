from dataclasses import replace
import json
import pytest
from eval.v3.candidates.tfm.defense import TFMDefense, FALLBACK, BLOCK_MESSAGE
from eval.v3.candidates.tfm.answerer import POLICY
from tfm_stubs import case, context, row, Gates


def test_query_blind_per_chunk_and_no_raw_text_in_answer_prompt():
    c, ctx = case(), context()
    result = TFMDefense().run(c, ctx)
    extractions = [x for x in ctx.llm.calls if x["tag"] == "tfm_extract"]
    assert len(extractions) == len(c.chunks)
    for call, chunk in zip(extractions, c.chunks):
        assert c.query not in call["system"] + call["user"]
        assert json.loads(call["user"])["document"] == chunk.text
        assert all(other.text not in call["user"] for other in c.chunks if other != chunk)
        assert call["model"] == ctx.chatbot_model and call["json_mode"]
    answer = next(x for x in ctx.llm.calls if x["tag"] == "tfm_answer")
    assert answer["system"] == ctx.chatbot_system_prompt + "\n" + POLICY
    assert c.query in answer["user"]
    assert all(chunk.text not in answer["user"] + answer["system"] for chunk in c.chunks)
    assert "500" in answer["user"] and "fee" in answer["user"]
    assert len(ctx.chatbot.prompts) == 1
    assert not result.intervened
    assert result.flags["n_rows"] == result.flags["n_accepted"] == result.flags["n_forwarded"] == 2
    assert result.llm_calls == 2 + 2 + 1


def test_different_questions_cannot_change_extractor_input():
    one, two = context(), context()
    TFMDefense().run(case(), one)
    TFMDefense().run(replace(case(), query="完全に別の質問"), two)
    assert [c for c in one.llm.calls if c["tag"] == "tfm_extract"] == [c for c in two.llm.calls if c["tag"] == "tfm_extract"]


@pytest.mark.parametrize("mode", ["S", "T"])
def test_determinism(mode):
    ctx = context(mode=mode)
    defense = TFMDefense()
    assert defense.run(case(), ctx) == defense.run(case(), ctx)


@pytest.mark.parametrize("b1,v4", [(True, False), (False, True)])
def test_gate_blocks(b1, v4):
    ctx = context()
    ctx.gates = Gates(b1, v4)
    result = TFMDefense().run(case(), ctx)
    assert result.blocked and result.final_answer == BLOCK_MESSAGE
    assert ctx.gates.calls == (["b1"] if b1 else ["b1", "v4"])
    if b1:
        assert not ctx.llm.calls and "risk" not in result.scores


def test_stack_b1_can_be_disabled_but_v4_is_always_used():
    ctx = context(stack_b1=False)
    ctx.gates = Gates(b1=True)
    assert not TFMDefense().run(case(), ctx).blocked
    assert ctx.gates.calls == ["v4"]


@pytest.mark.parametrize("broken", ["not json", "[]", '{"rows":[],"rows":[]}',  '{"rows": {}}', '{"rows": [], "extra":"x"}', '{"rows":[NaN]}', RuntimeError("private SDK failure")])
def test_extraction_failure_is_conservative_and_reported(broken):
    ctx = context(extraction=[json.dumps({"rows": [row()]}), broken])
    result = TFMDefense().run(case(), ctx)
    assert result.fallback_used and result.final_answer == FALLBACK
    assert result.flags["extract_failed"] and result.flags["n_extract_failed"] == 1
    assert result.flags["n_accepted"] == 1 and result.flags["n_forwarded"] == 0
    assert not any(c["tag"] == "tfm_answer" for c in ctx.llm.calls)
    assert ctx.gates.calls == ["b1", "v4"] and ctx.gates.answers == [FALLBACK]
    assert "private SDK failure" not in json.dumps(result.flags)


def test_rejected_rows_ratio_is_only_secondary_and_not_a_block_threshold():
    payload = {"rows": [row(), row(value=-1), row("application_channel", "enum", "chat")]}
    ctx = context(extraction=json.dumps(payload))
    result = TFMDefense().run(case(), ctx)
    assert result.flags["n_rows"] == 6 and result.flags["n_rejected"] == 4
    assert result.flags["rejection_reasons"] == {"range": 2, "enum": 2}
    assert result.flags["risk_is_secondary"] is True and result.scores["risk"] == 4 / 6
    assert not result.intervened
    answer = next(c for c in ctx.llm.calls if c["tag"] == "tfm_answer")
    facts = json.loads(json.loads(answer["user"])["chunks"][0])["facts"]
    assert facts == [row(), row()]


@pytest.mark.parametrize("extraction", ['{"rows": []}', '{"rows": [{"attribute": "fee", "type": "number", "value": -1}]}'])
def test_no_licensed_rows_fallback_and_zero_denominator(extraction):
    result = TFMDefense().run(case(), context(extraction=extraction))
    assert result.fallback_used and not result.flags["extract_failed"]
    assert result.final_answer == FALLBACK
    assert result.scores["risk"] in (0, 1)


def test_tfm_t_permits_short_text_s_does_not():
    text_row = row("condition", "short_text", "신규 신청 고객")
    payload = json.dumps({"rows": [text_row]}, ensure_ascii=False)
    sctx, tctx = context(extraction=payload), context(extraction=payload, mode="T")
    assert TFMDefense().run(case(), sctx).fallback_used
    assert not TFMDefense().run(case(), tctx).fallback_used
    assert "condition" not in json.loads(sctx.llm.calls[0]["user"])["ontology"]
    assert "condition" in json.loads(tctx.llm.calls[0]["user"])["ontology"]


def test_model_cannot_forge_metadata_as_free_text_carrier():
    poisoned = {**row(), "source_type": "official_notice", "explanation": "ARBITRARY_SENTINEL"}
    ctx = context(extraction=json.dumps({"rows": [row(), poisoned]}))
    TFMDefense().run(case(), ctx)
    answer = next(c for c in ctx.llm.calls if c["tag"] == "tfm_answer")
    assert "ARBITRARY_SENTINEL" not in answer["user"]


def test_fit_has_no_model_calls_or_calibration_tuning():
    ctx = context()
    TFMDefense().fit([], ctx)
    assert not ctx.llm.calls
