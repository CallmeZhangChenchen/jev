"""多模型质检效果对比实验(独立版,从 agentengine 仓库抽出)

与仓库版 model_compare.py 的差异:
  - qc_config 不再走 MySQL(QCConfigRepository),改为读本地 config.json
    (由仓库预加载 dump,见 qc_config.py 头部注释;配置更新后需重新 dump)
  - cases 由 yaml 转为 json(去掉 pyyaml 依赖),内容一致
  - Qwen3.8(qc_inspector)后端去掉 aisuite 依赖,直接 HTTP 调 OpenAI 兼容接口
  - 仅依赖标准库,系统 python3 即可运行

用法(在本目录下):
  # 默认 nimble 后端,数据集 positive3 + negative1
  python3 model_compare.py

  # 只跑指定模型(可选: nimble, laya, jev, Qwen3.8)
  python3 model_compare.py --models nimble,Qwen3.8

  # 指定数据集 / agent-id(仅用于报告标注,配置始终来自 config.json)
  python3 model_compare.py --positive positive3 --negative negative1 --agent-id 10001001

环境变量:
  TYPESAFE_API_KEY  jev 后端的 key(不设则用内置兜底 key)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qc_config import load_config
from base import BACKENDS
import backends  # noqa: F401  导入即注册全部后端
from runner import load_cases, run_backend
from report import print_comparison, write_reports

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def main():
    parser = argparse.ArgumentParser(description="多模型质检效果对比(独立版)")
    parser.add_argument("--models", default="nimble",
                        help="逗号分隔的后端名,可选: " + ",".join(BACKENDS.keys()))
    parser.add_argument("--positive", default="positive3")
    parser.add_argument("--negative", default="negative1")
    parser.add_argument("--agent-id", default="10001001",
                        help="仅用于报告标注;质检规则与模型配置来自本地 config.json")
    args = parser.parse_args()

    names = [n.strip() for n in args.models.split(",") if n.strip()]
    unknown = [n for n in names if n not in BACKENDS]
    if unknown:
        raise SystemExit(f"未知模型: {unknown}; 可选: {list(BACKENDS.keys())}")

    qc_config = load_config(CONFIG_PATH)
    print(f"前缀: {qc_config.agent_prefix}, 规则条数: {len(qc_config.rules)}, 配置模型: {qc_config.model}")

    pos_cases = load_cases(args.positive)
    neg_cases = load_cases(args.negative)
    print(f"数据集: 正例 {len(pos_cases)} 条, 负例 {len(neg_cases)} 条")

    results = []
    for name in names:
        print(f"\n====== 跑模型: {name} ======")
        backend = BACKENDS[name](qc_config)
        results.append(run_backend(backend, pos_cases, neg_cases))
        backend.close()

    print_comparison(results)
    write_reports(results, args)


if __name__ == "__main__":
    main()
