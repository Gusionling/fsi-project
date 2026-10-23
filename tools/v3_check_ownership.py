#!/usr/bin/env python3
"""v3 소유권 검사: 변경된 파일이 모두 자기 소유 경로 안에 있는지 확인한다.

사용 예 (레포 루트에서):
    python tools/v3_check_ownership.py --owner harness
    python tools/v3_check_ownership.py --owner dsnt --owner tfm --base origin/main

종료 코드 0 = 통과, 1 = 위반, 2 = 사용 오류.
커밋·푸시(또는 PR 생성) 전에 반드시 실행한다. 이 파일은 main 에서만 수정한다.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from typing import Dict, List

OWNERS: Dict[str, List[str]] = {
    "harness": [
        "eval/v3/common/",
        "tests/v3/common/",
        "eval/v3/results/_common/",
        "docs/validation_v3/results/harness.md",
    ],
    "data": [
        "eval/v3/data/",
        "tests/v3/data/",
        "docs/validation_v3/results/data.md",
    ],
    "par": [
        "eval/v3/candidates/par/",
        "tests/v3/par/",
        "eval/v3/results/par/",
        "docs/validation_v3/results/par.md",
    ],
    "dsnt": [
        "eval/v3/candidates/dsnt/",
        "tests/v3/dsnt/",
        "eval/v3/results/dsnt/",
        "docs/validation_v3/results/dsnt.md",
    ],
    "tfm": [
        "eval/v3/candidates/tfm/",
        "tests/v3/tfm/",
        "eval/v3/results/tfm/",
        "docs/validation_v3/results/tfm.md",
    ],
}


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    return out.stdout


def changed_files(base: str) -> List[str]:
    files = set()
    try:
        merge_base = _git("merge-base", base, "HEAD").strip()
        committed = _git("diff", "--name-only", f"{merge_base}", "HEAD")
    except subprocess.CalledProcessError:
        print(f"[error] 기준 브랜치 '{base}' 를 찾을 수 없습니다. `git fetch` 후 다시 실행하세요.", file=sys.stderr)
        sys.exit(2)
    files.update(line for line in committed.splitlines() if line)
    # 아직 커밋하지 않은 변경·신규 파일도 함께 본다
    for line in _git("status", "--porcelain").splitlines():
        path = line[3:]
        if " -> " in path:  # rename
            path = path.split(" -> ")[-1]
        files.add(path.strip().strip('"'))
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--owner", action="append", required=True, choices=sorted(OWNERS), help="소유자 이름(여러 번 가능)")
    parser.add_argument("--base", default="origin/main", help="비교 기준 브랜치 (기본: origin/main)")
    args = parser.parse_args()

    allowed: List[str] = []
    for owner in args.owner:
        allowed.extend(OWNERS[owner])

    violations = []
    for path in changed_files(args.base):
        if path.startswith(".cache/") or "/__pycache__/" in path or path.endswith(".pyc"):
            continue
        if not any(path == p or (p.endswith("/") and path.startswith(p)) for p in allowed):
            violations.append(path)

    if violations:
        print("[FAIL] 소유 경로 밖의 변경이 있습니다:")
        for v in violations:
            print(f"  - {v}")
        print("\n허용 경로:")
        for p in allowed:
            print(f"  + {p}")
        print("\n이 변경을 되돌리거나, 정말 필요하면 REPORT 에 '계약 변경 요청'으로 적고 사용자에게 맡기세요.")
        return 1
    print(f"[OK] 모든 변경이 소유 경로({', '.join(args.owner)}) 안에 있습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
