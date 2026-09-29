"""LLM 호출 단일 진입점.

프로젝트의 모든 LLM 호출은 call_llm/call_embedding 을 통해서만 한다. 같은 인터페이스에 아래 세 가지를 얹는다.
  (a) 테스트용 가짜 클라이언트 — 단위 테스트가 API 없이 돈다
  (b) 디스크 캐시(.llm_cache/) — 평가 반복 시 비용 방지
  (c) 오프라인 재생 모드 — 데모의 --offline 과 동일한 경로
"""
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()

CACHE_DIR = Path(".llm_cache")
_MISSING = object()

_client_override: Any = None
_openai_client: Any = None


class FakeLLMClient:
    """테스트용 가짜 클라이언트. chat_fn/embed_fn으로 원하는 응답을 주입한다."""

    def __init__(
        self,
        chat_fn: Callable[[str, bool], Any] | None = None,
        embed_fn: Callable[[str], list[float]] | None = None,
    ) -> None:
        self._chat_fn = chat_fn or (lambda prompt, json_mode: {"unexpected_span": None} if json_mode else "fake response")
        self._embed_fn = embed_fn or (lambda text: [0.0, 0.0, 0.0])

    def chat(self, prompt: str, model: str, json_mode: bool) -> Any:
        return self._chat_fn(prompt, json_mode)

    def embed(self, text: str, model: str) -> list[float]:
        return self._embed_fn(text)


class _OpenAIClient:
    def __init__(self) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    def chat(self, prompt: str, model: str, json_mode: bool) -> Any:
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        resp = self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        content = resp.choices[0].message.content
        return json.loads(content) if json_mode else content

    def embed(self, text: str, model: str) -> list[float]:
        resp = self._client.embeddings.create(model=model, input=text)
        return resp.data[0].embedding


def set_client(client: Any) -> None:
    """테스트에서 가짜 클라이언트를 주입할 때 사용. None이면 환경변수 기반 실제 클라이언트로 되돌린다."""
    global _client_override
    _client_override = client


def _resolve_client() -> Any:
    global _openai_client
    if _client_override is not None:
        return _client_override
    provider = os.environ.get("LLM_PROVIDER", "openai")
    if provider == "openai":
        if _openai_client is None:
            _openai_client = _OpenAIClient()
        return _openai_client
    if provider == "anthropic":
        raise NotImplementedError("anthropic 클라이언트는 아직 구현되지 않았다")
    raise ValueError(f"알 수 없는 LLM_PROVIDER: {provider}")


def _is_offline() -> bool:
    return os.environ.get("LLM_OFFLINE", "").lower() in ("1", "true", "yes")


def _cache_key(kind: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"{kind}_{digest}"


def _read_cache(key: str) -> Any:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return _MISSING
    return json.loads(path.read_text(encoding="utf-8"))["value"]


def _write_cache(key: str, value: Any) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    path.write_text(json.dumps({"value": value}, ensure_ascii=False), encoding="utf-8")


def call_llm(prompt: str, json_mode: bool = False) -> Any:
    """json_mode=True 이면 파싱된 dict 를, 아니면 문자열을 반환한다."""
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    key = _cache_key("chat", {"prompt": prompt, "model": model, "json_mode": json_mode})
    cached = _read_cache(key)
    if cached is not _MISSING:
        return cached
    if _is_offline():
        raise RuntimeError(f"오프라인 모드: 캐시에 없는 요청이다 (key={key})")
    result = _resolve_client().chat(prompt, model=model, json_mode=json_mode)
    _write_cache(key, result)
    return result


def call_embedding(text: str) -> list[float]:
    """텍스트를 임베딩 벡터로 변환한다. cluster_by_similarity 등 의미 유사도 계산에 쓴다."""
    model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    key = _cache_key("embedding", {"text": text, "model": model})
    cached = _read_cache(key)
    if cached is not _MISSING:
        return cached
    if _is_offline():
        raise RuntimeError(f"오프라인 모드: 캐시에 없는 요청이다 (key={key})")
    result = _resolve_client().embed(text, model=model)
    _write_cache(key, result)
    return result
