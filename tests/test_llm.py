"""src.llm 단위 테스트 — 가짜 클라이언트만 사용, 실제 API 호출 없음."""
import pytest

from src import llm


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path / ".llm_cache")
    monkeypatch.delenv("LLM_OFFLINE", raising=False)
    llm.set_client(None)
    yield
    llm.set_client(None)


def test_call_llm_text_mode_uses_fake_client():
    fake = llm.FakeLLMClient(chat_fn=lambda prompt, json_mode: f"echo:{prompt}")
    llm.set_client(fake)
    assert llm.call_llm("hello") == "echo:hello"


def test_call_llm_json_mode_returns_parsed_dict():
    fake = llm.FakeLLMClient(chat_fn=lambda prompt, json_mode: {"unexpected_span": None})
    llm.set_client(fake)
    assert llm.call_llm("prompt", json_mode=True) == {"unexpected_span": None}


def test_call_llm_caches_result_and_skips_second_call():
    calls = []

    def chat_fn(prompt, json_mode):
        calls.append(prompt)
        return "response"

    llm.set_client(llm.FakeLLMClient(chat_fn=chat_fn))
    llm.call_llm("same prompt")
    llm.call_llm("same prompt")
    assert len(calls) == 1


def test_call_llm_different_prompts_are_not_conflated():
    llm.set_client(llm.FakeLLMClient(chat_fn=lambda prompt, json_mode: f"echo:{prompt}"))
    assert llm.call_llm("a") == "echo:a"
    assert llm.call_llm("b") == "echo:b"


def test_call_embedding_uses_fake_client_and_caches():
    calls = []

    def embed_fn(text):
        calls.append(text)
        return [1.0, 2.0, 3.0]

    llm.set_client(llm.FakeLLMClient(embed_fn=embed_fn))
    v1 = llm.call_embedding("hi")
    v2 = llm.call_embedding("hi")
    assert v1 == v2 == [1.0, 2.0, 3.0]
    assert len(calls) == 1


def test_offline_mode_raises_on_cache_miss(monkeypatch):
    monkeypatch.setenv("LLM_OFFLINE", "1")
    llm.set_client(llm.FakeLLMClient())
    with pytest.raises(RuntimeError):
        llm.call_llm("never cached before")


def test_offline_mode_replays_cached_value(monkeypatch):
    llm.set_client(llm.FakeLLMClient(chat_fn=lambda prompt, json_mode: "cached response"))
    llm.call_llm("prompt to cache")

    monkeypatch.setenv("LLM_OFFLINE", "1")
    assert llm.call_llm("prompt to cache") == "cached response"


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "does-not-exist")
    with pytest.raises(ValueError):
        llm.call_llm("prompt that is not cached")
