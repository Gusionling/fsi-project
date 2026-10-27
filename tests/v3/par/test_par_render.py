from eval.v3.candidates.par import render
from eval.v3.candidates.par.render import Piece


def test_assemble_keeps_text_and_replaces_with_constants():
    out = render.assemble([Piece(text="안내입니다."), Piece(replace_type="completion_claim"), Piece(text="감사합니다.")])
    assert out == f"안내입니다. {render.FALLBACK_COMPLETION} 감사합니다."


def test_same_type_template_once_different_types_both():
    out = render.assemble([Piece(replace_type="completion_claim"), Piece(replace_type="completion_claim"), Piece(replace_type="credential_request")])
    assert out == f"{render.FALLBACK_COMPLETION} {render.FALLBACK_CREDENTIAL}"


def test_templates_contain_no_entities_or_completion_claims():
    for t in (render.FALLBACK_COMPLETION, render.FALLBACK_CREDENTIAL, render.PARSE_FAILED_ANSWER, render.GATE_BLOCKED_ANSWER):
        assert "http" not in t and not any(ch.isdigit() for ch in t)
    assert "완료되었" not in render.FALLBACK_COMPLETION and "입력해 주세요" not in render.FALLBACK_CREDENTIAL
