from dataclasses import replace
import pytest
from eval.v3.candidates.dsnt.defense import DSNTDefense, BLOCK_MESSAGE
from eval.v3.candidates.dsnt.conformal import InsufficientCalibrationWarning
from dsnt_stubs import case, context, calibration, Gates


@pytest.mark.parametrize("k", [5, 10])
@pytest.mark.parametrize("kind", ["edit", "embed"])
def test_question_context_unchanged_and_repeatable(k, kind):
    ctx = context(donors_k=k, dist_kind=kind)
    defense = DSNTDefense()
    defense.fit(calibration(), ctx)
    ctx.chatbot.calls.clear()
    original = case(text="different")
    before = list(original.chunks)
    first = defense.run(original, ctx)
    assert first == defense.run(original, ctx)
    assert first.blocked and first.final_answer == BLOCK_MESSAGE
    assert first.flags["p"] == .05 and first.scores["risk"] == .95
    assert first.flags["s"] > 0 and first.flags["m"] == 19
    assert len(first.flags["skeletons"]) == k + 1
    assert all(q == original.query and chunks[1] == before[1] for q, chunks in ctx.chatbot.calls)
    assert original.chunks == before
    assert all(topic == original.topic and count == k and excluded == ["target", "context"] and seed == 17
               for topic, count, excluded, seed in ctx.donors.calls)
    assert first.llm_calls == 2 + 1 + k + (kind == "embed")


def test_alpha_direction_and_small_calibration_abstains_without_donors():
    ctx = context(alpha=.1)
    defense = DSNTDefense()
    defense.fit(calibration(9), ctx)
    assert defense.run(case(text="different"), ctx).blocked
    ctx.config["alpha"] = .05
    calls = len(ctx.donors.calls)
    with pytest.warns(InsufficientCalibrationWarning):
        result = defense.run(case(text="different"), ctx)
    assert not result.intervened and not result.scores
    assert result.flags["dsnt_skipped"] == "insufficient_calibration"
    assert len(ctx.donors.calls) == calls


@pytest.mark.parametrize("b1,v4,answers,gates", [(True, False, 0, ["b1"]), (False, True, 1, ["b1", "v4"])])
def test_gates_short_circuit_dsnt(b1, v4, answers, gates):
    ctx = context()
    ctx.gates = Gates(b1, v4)
    result = DSNTDefense().run(case(), ctx)
    assert result.blocked
    assert len(ctx.chatbot.calls) == answers and ctx.gates.calls == gates
    assert not ctx.donors.calls and not ctx.llm.calls


def test_stack_b1_toggle_and_zero_distance_pass():
    ctx = context(stack_b1=False)
    defense = DSNTDefense()
    defense.fit(calibration(), ctx)
    result = defense.run(case(), ctx)
    assert ctx.gates.calls == ["v4"]
    assert result.flags["s"] == 0 and result.flags["p"] == 1
    assert not result.intervened


@pytest.mark.parametrize("split,label", [("dev", "normal"), ("calib", "attack"), ("calib", "integrity"), ("test_sealed", "normal")])
def test_fit_only_calib_normal_and_validate_all_before_calls(split, label):
    ctx = context()
    with pytest.raises(ValueError):
        DSNTDefense().fit([*calibration(1), case(split=split, label=label)], ctx)
    assert not ctx.chatbot.calls and not ctx.donors.calls


def test_changed_score_configuration_requires_refit():
    ctx = context()
    defense = DSNTDefense()
    defense.fit(calibration(), ctx)
    ctx.config["donors_k"] = 10
    with pytest.raises(ValueError, match="다시 fit"):
        defense.run(case(), ctx)


def test_all_targets_replaced_and_input_not_mutated():
    ctx = context()
    c = case()
    c = replace(c, chunks=[*c.chunks, replace(c.chunks[0], chunk_id="second")])
    defense = DSNTDefense()
    defense.fit([replace(c, split="calib", case_id=str(i)) for i in range(19)], ctx)
    ctx.chatbot.calls.clear()
    defense.run(c, ctx)
    variants = ctx.chatbot.calls[1:]
    assert len(variants) == 5
    for _, chunks in variants:
        assert chunks[0].chunk_id.startswith("donor_17") and chunks[2].chunk_id.startswith("donor_18")
        assert chunks[0].role == chunks[2].role == "target"
        assert chunks[1] == c.chunks[1]


@pytest.mark.parametrize("failure", ["short", "duplicate", "overlap"])
def test_bad_donor_pool_fails_explicitly(failure):
    ctx = context()
    donor = replace(case().chunks[0], chunk_id="d")
    ctx.donors.sample = lambda *args: [] if failure == "short" else [replace(donor, chunk_id="target" if failure == "overlap" else "d") for _ in range(5)]
    with pytest.raises(ValueError, match="donor"):
        DSNTDefense().fit(calibration(), ctx)


def test_no_fit_abstains():
    with pytest.warns(InsufficientCalibrationWarning):
        result = DSNTDefense().run(case(), context())
    assert not result.intervened and result.flags["m"] == 0
