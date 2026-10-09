"""C2 추출기 — 프롬프트 파일 로더 + 해시 검증 + 실제 추출기 API 호출.

추출 프롬프트는 eval/mech_search/c2_extract_prompt.txt 단일 파일에서 읽는다.
문서(docs/decision_protocol_v3.md §1.2)는 본문을 복사해 두지 않고 파일 경로와
바이트 기준 SHA-256만 적는다 — 본문과 해시가 따로 보관되다가 어긋나는 사고
(2026-10-10 erratum, §10)를 구조적으로 막기 위함이다.

실행(추출기 API 호출) 전에 반드시 load_extract_prompt()로 해시를 확인하고,
다르면 API 호출을 하지 않고 즉시 중단한다.

모델 역할(§8에서 확정, 아래 상수)과 드리프트 검사(ModelRun/ModelDriftError)도
여기 둔다. call_extractor()가 실제 API 호출을 수행한다(§12 실행 방침).
"""
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

PROMPT_PATH = Path(__file__).resolve().parent / "c2_extract_prompt.txt"

# docs/decision_protocol_v3.md §1.2에 기재된 값과 반드시 같아야 한다. 이 상수와
# 파일이 어긋나면 프롬프트가 동결 시점과 달라졌다는 뜻이므로 API를 호출하지 않는다.
EXPECTED_PROMPT_HASH = "3ee5390c3789fc071d3ade061473e691f23d1d2f4ae4891ec94449892f4464e1"

# docs/decision_protocol_v3.md §8에서 확정한 역할. 날짜 포함 스냅샷 ID가 이
# 키/조직에는 노출되지 않아 별칭으로만 고정한다(한계, §8 참고).
PRIMARY_MODEL = "gpt-4.1-mini"  # 1차: (a)(b)(c) 전부 이 모델 결과로만 계산한다
SECONDARY_MODEL = "o4-mini"  # 2차: (d) 교차 모델 일치도 κ 전용
# 판정(a)~(d) 어디에도 쓰지 않는다. 돌릴 경우 결과는 별도 표로만 보고한다(§8).
EXCLUDED_AUX_MODEL = "gpt-5.6-luna"

MAX_TRANSPORT_RETRIES = 3  # §12.3: 전송 계층 오류(네트워크/429/5xx)만 재시도한다.
REQUEST_TIMEOUT = 60.0


class PromptHashMismatch(RuntimeError):
    """c2_extract_prompt.txt의 해시가 문서 기재값과 다를 때 발생시킨다 — API 호출 전 중단용."""


class ModelDriftError(RuntimeError):
    """한 번의 실행(run) 중 API가 실제로 돌려준 모델명(response.model)이 바뀌면 발생시킨다.

    별칭(alias)만 노출되는 환경이라 모델을 스냅샷으로 고정할 수 없다(§8 한계) — 그
    대신 실행 중 실제 모델명이 바뀌는지를 감시해서, 바뀌면 그 실행 전체를 무효
    처리하고 중단한다.
    """


class ModelRun:
    """한 번의 실행 동안 호출마다 돌아온 response.model을 기록하고 드리프트를 검사한다.

    §12.3: 동시 호출(스레드풀)에서도 동작해야 하므로 record()는 락으로 보호한다.
    API 호출 없이 순수 로직만 테스트할 수 있도록 record()는 모델명 문자열만 받는다
    (실제 API 응답 객체에서 response.model을 꺼내 넘기는 건 호출부의 책임).
    """

    def __init__(self, expected_model: str):
        self.expected_model = expected_model
        self.seen_models: list[str] = []
        self._lock = threading.Lock()

    def record(self, actual_model: str) -> None:
        with self._lock:
            self.seen_models.append(actual_model)
            first = self.seen_models[0]
            if first != actual_model:
                raise ModelDriftError(
                    f"실행 중 실제 모델명이 바뀌었다 (처음: {first!r}, "
                    f"이번: {actual_model!r}). 이 실행 전체를 무효 처리한다."
                )


def actual_prompt_hash() -> str:
    return hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()


