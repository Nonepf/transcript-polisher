"""
api_client.py — SiliconFlow API 调用层

职责：
- 调用 /v1/chat/completions 端点
- 请求前经令牌桶限速（RPM + TPM）
- 429 → 优先读 Retry-After 头，否则指数退避 + 随机抖动
- 其他 HTTP 错误 / 网络异常 → 指数退避重试
"""

import random
import time

import requests

from .rate_limiter import RateLimiter, safe_print

# 进程内唯一限速器实例，由 pipeline.py 在启动时初始化
_rate_limiter: RateLimiter | None = None


def init_rate_limiter(rpm: int, tpm: int) -> None:
    """初始化全局令牌桶，必须在任何 call_llm 调用前执行。"""
    global _rate_limiter
    _rate_limiter = RateLimiter(rpm, tpm)


def _estimate_tokens(messages: list[dict], max_tokens: int) -> int:
    """
    粗估本次请求的 token 消耗（输入 + 最大输出）。
    中文约 1.5 char/token，保守估算不做语言区分。
    """
    input_chars  = sum(len(m.get("content", "")) for m in messages)
    input_tokens = int(input_chars / 1.5)
    return input_tokens + max_tokens


def call_llm(messages: list[dict], cfg: dict, max_tokens: int | None = None) -> str:
    """
    向 SiliconFlow 发送对话请求并返回模型回复文本。

    Args:
        messages:   符合 OpenAI 格式的消息列表。
        cfg:        全局配置字典（需含 api_key / api_base / model 等键）。
        max_tokens: 覆盖 cfg["max_tokens"]，可选。

    Returns:
        模型返回的纯文本内容。

    Raises:
        RuntimeError: 超过最大重试次数后仍失败。
    """
    url      = f"{cfg['api_base']}/chat/completions"
    headers  = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type":  "application/json",
    }
    max_tok  = max_tokens or cfg["max_tokens"]
    payload  = {
        "model":       cfg["model"],
        "messages":    messages,
        "max_tokens":  max_tok,
        "temperature": cfg["temperature"],
    }
    estimated = _estimate_tokens(messages, max_tok)

    for attempt in range(cfg["retry_times"]):

        # ── 1. 令牌桶限速 ────────────────────────────────────────────────────
        if _rate_limiter:
            _rate_limiter.acquire(estimated)

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=180)

            # ── 2. 429 Rate Limit ────────────────────────────────────────────
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                wait = (
                    float(retry_after) + random.uniform(0.5, 2.0)
                    if retry_after
                    else min(
                        cfg["backoff_base"] * (2 ** attempt) + random.uniform(0, 3),
                        cfg["backoff_max"],
                    )
                )
                safe_print(
                    f"\n    ⏸ 429 限流，等待 {wait:.1f}s"
                    f"（第 {attempt + 1}/{cfg['retry_times']} 次重试）...",
                    flush=True,
                )
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

        # ── 3. 其他 HTTP 错误 ─────────────────────────────────────────────────
        except requests.exceptions.HTTPError as exc:
            wait = min(
                cfg["backoff_base"] * (2 ** attempt) + random.uniform(0, 2),
                cfg["backoff_max"],
            )
            safe_print(
                f"\n    ⚠ HTTP {exc.response.status_code}，{wait:.1f}s 后重试"
                f"（{attempt + 1}/{cfg['retry_times']}）...",
                flush=True,
            )
            if attempt == cfg["retry_times"] - 1:
                raise
            time.sleep(wait)

        # ── 4. 网络 / 超时 ────────────────────────────────────────────────────
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            wait = min(
                cfg["backoff_base"] * (2 ** attempt) + random.uniform(0, 2),
                cfg["backoff_max"],
            )
            safe_print(
                f"\n    ⚠ 网络错误，{wait:.1f}s 后重试"
                f"（{attempt + 1}/{cfg['retry_times']}）...",
                flush=True,
            )
            if attempt == cfg["retry_times"] - 1:
                raise
            time.sleep(wait)

    raise RuntimeError(f"已重试 {cfg['retry_times']} 次，请求仍失败")
