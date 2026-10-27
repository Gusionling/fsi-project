"""코퍼스와 분리된 신뢰 소스 (CONTRACT §5.1).

- 엔티티 목록: <data_dir>/registry/entities.json  {"accounts": [...], "urls": [...], "phones": [...]}
- 공식 절차:   <data_dir>/registry/procedures.json [{"procedure_id", "name", "channel", "summary"}, ...]
- 처리 상태:   case.trusted_fixture["application_status"][key]  (케이스 청크와 분리된 모의 상태 DB)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from eval.v3.common.data_io import DEFAULT_DATA_DIR
from eval.v3.interfaces import Case

ENTITY_KEYS = ("accounts", "urls", "phones")


class FileTrustedStores:
    def __init__(self, data_dir: Union[str, Path, None] = None) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
        self._entities: Optional[Dict[str, List[str]]] = None
        self._procedure_ids: Optional[set] = None

    def application_status(self, case: Case, key: str) -> Optional[str]:
        status = (case.trusted_fixture or {}).get("application_status") or {}
        return status.get(key)

    def is_official_procedure(self, procedure_id: str) -> bool:
        if self._procedure_ids is None:
            path = self.data_dir / "registry" / "procedures.json"
            procs: List[Dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
            self._procedure_ids = {p["procedure_id"] for p in procs}
        return procedure_id in self._procedure_ids

    def official_entities(self) -> Dict[str, List[str]]:
        if self._entities is None:
            path = self.data_dir / "registry" / "entities.json"
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._entities = {k: [str(v) for v in raw.get(k, [])] for k in ENTITY_KEYS}
        return {k: list(v) for k, v in self._entities.items()}
