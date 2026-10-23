"""v3 검증용 동결 인터페이스.

이 파일은 main 에서만 수정한다. 어떤 에이전트도 수정하지 않는다.
후보 방어(DSNT, TFM-L, PAR)와 기준선(L0~L2)은 모두 `Defense` 를 구현하고,
하네스(eval/v3/common)는 이 인터페이스만 보고 실행한다.

계약 전문은 docs/validation_v3/CONTRACT.md 를 본다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# 데이터 모델
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str
    role: str  # "target" | "context"
    source_type: Optional[str] = None  # official_notice | faq | internal_policy | unknown


@dataclass(frozen=True)
class Case:
    """검색이 끝난 상태의 한 케이스. 검색 단계는 평가에서 제외(고정)한다."""

    case_id: str
    split: str  # dev | calib | test_sealed
    label: str  # attack | normal | integrity
    query: str
    topic: str
    chunks: List[Chunk]
    attack: Optional[Dict[str, Any]] = None
    normal: Optional[Dict[str, Any]] = None
    integrity: Optional[Dict[str, Any]] = None
    trusted_fixture: Dict[str, Any] = field(default_factory=dict)
    author_model: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 서비스 인터페이스 (하네스가 구현해서 RunContext 로 넘긴다)
# ---------------------------------------------------------------------------


@runtime_checkable
class LLM(Protocol):
    """모든 LLM 호출은 이 인터페이스를 통해서만 한다 (캐시·비용 집계·오프라인 테스트용)."""

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        json_mode: bool = False,
        tag: str = "",
    ) -> str: ...

    def embed(self, texts: List[str], model: str = "text-embedding-3-small") -> List[List[float]]: ...


@runtime_checkable
class Chatbot(Protocol):
    """평가 대상 챗봇 (gpt-4o-mini + 방어적 시스템 프롬프트). 방어 없는 기본 경로."""

    def answer(self, query: str, chunks: List[Chunk]) -> str: ...

    def build_user_prompt(self, query: str, chunks: List[Chunk]) -> str:
        """청크를 프롬프트에 붙이는 방식. 생성 경로를 바꾸는 후보(PAR, TFM)가 같은 형식을 쓰도록 공개한다."""
        ...


@dataclass
class GateResult:
    blocked: bool
    score: float = 0.0  # B1 이면 0~100 위험도, V4 이면 공식 목록에 없는 엔티티 수
    detail: Dict[str, Any] = field(default_factory=dict)
    llm_calls: int = 0


@runtime_checkable
class Gates(Protocol):
    """L1 의 두 문(입구 B1, 출구 V4). 후보는 L1 을 통째로 감싸지 않고 이 문들을 조합해 쓴다."""

    def b1_chunk_gate(self, case: Case, ctx: "RunContext") -> GateResult:
        """각 청크를 B1 으로 판정. 하나라도 70 이상이면 blocked. score 는 최대 위험도."""
        ...

    def v4_answer_gate(self, case: Case, answer: str, ctx: "RunContext") -> GateResult:
        """답변 속 계좌·URL·전화번호가 공식 목록에 없으면 blocked. score 는 목록 밖 엔티티 수."""
        ...


@runtime_checkable
class TrustedStores(Protocol):
    """코퍼스와 분리된 신뢰 소스. 공격자가 오염시킬 수 없다는 가정의 저장소."""

    def application_status(self, case: Case, key: str) -> Optional[str]:
        """case.trusted_fixture['application_status'][key] 를 반환. 없으면 None."""
        ...

    def is_official_procedure(self, procedure_id: str) -> bool: ...

    def official_entities(self) -> Dict[str, List[str]]:
        """{'accounts': [...], 'urls': [...], 'phones': [...]} (eval/v3/data/registry/entities.json)."""
        ...


@runtime_checkable
class DonorPool(Protocol):
    """같은 주제의 정상 청크 풀 (DSNT 용). 평가 케이스의 청크와 겹치지 않는다."""

    def sample(self, topic: str, k: int, exclude_chunk_ids: List[str], seed: int) -> List[Chunk]: ...


@dataclass
class RunContext:
    llm: LLM
    chatbot: Chatbot
    trusted: TrustedStores
    donors: DonorPool
    gates: Gates
    chatbot_model: str = "gpt-4o-mini"
    chatbot_system_prompt: str = ""  # 하네스가 기존 챗봇의 시스템 프롬프트를 채워 넣는다
    seed: int = 0
    config: Dict[str, Any] = field(default_factory=dict)  # --set key=value 로 받은 설정


# ---------------------------------------------------------------------------
# 방어 인터페이스
# ---------------------------------------------------------------------------


@dataclass
class DefenseResult:
    final_answer: str
    # 방어가 고객 응답에 개입했는가 (아래 둘 중 하나라도 True 면 "개입")
    blocked: bool = False  # 거부·격리
    fallback_used: bool = False  # 안전 문구로 대체
    # 연속 점수가 있으면 "risk" 키에 넣는다 (높을수록 의심). 없으면 생략.
    scores: Dict[str, float] = field(default_factory=dict)
    # 진단용 (JSON 직렬화 가능해야 함)
    flags: Dict[str, Any] = field(default_factory=dict)
    llm_calls: int = 0

    @property
    def intervened(self) -> bool:
        return bool(self.blocked or self.fallback_used)


@runtime_checkable
class Defense(Protocol):
    name: str

    def fit(self, calib_cases: List[Case], ctx: RunContext) -> None:
        """calib split(정상 위주)으로 임계값을 정한다. 필요 없으면 아무것도 하지 않는다."""
        ...

    def run(self, case: Case, ctx: RunContext) -> DefenseResult:
        """한 케이스를 처리한다. 방어가 없으면 ctx.chatbot.answer 를 그대로 호출한다."""
        ...
