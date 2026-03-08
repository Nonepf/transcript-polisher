"""
config.py — 全局配置

所有可调参数集中于此，其他模块只读取，不修改。
CLI 参数通过 main.py 覆盖 CONFIG 中对应的键。
"""

import os

CONFIG: dict = {
    # ── API ──────────────────────────────────────────────────────────────────
    "api_key":  os.getenv("SILICONFLOW_API_KEY", "YOUR_API_KEY_HERE"),
    "api_base": "https://api.siliconflow.cn/v1",
    "model":    "moonshotai/Kimi-K2-Instruct",

    # ── 并发 & 限速（L0 配额：500 RPM / 2,000,000 TPM，留 10% 余量）────────────
    "max_workers": 8,           # 段落润色并发线程数，建议 ≤ RPM/10
    "rpm_limit":   450,         # 每分钟最大请求数
    "tpm_limit":   1_800_000,   # 每分钟最大 token 数

    # ── 429 / 网络错误重试 ────────────────────────────────────────────────────
    "retry_times":  6,          # 最大重试次数
    "backoff_base": 2,          # 退避基数（秒），实际等待 = base × 2^attempt + jitter
    "backoff_max":  120,        # 单次等待上限（秒）

    # ── LLM 请求参数 ──────────────────────────────────────────────────────────
    "max_tokens":  4096,
    "temperature": 0.3,

    # ── 分段参数 ──────────────────────────────────────────────────────────────
    "planning_preview_chars": 6000,   # 规划阶段发给 LLM 的最大字符数
    "fallback_chunk_size":    1200,   # 兜底分段的每段字数上限
    "context_summary_chars":  400,    # 段间传递的上文摘要最大长度

    # ── 路径 ─────────────────────────────────────────────────────────────────
    "input_folder":  "recording_raw",
    "output_folder": "recording_polished",
}
