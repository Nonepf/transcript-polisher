"""
rate_limiter.py — 令牌桶限速器 & 线程安全打印

RateLimiter：双桶（RPM + TPM），线程安全，所有并发线程共享同一实例。
safe_print：加锁打印，防止多线程输出交错。
"""

import time
import threading

_print_lock = threading.Lock()


def safe_print(*args, **kwargs) -> None:
    """线程安全的 print，防止并发输出交错。"""
    with _print_lock:
        print(*args, **kwargs)


class RateLimiter:
    """
    双桶令牌限速器，同时约束 RPM 和 TPM。

    工作原理：
    - 每个桶有固定容量，按时间匀速补充令牌。
    - acquire() 阻塞直到两个桶都有足够令牌，然后原子扣减。
    - 计算精确等待时长后短暂 sleep，避免忙等。
    """

    def __init__(self, rpm: int, tpm: int) -> None:
        self._lock = threading.Lock()

        self._rpm_capacity    = float(rpm)
        self._rpm_tokens      = float(rpm)          # 启动时桶满
        self._rpm_refill_rate = rpm / 60.0           # tokens / sec

        self._tpm_capacity    = float(tpm)
        self._tpm_tokens      = float(tpm)
        self._tpm_refill_rate = tpm / 60.0

        self._last_refill = time.monotonic()

    # ── 内部方法 ─────────────────────────────────────────────────────────────

    def _refill(self) -> None:
        """根据经过的时间补充两个桶的令牌（需在持锁状态下调用）。"""
        now     = time.monotonic()
        elapsed = now - self._last_refill
        self._rpm_tokens = min(self._rpm_capacity,
                               self._rpm_tokens + elapsed * self._rpm_refill_rate)
        self._tpm_tokens = min(self._tpm_capacity,
                               self._tpm_tokens + elapsed * self._tpm_refill_rate)
        self._last_refill = now

    def _wait_needed(self, estimated_tokens: int) -> float:
        """
        在持锁状态下，计算还需等待多少秒才能满足本次请求。
        返回 0.0 表示当前可以立即获取。
        """
        if self._rpm_tokens >= 1 and self._tpm_tokens >= estimated_tokens:
            return 0.0
        wait_rpm = max(0.0, (1 - self._rpm_tokens) / self._rpm_refill_rate)
        wait_tpm = max(0.0, (estimated_tokens - self._tpm_tokens) / self._tpm_refill_rate)
        return max(wait_rpm, wait_tpm)

    # ── 公共接口 ─────────────────────────────────────────────────────────────

    def acquire(self, estimated_tokens: int = 2000) -> None:
        """
        阻塞直到两桶都有足够令牌，然后原子扣减。

        Args:
            estimated_tokens: 本次请求预估消耗的 token 数（输入 + 输出）。
        """
        while True:
            with self._lock:
                self._refill()
                wait = self._wait_needed(estimated_tokens)
                if wait == 0.0:
                    self._rpm_tokens -= 1
                    self._tpm_tokens -= estimated_tokens
                    return

            # 释放锁后再 sleep，避免持锁阻塞其他线程
            time.sleep(min(wait, 1.0))
