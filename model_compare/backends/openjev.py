"""后端:openjev(codiv.ai /v1/systemone),判别式决策模型

请求:
  POST https://api.codiv.ai/v1/systemone
  Header: Authorization: Bearer <TYPESAFE_CODIV_API_KEY, 缺省用本地兜底>
  {"model": "openjev-latest", "state": <话术>,
   "questions": {"is_violation": {"type": "noul", "instructions": <统一 prompt>}}}
响应:
  {"model":"openjev-0.1",
   "answers":{"is_violation":{"type":"noul","noul":0.9974621249534545}},
   "usage":{"input_tokens":86,"output_tokens":0}}

noul = 对 instructions 问句答 Yes 的概率。与 clef / Intern-Decision-4B
同属 systemone 协议(多 questions dict, choice|score|noul 三类型),
仅端点、鉴权与 model 名不同。这里 instructions 用统一质检 prompt(问"是否合规"),
故 noul = P(合规),noul < THRESHOLD 判违规。
"""
import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.request

try:
    import certifi
    _CA_FILE = certifi.where()
except ImportError:  # 无 certifi 时用系统默认 CA
    _CA_FILE = None

from base import JudgeResult, ModelBackend, register_backend
from qc_config import build_prompt

OPENJEV_URL = "https://api.codiv.ai/v1/systemone"
MODEL = "openjev-latest"
QUESTION_KEY = "is_violation"
THRESHOLD = 0.5


@register_backend("openjev")
class OpenJevBackend(ModelBackend):
    def __init__(self, config):
        self.api_key = os.environ.get(
            "TYPESAFE_CODIV_API_KEY",
            "sk-codiv-5TplzGMkVZwHj1p1SjUFuCPS4dGhdyByqmP8YXko",
        )
        self.questions = {
            QUESTION_KEY: {
                "type": "noul",
                "instructions": build_prompt(config),
            }
        }
        self.last_request = ""

    def _post(self, payload_str: str):
        """urllib 直连;macOS 缺 CA 证书时回退 curl。返回 (body, error)。"""
        request = urllib.request.Request(
            OPENJEV_URL, data=payload_str.encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
        )
        try:
            context = ssl.create_default_context(cafile=_CA_FILE) if _CA_FILE \
                else ssl.create_default_context()
            with urllib.request.urlopen(request, timeout=60, context=context) as resp:
                return resp.read().decode("utf-8"), ""
        except urllib.error.HTTPError as e:
            return "", f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
        except (urllib.error.URLError, OSError):
            # OSError 覆盖 ConnectionResetError 等连接中断,统一回退 curl
            result = subprocess.run(
                ["curl", "-sS", "--max-time", "60", OPENJEV_URL,
                 "-H", f"Authorization: Bearer {self.api_key}",
                 "-H", "Content-Type: application/json",
                 "-d", payload_str, "-w", "\nHTTP_CODE:%{http_code}"],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                return "", f"curl 失败: {result.stderr.strip()[:200]}"
            body, _, tail = result.stdout.rpartition("\nHTTP_CODE:")
            code = tail.strip()
            if code != "200":
                return "", f"HTTP {code}: {body[:300]}"
            return body, ""

    def judge(self, text):
        payload = {"model": MODEL, "state": f"{text}", "questions": self.questions}
        payload_str = json.dumps(payload, ensure_ascii=False)
        self.last_request = json.dumps(payload, ensure_ascii=False, indent=2)
        start = time.time()
        body, error = self._post(payload_str)
        if error:
            return JudgeResult(latency_ms=int((time.time() - start) * 1000), error=error)
        latency = int((time.time() - start) * 1000)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return JudgeResult(raw=body, latency_ms=latency, error="响应非 JSON")

        answer = data.get("answers", {}).get(QUESTION_KEY, {})
        score = answer.get("noul")
        if not isinstance(score, (int, float)):
            return JudgeResult(raw=body, latency_ms=latency,
                               error=f"未取到 noul 分数: {answer}")

        # noul = P(Yes 合规),故分数越低越违规
        hit = score < THRESHOLD
        return JudgeResult(hit=hit,
                           categories=["话术违规"] if hit else [],
                           unclassified_hit=hit,
                           raw=f"noul={score} (阈值 {THRESHOLD}, 低于阈值判违规)",
                           latency_ms=latency)
