"""数据集加载、跑批与指标计算"""
import json
from pathlib import Path

from base import ModelBackend

# model_compare/cases
CASES_DIR = Path(__file__).parent / "cases"


def load_cases(name):
    with open(CASES_DIR / f"{name}.json", "r", encoding="utf-8") as f:
        return json.load(f).get("cases", [])


def _preview_first(backend: ModelBackend, sample, group, expect_hit):
    """每个数据集分组开跑前打印该组第一条的完整入参/出参,方便观测。"""
    r = backend.judge(sample["text"])
    print("\n" + "-" * 72)
    print(f"[{backend.name}] {group} 首条样本预览")
    print("-" * 72)
    print("入参 text:")
    print(sample["text"])
    if sample.get("expect_category"):
        print(f"期望类别: {sample['expect_category']}")
    print(f"期望结果: {'命中' if expect_hit else '放行'}")
    model_request = getattr(backend, "last_request", "")
    if model_request:
        print("模型完整入参:")
        print(model_request)
    print("出参:")
    print(f"  hit(命中违规): {r.hit}")
    print(f"  categories: {r.categories}")
    print(f"  latency_ms: {r.latency_ms}")
    if r.error:
        print(f"  error: {r.error}")
    print("  raw:")
    print(f"    {r.raw}")
    print("-" * 72 + "\n")


def run_backend(backend: ModelBackend, pos_cases, neg_cases):
    records, errors = [], 0

    def feed(cases, expect_hit, group):
        nonlocal errors
        total = len(cases)
        if cases:
            _preview_first(backend, cases[0], group, expect_hit)
        for i, case in enumerate(cases, start=1):
            text = case["text"]
            print(f"\r[{backend.name}] {group} {i}/{total}", end="", flush=True)
            r = backend.judge(text)
            if r.error:
                errors += 1
            correct = (r.hit == expect_hit) and not r.error
            records.append({
                "group": group,
                "text": text,
                "expect_hit": expect_hit,
                "expect_category": case.get("expect_category"),
                "hit": r.hit,
                "categories": r.categories,
                "unclassified_hit": r.unclassified_hit,
                "correct": correct,
                "latency_ms": r.latency_ms,
                "error": r.error,
                "raw": r.raw,
            })
        print()

    feed(pos_cases, True, "正例")
    feed(neg_cases, False, "负例")

    pos = [r for r in records if r["group"] == "正例"]
    neg = [r for r in records if r["group"] == "负例"]
    pos_ok = sum(r["correct"] for r in pos)
    neg_ok = sum(r["correct"] for r in neg)

    # 分类别正例命中率:按 expect_category 分组,组内被判违规(hit)的比例即该类召回。
    # 模型只需判违规/合规,不需要输出类别。
    cat_hit = {}
    for r in pos:
        cat = r["expect_category"] or "未标注"
        slot = cat_hit.setdefault(cat, [0, 0])  # 判违规数 / 总数
        slot[1] += 1
        if r["hit"]:
            slot[0] += 1

    latencies = [r["latency_ms"] for r in records if not r["error"]]
    return {
        "model": backend.name,
        "positive_hit": {"ok": pos_ok, "total": len(pos)},
        "negative_pass": {"ok": neg_ok, "total": len(neg)},
        "accuracy": {"ok": pos_ok + neg_ok, "total": len(records)},
        "errors": errors,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "category_hit": {c: {"hit": v[0], "total": v[1]}
                         for c, v in sorted(cat_hit.items())},
        "records": records,
    }