def load_extract_prompt(verify: bool = True) -> str:
    """프롬프트 텍스트를 반환한다. verify=True(기본)면 해시가 다르면 예외를 던진다."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    if verify:
        actual = actual_prompt_hash()
        if actual != EXPECTED_PROMPT_HASH:
            raise PromptHashMismatch(
                f"{PROMPT_PATH.name} 해시가 문서 기재값과 다르다 "
                f"(기대: {EXPECTED_PROMPT_HASH}, 실제: {actual}). API 호출 전에 중단한다."
            )
    return text


_TRANSPORT_ERROR_NAMES = (
    "APIConnectionError",
    "APITimeoutError",
    "RateLimitError",
    "InternalServerError",
    "APIStatusError",
)


def _is_transport_error(exc: Exception) -> bool:
    return type(exc).__name__ in _TRANSPORT_ERROR_NAMES


def _is_temperature_unsupported(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "temperature" in msg and ("unsupported" in msg or "not support" in msg or "does not support" in msg)


_client_lock = threading.Lock()
_client: Any = None


def _get_client() -> Any:
    global _client
    with _client_lock:
        if _client is None:
            from openai import OpenAI

            _client = OpenAI(
                api_key=os.environ.get("OPENAI_API_KEY"),
                timeout=REQUEST_TIMEOUT,
                max_retries=0,  # 재시도는 call_extractor가 전송 계층 오류에만 직접 담당한다
            )
        return _client


def call_extractor(response_text: str, model: str, temperature: float | None = 0) -> dict[str, Any]:
    """추출기 API를 1회 호출한다(전송 계층 오류만 최대 MAX_TRANSPORT_RETRIES회 재시도).

    반환 딕셔너리:
      actual_model: API가 실제로 돌려준 모델명(response.model)
      used_temperature: 실제로 전달된 temperature(None이면 모델이 거부해 생략했다는 뜻)
      temperature_fallback: 위 생략이 실제로 일어났는지
      extraction: 파싱된 JSON(dict) 또는 None(파싱/스키마 실패 시)
      schema_error: JSON 파싱 자체가 실패했는지(확장 필드 검증은 c2_sink.decide_response가 함)
      raw_content: API가 돌려준 원문 문자열
    """
    prompt = load_extract_prompt(verify=True).format(response=response_text)
    client = _get_client()
    kwargs = {"response_format": {"type": "json_object"}}
    used_temperature = temperature
    temperature_fallback = False

    def _do_call(with_temperature: bool):
        call_kwargs = dict(kwargs)
        if with_temperature and temperature is not None:
            call_kwargs["temperature"] = temperature
        return client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            **call_kwargs,
        )

    last_exc: Exception | None = None
    resp = None
    for attempt in range(MAX_TRANSPORT_RETRIES):
        try:
            resp = _do_call(with_temperature=True)
            break
        except Exception as exc:  # noqa: BLE001 - 아래서 종류별로 분기한다
            if _is_temperature_unsupported(exc):
                used_temperature = None
                temperature_fallback = True
                try:
                    resp = _do_call(with_temperature=False)
                    break
                except Exception as exc2:  # noqa: BLE001
                    if _is_transport_error(exc2) and attempt < MAX_TRANSPORT_RETRIES - 1:
                        last_exc = exc2
                        time.sleep(2**attempt)
                        continue
                    raise
            if _is_transport_error(exc):
                last_exc = exc
                if attempt < MAX_TRANSPORT_RETRIES - 1:
                    time.sleep(2**attempt)
                    continue
                raise
            # 전송 계층 오류가 아니면(예: 인증 오류 등) 재시도하지 않고 즉시 전파한다.
            raise

    if resp is None:
        raise last_exc  # type: ignore[misc]

    actual_model = resp.model
    content = resp.choices[0].message.content
    extraction: Any = None
    schema_error = False
    try:
        extraction = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        schema_error = True

    return {
        "actual_model": actual_model,
        "used_temperature": used_temperature,
        "temperature_fallback": temperature_fallback,
        "extraction": extraction,
        "schema_error": schema_error,
        "raw_content": content,
    }
