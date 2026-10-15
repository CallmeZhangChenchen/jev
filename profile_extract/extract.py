#!/usr/bin/env python3
"""用判别式决策模型(Intern-Decision-4B / jev)从历史对话中提取 profile_data 的枚举字段

原理:两个模型都只有 choice|score|noul 类型,不能生成自由文本,
因此只处理"候选值可枚举"的字段(choice);URL/列表/单一取值字段自动跳过。

- Intern-Decision-4B: POST /predict,一次调用带全部字段的 question,
  choice 的 criteria 必须是 dict {候选值: 描述}
- jev:                POST /decide,一次只带一个 question,
  choice 的 criteria 用 list

字段发现规则(自动,从全量真值统计):
  1. 取值必须是标量(列表/字典跳过)
  2. 非空取值 >= 2 种(单一取值无判定意义)且 <= 8 种(非枚举跳过)
  3. 链接类取值(http/小程序://)只在"全部会话为同一个固定值"时保留

真值取自抓取时刻的 profile_data 快照(含对话外系统侧更新),完美准确率未必 100%。

用法:
  python3 extract.py                       # v4/v5 各前100条,两个模型
  python3 extract.py --file v4 --model jev --limit 100
"""
import argparse
import json
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DIR = Path(__file__).resolve().parent
DATA_FILES = {
    "v4": "/Users/zcc/Downloads/yixin/jev/all_memory_messages_filtered_v4.json",
    "v5": "/Users/zcc/Downloads/yixin/jev/all_memory_messages_filtered_v5.json",
}
PREDICT_URL = "http://10.10.200.201:8000/predict"   # Intern-Decision-4B
DECIDE_URL = "http://10.10.200.201:8000/decide"     # jev
CLEF_URL = "http://localhost:30000/v1/systemone"    # clef
INTERN_MODEL = "Intern-Decision-4B"
CLEF_MODEL = "Cloudflare/clef"
EMPTY_LABEL = "未提供"        # 空字符串取值的候选标签
MSG_CHAR_CAP = None           # 单条消息截断(None=不截断)
CTX_CHAR_CAP = None           # 整段对话截断(None=不截断;实测前100条最长 13226 字符)
WORKERS = 8
RESULT_DIR = DIR / "results"


def http_json(url, payload, timeout=120):
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def label(v):
    s = str(v)
    return EMPTY_LABEL if s == "" else s


def build_context(msgs):
    lines = []
    for m in msgs:
        c = (m.get("content") or "").strip().replace("\n", " ")
        if c:
            line = f'{m.get("role")}: {c}'
            if MSG_CHAR_CAP:
                line = line[:MSG_CHAR_CAP]
            lines.append(line)
    ctx = "\n".join(lines)
    if CTX_CHAR_CAP and len(ctx) > CTX_CHAR_CAP:
        ctx = ctx[-CTX_CHAR_CAP:]
    return ctx


def truth_map(session):
    """合并多 agent 的 profile_data -> {字段: 值}"""
    pd = (session.get("profile_data") or {}).get("profile_data") or {}
    merged = {}
    for fields in pd.values():
        for f, v in (fields or {}).items():
            merged[f] = v
    return merged


def discover_fields(sessions):
    """从全量真值自动发现可判定枚举字段 -> {字段: [候选值(已做空值标签)]}"""
    vals = defaultdict(set)
    for s in sessions:
        for f, v in truth_map(s).items():
            if isinstance(v, (str, int, float)) and str(v) != "":
                vals[f].add(str(v))
    keep = {}
    for f, vs in vals.items():
        if len(vs) < 2:
            print(f"  跳过字段 {f}: 单一取值 {vs}, 无可判定性")
            continue
        if len(vs) > 8:
            print(f"  跳过字段 {f}: {len(vs)} 种取值, 非枚举")
            continue
        links = [v for v in vs if "http" in v or v.startswith("#小程序://")]
        if len(links) > 1:
            print(f"  跳过字段 {f}: {len(links)} 个互不相同的链接, 模型无法生成")
            continue
        keep[f] = sorted(label(v) for v in vs)
    return keep


