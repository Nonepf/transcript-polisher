"""
renderer.py — 输出文档渲染

将润色正文、关键信息提取结果、原始文稿拼装为最终的 Markdown 报告。
与处理逻辑解耦，方便未来替换输出格式（如改为 HTML / DOCX）。
"""

import time
from pathlib import Path


def render_report(
    filename:  str,
    original:  str,
    polished:  str,
    key_info:  str,
    seg_plan:  list[dict],
) -> str:
    """
    生成完整的 Markdown 润色报告。

    Args:
        filename:  原始文件名（用于标题和统计）。
        original:  原始文稿文本。
        polished:  润色后完整文本。
        key_info:  关键信息提取 Markdown 块。
        seg_plan:  LLM 分段计划（空列表则不渲染目录）。

    Returns:
        完整 Markdown 字符串。
    """
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    stem      = Path(filename).stem

    toc_block = _render_toc(seg_plan)

    return (
        f"# 录音稿润色报告：{stem}\n\n"
        f"> 生成时间：{timestamp}  \n"
        f"> 原文字数：{len(original):,} 字 ｜ 润色后字数：{len(polished):,} 字\n\n"
        f"{toc_block}"
        f"---\n\n"
        f"## 📋 关键信息提取\n\n"
        f"{key_info}\n\n"
        f"---\n\n"
        f"## ✏️ 润色后正文\n\n"
        f"{polished}\n\n"
        f"---\n\n"
        f"## 📝 原始文稿（存档）\n\n"
        f"<details>\n"
        f"<summary>点击展开原始文稿</summary>\n\n"
        f"```\n{original}\n```\n\n"
        f"</details>\n"
    )


# ── 内部辅助 ─────────────────────────────────────────────────────────────────

def _render_toc(seg_plan: list[dict]) -> str:
    """根据分段计划渲染话题目录块，无计划时返回空字符串。"""
    if not seg_plan:
        return ""
    lines = "\n".join(f"- {s.get('title', '—')}" for s in seg_plan)
    return f"**话题段落规划**\n\n{lines}\n\n"
