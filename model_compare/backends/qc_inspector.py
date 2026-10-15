"""后端:直接用配置模型做语义质检(只走模型,不做规则子串匹配)

原仓库版走 LLMChecker(aisuite);这里改为直接 HTTP 调 OpenAI 兼容接口
(/chat/completions),判定逻辑保持一致:
  只输出 Yes(合规)/ No(违规);超时一律判合规;
  异常/无法识别时 fail_open 放行,否则记为命中。
"""
import json
import time
import urllib.error
import urllib.request

from base import JudgeResult, ModelBackend, register_backend
from qc_config import build_prompt


@register_backend("Qwen3.8")
class QCInspectorBackend(ModelBackend):
    def __init__(self, config):
        self.fail_open = config.fail_open
        # aisuite 的 model 形如 "openai:Qwen3.8-27B-AWQ-INT4",去掉 provider 前缀
        self.model = config.model.split(":", 1)[-1]
        self.url = config.base_url.rstrip("/") + "/chat/completions"
        self.timeout = config.timeout
        self.prompt = build_prompt(config)
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
            **config.extra_headers,
        }
        # 模型参数,强制关闭思考;extra_body 展开合并进请求体
        self.params = dict(config.model_params)
        extra_body = dict(self.params.pop("extra_body", None) or {})
        extra_body.setdefault("chat_template_kwargs", {})["enable_thinking"] = False
        self.params.update(extra_body)
        # 最近一次发给模型的完整请求(供预览打印)
        self.last_request = ""

    def _chat(self, text):
        """返回 (raw_content, error);timeout 单独标记"""
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": text},
            ],
            **self.params,
        }
        self.last_request = json.dumps(
            {"model": self.model, "messages": body["messages"], "params": self.params},
            ensure_ascii=False, indent=2)
        request = urllib.request.Request(
            self.url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST", headers=self.headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"] or "", ""
        except Exception as e:
            return "", e

    def judge(self, text):
        if not text:
            return JudgeResult(raw="")
        start = time.time()
        raw, err = self._chat(text)
        latency = int((time.time() - start) * 1000)
        if err:
            if _is_timeout(err):
                return JudgeResult(raw="超时,判合规", latency_ms=latency)  # 超时一律判合规
            reason = f"质检模型异常: {err}"
            return self._fail(reason, latency)

        answer = raw.strip().lower()
        if answer.startswith("yes"):
            return JudgeResult(raw=raw, latency_ms=latency)
        if answer.startswith("no"):
            return JudgeResult(hit=True, categories=["话术违规"],
                               unclassified_hit=True, raw=raw, latency_ms=latency)
        return self._fail(f"质检结果无法识别: {raw}", latency)

    def _fail(self, reason, latency):
        """模型异常/结果无法识别:fail_open 放行,否则记为命中"""
        if self.fail_open:
            return JudgeResult(raw=reason, latency_ms=latency)
        return JudgeResult(hit=True, categories=["质检不可用"],
                           unclassified_hit=True, raw=reason, latency_ms=latency)


def _is_timeout(e: Exception) -> bool:
    name = type(e).__name__.lower()
    if "timeout" in name:
        return True
    return "timeout" in str(e).lower() or "timed out" in str(e).lower()