def instr(field):
    return (f"根据客服与用户的对话,判断该客户当前的【{field}】。"
            f"只依据对话中明确表达的信息,从候选中选出最符合当前状态的一项。")


def pack(session, fields, preds, err, latency):
    truth = truth_map(session)
    per_field = {}
    for f in fields:
        tv = truth.get(f)
        t = label(tv) if tv is not None else None  # None=该会话真值缺失,不计入准确率
        p = preds.get(f)
        per_field[f] = {"truth": t, "pred": p,
                        "confidence": preds.get(f + "|conf"), "ok": t is not None and p == t}
    return {"session_id": session["session_id"], "latency_ms": int(latency * 1000),
            "error": err, "fields": per_field}


def run_threads(tasks, fn, tag):
    """tasks: [(session, field_or_fields)];fn(task) -> pack 结果"""
    results, done, lock = [], [0], __import__("threading").Lock()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(fn, tasks):
            results.append(r)
            with lock:
                done[0] += 1
                if done[0] % 20 == 0 or done[0] == len(tasks):
                    print(f"\r  {tag} {done[0]}/{len(tasks)}", end="", flush=True)
    print()
    return results


def run_systemone(sessions, fields, url, model, tag):
    """Intern-Decision-4B / clef 共用:每 session 一次调用,带全部字段

    两者同属 systemone 协议,questions dict 多字段,choice criteria 必须是 dict。
    """
    def one(s):
        questions = {f: {"type": "choice", "instructions": instr(f),
                         "criteria": {v: v for v in opts}}
                     for f, opts in fields.items()}
        t0 = time.time()
        try:
            data = http_json(url, {"model": model,
                                   "state": build_context(s["chat_messages"]),
                                   "questions": questions})
            answers = data.get("answers", {})
            preds = {}
            for f in fields:
                a = answers.get(f, {})
                preds[f] = a.get("choice")
                preds[f + "|conf"] = a.get("confidence")
            err = "" if answers else "响应无 answers"
        except Exception as e:
            preds, err = {}, f"{type(e).__name__}: {e}"
        return pack(s, fields, preds, err, time.time() - t0)
    return run_threads(sessions, one, f"[{tag}]")


def run_intern(sessions, fields):
    """Intern-Decision-4B: POST /predict"""
    return run_systemone(sessions, fields, PREDICT_URL, INTERN_MODEL, INTERN_MODEL)


def run_clef(sessions, fields):
    """clef: POST /v1/systemone,与 Intern 同协议"""
    return run_systemone(sessions, fields, CLEF_URL, CLEF_MODEL, "clef")


def run_jev(sessions, fields):
    """jev: 每字段一次 /decide(choice, list 候选),响应取 result.choice"""
    tasks = [(s, f) for s in sessions for f in fields]
    partial = defaultdict(dict)

    def one(task):
        s, f = task
        t0 = time.time()
        try:
            data = http_json(DECIDE_URL, {"context": build_context(s["chat_messages"]),
                                          "question": {"type": "choice",
                                                       "instructions": instr(f),
                                                       "criteria": fields[f]}})
            result = data.get("result", {})
            pred, conf = result.get("choice"), result.get("confidence")
            err = "" if pred is not None else f"响应无 choice: {result}"
        except Exception as e:
            pred, conf, err = None, None, f"{type(e).__name__}: {e}"
        return s["session_id"], f, pred, conf, err, time.time() - t0

    raw = run_threads(tasks, one, "[jev]")
    lat = defaultdict(list)
    errors = {}
    for sid, f, pred, conf, err, dt in raw:
        partial[sid][f] = pred
        partial[sid][f + "|conf"] = conf
        lat[f].append(dt)
        if err:
            errors[(sid, f)] = err
    out = []
    for s in sessions:
        sid = s["session_id"]
        out.append(pack(s, fields, partial[sid], "; ".join(
            f"{f}: {errors[(sid, f)]}" for f in fields if (sid, f) in errors),
            sum(lat[f][0] for f in fields)))
    return out


