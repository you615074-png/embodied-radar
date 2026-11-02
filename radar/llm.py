"""大模型调用：OpenAI 兼容接口（默认 DeepSeek），附带 token 统计和峰谷判断。"""
import json
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone

from . import config


class Usage:
    def __init__(self):
        self.lock = threading.Lock()
        self.calls = self.hit = self.miss = self.out = self.peak_calls = 0

    def add(self, u: dict, peak: bool):
        hit = u.get("prompt_cache_hit_tokens") or 0
        miss = u.get("prompt_cache_miss_tokens")
        if miss is None:
            miss = (u.get("prompt_tokens") or 0) - hit
        with self.lock:
            self.calls += 1
            self.hit += hit
            self.miss += miss
            self.out += u.get("completion_tokens") or 0
            self.peak_calls += int(peak)

    def cost_usd(self) -> float:
        p = config.PRICE
        base = (self.hit * p["hit"] + self.miss * p["miss"] + self.out * p["out"]) / 1e6
        # 粗略：按峰时调用占比把对应部分翻倍
        ratio = self.peak_calls / self.calls if self.calls else 0
        return base * (1 + ratio)

    def summary(self) -> str:
        if not self.calls:
            return "本次未调用大模型"
        if config.LLM_BACKEND == "dsh":
            return f"{self.calls} 次调用（dsh 本地调试，不统计 token）"
        return (f"{self.calls} 次调用，输入 {self.hit + self.miss:,} token"
                f"（缓存命中 {self.hit:,}），输出 {self.out:,} token，"
                f"估算 ${self.cost_usd():.3f}")


usage = Usage()


def is_peak(now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    return any(a <= now.hour < b for a, b in config.PEAK_HOURS_UTC)


_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        if not config.LLM_API_KEY:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY（或 LLM_API_KEY）")
        _client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL, timeout=600)
    return _client


def chat(messages, model, *, json_mode=False, thinking=False, max_tokens=8000) -> str:
    if config.LLM_BACKEND == "dsh":
        return _chat_dsh(messages, json_mode)
    kwargs = dict(model=model, messages=messages, max_tokens=max_tokens)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if "deepseek" in config.LLM_BASE_URL:
        kwargs["extra_body"] = {"thinking": {"type": "enabled" if thinking else "disabled"}}
    last = None
    for attempt in range(3):
        try:
            resp = _get_client().chat.completions.create(**kwargs)
            usage.add(resp.usage.model_dump() if resp.usage else {}, is_peak())
            return resp.choices[0].message.content or ""
        except Exception as e:  # 网络抖动、限流等，退避重试
            last = e
            time.sleep(5 * (attempt + 1))
    raise last


DSH_PATCH = config.ROOT / "tools" / "dsh-notools.yml"


def _chat_dsh(messages, json_mode) -> str:
    """本地调试：通过 dsh headless 调 DeepSeek（关闭 shell/文件工具，避免 README 里的注入内容操作本机）。"""
    parts = [f"[{m['role']}]\n{m['content']}" for m in messages]
    parts.append("直接输出最终结果，不要调用任何工具。" + ("只输出一个 JSON 对象。" if json_mode else ""))
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run(
            ["dsh", "--profile", "headless", "--patch", str(DSH_PATCH), "-"],
            input="\n\n".join(parts), capture_output=True, text=True, cwd=tmp, timeout=900,
        )
    if r.returncode != 0:
        raise RuntimeError(f"dsh 调用失败：{r.stderr[-500:]}")
    usage.add({}, is_peak())
    return r.stdout.strip()


def parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"模型没有返回 JSON：{text[:200]}")
    raw = text[start:end + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 常见毛病：结尾多一个逗号、字符串里直接换行
        return json.loads(re.sub(r",\s*([}\]])", r"\1", raw), strict=False)
