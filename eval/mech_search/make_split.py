"""C2 실험의 탐색/검증 50/50 분할을 만든다. 결과(C' 판정, C2 추출 결과)를 보기 전에
실행하고 ID 목록을 커밋한다. 층화 키: 정상은 source(+정책인접 group), 공격은 tier.

실행: python -m eval.mech_search.make_split
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

SEED = 42


def stratified_half(ids_by_stratum: dict, seed: int):
    rng = random.Random(seed)
    explore, verify = [], []
    for stratum, ids in sorted(ids_by_stratum.items()):
        ids = sorted(ids)
        rng.shuffle(ids)
        half = len(ids) // 2
        explore.extend(ids[:half])
        verify.extend(ids[half:])
        if len(ids) % 2 == 1:
            # 홀수면 탐색 쪽에 하나 더(탐색이 설계용이라 더 많이 봐도 무방)
            explore.append(ids[half * 2])
    return sorted(explore), sorted(verify)


def main():
    nb = json.loads((ROOT / "logs" / "normal_baseline_responses.json").read_text(encoding="utf-8"))
    pa = json.loads((ROOT / "logs" / "policy_adjacent_responses.json").read_text(encoding="utf-8"))

    normal_strata = defaultdict(list)
    for cid, entry in nb.items():
        normal_strata[f"nb:{entry['source']}"].append(cid)
    for cid, entry in pa.items():
        normal_strata[f"pa:{entry['group']}"].append(cid)

    run = json.loads(
        sorted((ROOT / "logs").glob("checkpoint3_holdout_run_*.json"))[-1].read_text(encoding="utf-8")
    )
    meta = run["holdout_meta"]
    attack_strata = defaultdict(list)
    for cid, m in meta.items():
        if m["intent"] == "info_exfil" and m["attack_class"] == "instruction_injection":
            attack_strata[f"tier:{m['tier']}"].append(cid)

    normal_explore, normal_verify = stratified_half(normal_strata, SEED)
    attack_explore, attack_verify = stratified_half(attack_strata, SEED)

    print("정상 층 구성:", {k: len(v) for k, v in sorted(normal_strata.items())})
    print(f"정상 탐색/검증: {len(normal_explore)}/{len(normal_verify)}")
    print("공격 층 구성:", {k: len(v) for k, v in sorted(attack_strata.items())})
    print(f"공격 탐색/검증: {len(attack_explore)}/{len(attack_verify)}")

    out = {
        "seed": SEED,
        "normal_explore": normal_explore,
        "normal_verify": normal_verify,
        "attack_info_exfil_explore": attack_explore,
        "attack_info_exfil_verify": attack_verify,
    }
    out_path = ROOT / "eval" / "mech_search" / "c2_split.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {out_path}")


if __name__ == "__main__":
    main()