def summarize(file_key, model, fields, results):
    stat = {f: [0, 0] for f in fields}  # [对, 总(真值存在)]
    errors = 0
    for r in results:
        if r["error"]:
            errors += 1
        for f, v in r["fields"].items():
            if v["truth"] is not None:
                stat[f][1] += 1
                stat[f][0] += v["ok"]
    lat = [r["latency_ms"] for r in results if not r["error"]]
    return {"file": file_key, "model": model,
            "fields": {f: {"correct": c, "total": t,
                           "acc": round(c / t * 100, 1) if t else None}
                       for f, (c, t) in stat.items()},
            "micro": {"correct": sum(c for c, _ in stat.values()),
                      "total": sum(t for _, t in stat.values())},
            "errors": errors,
            "avg_latency_ms": round(sum(lat) / len(lat)) if lat else None,
            "results": results}


def main():
    ap = argparse.ArgumentParser(description="从历史对话提取 profile_data(仅枚举字段)")
    ap.add_argument("--file", default="both", choices=["v4", "v5", "both"])
    ap.add_argument("--model", default="clef",
                    choices=["Intern-Decision-4B", "jev", "clef", "both", "all"])
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    RESULT_DIR.mkdir(exist_ok=True)
    files = list(DATA_FILES) if args.file == "both" else [args.file]
    _ALL = [INTERN_MODEL, "jev", "clef"]
    models = _ALL if args.model in ("all", "both") \
        else [args.model]

    summaries = []
    for fk in files:
        sessions = json.load(open(DATA_FILES[fk], encoding="utf-8"))["data"][:args.limit]
        print(f"\n===== {fk}: 前 {len(sessions)} 条 =====")
        fields = discover_fields(json.load(open(DATA_FILES[fk], encoding="utf-8"))["data"])
        print(f"  可提取字段({len(fields)}): {fields}")
        for model in models:
            print(f"-- {model} --")
            t0 = time.time()
            results = run_intern(sessions, fields) if model == INTERN_MODEL \
                else run_clef(sessions, fields) if model == "clef" \
                else run_jev(sessions, fields)
            summ = summarize(fk, model, fields, results)
            summ["elapsed_s"] = round(time.time() - t0, 1)
            summaries.append(summ)
            out = RESULT_DIR / f"extract_{fk}_{model}.json"
            with open(out, "w", encoding="utf-8") as f:
                json.dump(summ, f, ensure_ascii=False, indent=2)
            print(f"  明细: {out}")

    # 汇总表
    lines = ["# profile_data 提取准确率(仅枚举字段)", ""]
    print("\n" + "=" * 76)
    print(f"{'文件':<5}{'模型':<20}{'字段':<16}{'准确率':>10}{'样本':>8}")
    print("-" * 76)
    for s in summaries:
        for f, v in s["fields"].items():
            acc = f"{v['acc']}%" if v["acc"] is not None else "-"
            print(f"{s['file']:<5}{s['model']:<20}{f:<16}{acc:>10}{v['total']:>8}")
            lines.append(f"| {s['file']} | {s['model']} | {f} | {acc} | {v['total']} |")
        micro = s["micro"]
        macc = f"{micro['correct'] / micro['total'] * 100:.1f}%" if micro["total"] else "-"
        print(f"{'':<5}{s['model']:<20}{'-- 合计 --':<16}{macc:>10}{micro['total']:>8}"
              f"  (耗时 {s['elapsed_s']}s, 异常 {s['errors']})")
        lines.append(f"| {s['file']} | {s['model']} | **合计** | **{macc}** | {micro['total']} |")
    print("=" * 76)
    header = "| 文件 | 模型 | 字段 | 准确率 | 样本 |\n|---|---|---|---|---|"
    with open(RESULT_DIR / "summary.md", "w", encoding="utf-8") as f:
        f.write(header + "\n" + "\n".join(lines) + "\n")
    print(f"汇总: {RESULT_DIR / 'summary.md'}")


if __name__ == "__main__":
    main()
