"""对比结果的终端展示与 JSON/Markdown 报告落盘"""
import json
from datetime import datetime
from pathlib import Path

# model_compare/logs
LOG_DIR = Path(__file__).parent / "logs"


def pct(ok, total):
    return f"{(ok / total * 100):.1f}%" if total else "-"


def print_comparison(results):
    print("\n" + "=" * 72)
    print("模型对比汇总")
    print("=" * 72)
    header = f"{'模型':<16}{'正例命中率':>12}{'负例放行率':>12}{'总准确率':>10}{'平均延迟ms':>12}{'异常':>5}"
    print(header)
    print("-" * 72)
    for r in results:
        print(f"{r['model']:<16}"
              f"{pct(r['positive_hit']['ok'], r['positive_hit']['total']):>12}"
              f"{pct(r['negative_pass']['ok'], r['negative_pass']['total']):>12}"
              f"{pct(r['accuracy']['ok'], r['accuracy']['total']):>10}"
              f"{(str(r['avg_latency_ms']) if r['avg_latency_ms'] is not None else '-'):>12}"
              f"{r['errors']:>5}")

    all_cats = sorted({c for r in results for c in r["category_hit"]})
    if all_cats:
        print("\n分类别正例命中率:")
        print(f"{'类别':<16}" + "".join(f"{r['model']:>18}" for r in results))
        for cat in all_cats:
            row = f"{cat:<16}"
            for r in results:
                v = r["category_hit"].get(cat)
                if v:
                    cell = f"{pct(v['hit'], v['total'])} ({v['hit']}/{v['total']})"
                else:
                    cell = "-"
                row += f"{cell:>20}"
            print(row)

    # 失败明细(只看每条 case 哪些模型错了)
    print("\n各模型不符合预期明细:")
    any_fail = False
    n = len(results[0]["records"]) if results else 0
    for i in range(n):
        bad = [r["model"] for r in results if not r["records"][i]["correct"]]
        if bad:
            any_fail = True
            rec = results[0]["records"][i]
            group = rec["group"]
            print(f"- [{group}] {'、'.join(bad)} | 期望:{'命中' if rec['expect_hit'] else '放行'} | {rec['text'][:60]}")
    if not any_fail:
        print("无")


def write_reports(results, args):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_file = LOG_DIR / f"compare_{stamp}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "agent_id": args.agent_id,
                   "datasets": {"positive": args.positive, "negative": args.negative},
                   "results": results}, f, ensure_ascii=False, indent=2)

    md_file = LOG_DIR / f"compare_{stamp}.md"
    lines = [f"# 质检模型对比报告  {datetime.now():%Y-%m-%d %H:%M:%S}", "",
             f"数据集: 正例 {args.positive} / 负例 {args.negative}  (agent_id={args.agent_id})", "",
             "| 模型 | 正例命中率 | 负例放行率 | 总准确率 | 平均延迟ms | 异常数 |",
             "|---|---|---|---|---|---|"]
    for r in results:
        lines.append(
            f"| {r['model']} | {pct(r['positive_hit']['ok'], r['positive_hit']['total'])} "
            f"({r['positive_hit']['ok']}/{r['positive_hit']['total']}) | "
            f"{pct(r['negative_pass']['ok'], r['negative_pass']['total'])} "
            f"({r['negative_pass']['ok']}/{r['negative_pass']['total']}) | "
            f"{pct(r['accuracy']['ok'], r['accuracy']['total'])} | "
            f"{r['avg_latency_ms']} | {r['errors']} |")
    all_cats = sorted({c for r in results for c in r["category_hit"]})
    if all_cats:
        lines += ["", "## 分类别正例命中率", "",
                  "| 类别 | " + " | ".join(r["model"] for r in results) + " |",
                  "|---|" + "---|" * len(results)]
        for cat in all_cats:
            row = [cat]
            for r in results:
                v = r["category_hit"].get(cat)
                if v:
                    cell = f"{pct(v['hit'], v['total'])} ({v['hit']}/{v['total']})"
                else:
                    cell = "-"
                row.append(cell)
            lines.append("| " + " | ".join(row) + " |")
    with open(md_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\nJSON 报告: {json_file}")
    print(f"Markdown 报告: {md_file}")
