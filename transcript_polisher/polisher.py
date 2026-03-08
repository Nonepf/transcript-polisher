"""
polisher.py — 段落润色 & 关键信息提取

polish_all_chunks():
    用 ThreadPoolExecutor 并发润色各段落。
    上下文摘要按顺序滚动传递：每段启动前等待前一段完成（最多 30s），
    保证上下文连贯性，同时不阻塞整体并发。
    若需严格串行上下文，将 cfg["max_workers"] 设为 1。

extract_key_info():
    对全文润色结果做一次结构化信息提取。
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .api_client   import call_llm
from .prompts      import POLISH_SYSTEM, POLISH_USER, KEY_INFO_SYSTEM, KEY_INFO_USER
from .rate_limiter import safe_print

# ── 类型别名 ─────────────────────────────────────────────────────────────────
Chunk = tuple[str, str]   # (title, text)

_CONTEXT_WAIT_TIMEOUT = 30   # 等待前一段完成的超时秒数（超时后用占位摘要）


# ════════════════════════════════════════════════════════════════════════════
# 单段润色（线程池任务）
# ════════════════════════════════════════════════════════════════════════════

def _polish_one(
    idx:     int,    # 1-based 段落序号
    title:   str,
    chunk:   str,
    total:   int,
    context: str,
    cfg:     dict,
) -> tuple[int, str, str]:
    """
    润色单个段落。
    Returns:
        (idx, polished_text, summary)
    """
    user_msg = POLISH_USER.format(
        context=context,
        title=title,
        idx=idx,
        total=total,
        chunk=chunk,
    )
    messages = [
        {"role": "system", "content": POLISH_SYSTEM},
        {"role": "user",   "content": user_msg},
    ]
    raw = call_llm(messages, cfg)

    if "---SUMMARY---" in raw:
        body, summary_raw = raw.split("---SUMMARY---", 1)
        polished = body.strip()
        summary  = summary_raw.strip()[: cfg["context_summary_chars"]]
    else:
        polished = raw.strip()
        summary  = polished[-cfg["context_summary_chars"]:]

    safe_print(f"  ✅ 段落 {idx}/{total}「{title}」润色完成")
    return idx, polished, summary


# ════════════════════════════════════════════════════════════════════════════
# 并发润色编排
# ════════════════════════════════════════════════════════════════════════════

def polish_all_chunks(chunks: list[Chunk], cfg: dict) -> str:
    """
    并发润色所有段落，保序拼接为完整润色文本。

    上下文策略：
    - 每段任务启动前调用 _wait_for_context()，等待前一段完成并获取摘要。
    - 超时（30s）则使用占位字符串，不阻塞整体流程。
    - max_workers=1 时退化为严格串行，摘要传递完全准确。
    """
    total = len(chunks)
    max_w = min(cfg["max_workers"], total)
    safe_print(f"  🚀 启动 {max_w} 个并发线程润色 {total} 个段落...")

    # 共享状态（按 0-based index）
    results:   list[str | None]  = [None]  * total
    summaries: list[str]         = [""]    * total
    completed: list[bool]        = [False] * total
    lock = threading.Lock()

    def wait_for_context(i: int) -> str:
        """等待第 i-1 段（0-based）完成，返回其摘要。"""
        if i == 0:
            return "（无上文，这是第一段）"
        deadline = time.monotonic() + _CONTEXT_WAIT_TIMEOUT
        while not completed[i - 1] and time.monotonic() < deadline:
            time.sleep(0.2)
        return summaries[i - 1] or f"（第 {i} 段上文摘要生成中，请结合行文判断）"

    def task(i: int, title: str, chunk: str) -> int:
        context = wait_for_context(i)
        _, polished, summary = _polish_one(i + 1, title, chunk, total, context, cfg)
        with lock:
            results[i]   = polished
            summaries[i] = summary
            completed[i] = True
        return i

    with ThreadPoolExecutor(max_workers=max_w) as executor:
        futures = {
            executor.submit(task, i, title, chunk): i
            for i, (title, chunk) in enumerate(chunks)
        }
        for future in as_completed(futures):
            i = futures[future]
            try:
                future.result()
            except Exception as exc:
                safe_print(f"  ❌ 段落 {i + 1} 润色失败：{exc}")
                with lock:
                    results[i]   = f"<!-- 润色失败：{exc} -->\n\n{chunks[i][1]}"
                    completed[i] = True

    return "\n\n---\n\n".join(r or "" for r in results)


# ════════════════════════════════════════════════════════════════════════════
# 关键信息提取
# ════════════════════════════════════════════════════════════════════════════

def extract_key_info(polished_text: str, cfg: dict) -> str:
    """对完整润色文本做一次结构化信息提取，返回 Markdown 格式报告。"""
    safe_print("  🔍 提取关键信息...", end=" ", flush=True)
    messages = [
        {"role": "system", "content": KEY_INFO_SYSTEM},
        {"role": "user",   "content": KEY_INFO_USER.format(
            full_text=polished_text[:8000]   # 截断防超限
        )},
    ]
    result = call_llm(messages, cfg, max_tokens=2000)
    safe_print("✅")
    return result
