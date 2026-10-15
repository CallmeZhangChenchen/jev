"""质检配置:从预加载的 JSON 读取(替代原仓库 MySQL 版的 QCConfigRepository)

配置由 agentengine 仓库预先 dump:
  .venv/bin/python -c "
  import sys; sys.path.insert(0, '.')
  from core.quality_inspection import QCConfigRepository
  cfg = QCConfigRepository().get_config('10001001')
  open('config.json', 'w').write(cfg.model_dump_json(indent=2))
  "
"""
import json


class QCRule:
    def __init__(self, d):
        self.scope = d.get("scope", "")
        self.category = d.get("category", "")
        self.level = d.get("level", "")
        self.words = d.get("words") or []
        self.llm_phrases = d.get("llm_phrases") or []
        self.explanation = d.get("explanation") or ""


class QCConfig:
    def __init__(self, d):
        self.agent_prefix = d.get("agent_prefix", "")
        self.enabled = d.get("enabled", True)
        self.dry_run = d.get("dry_run", False)
        self.retry_count = d.get("retry_count", 0)
        self.fail_open = d.get("fail_open", True)
        self.warn_wechat = d.get("warn_wechat", False)
        self.model = d.get("model", "")
        self.base_url = d.get("base_url", "")
        self.api_key = d.get("api_key", "")
        self.model_params = d.get("model_params") or {}
        self.extra_headers = d.get("extra_headers") or {}
        self.prompt = d.get("prompt") or ""
        self.yes_standard = d.get("yes_standard") or ""
        self.timeout = d.get("timeout") or 3.0
        self.rules = [QCRule(r) for r in d.get("rules") or []]


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return QCConfig(json.load(f))


def build_prompt(config: QCConfig) -> str:
    """与 core.quality_inspection.llm_checker.LLMChecker._build_prompt 逻辑完全一致:
    主体 prompt + 规则动态拼接 + yes_standard。"""
    parts = [config.prompt.strip()]
    shown = [r for r in config.rules if r.explanation or r.llm_phrases]
    if shown:
        lines = ["", "以下情形必须判定为 No(违规):"]
        for r in shown:
            examples = r.llm_phrases
            line = f"- 【{r.category}】"
            if examples:
                line += f"如“{'”“'.join(examples)}”。"
            if r.explanation:
                line += r.explanation
            lines.append(line)
        parts.append("\n".join(lines))
    if config.yes_standard.strip():
        parts.append("\n判 Yes(合规)的标准:\n" + config.yes_standard.strip())
    return "\n".join(parts)
