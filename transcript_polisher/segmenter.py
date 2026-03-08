"""
segmenter.py — 文本分段

两种策略：
1. LLM 智能分段（主路径）：把全文交给 LLM 识别话题边界，返回 JSON 分段计划，
   再用 start_hint 定位原文切割点。
2. 兜底分段（降级路径）：LLM 规划失败时，按自然段落 + 字数上限粗切。

对外接口：
  segment(text, cfg) -> list[tuple[str, str]]
      返回 [(title, chunk_text), ...]，调用方不需感知内部策略。
"""

import json
import re

from .api_client import call_llm
from .prompts    import PLANNING_SYSTEM, PLANNING_USER
from .rate_limiter import safe_print

# ── 类型别名 ─────────────────────────────────────────────────────────────────
Chunk  = tuple[str, str]          # (title, text)
SegPlan = list[dict]              # LLM 返回的分段计划


# ════════════════════════════════════════════════════════════════════════════
# LLM 分段规划
# ════════════════════════════════════════════════════════════════════════════

def _llm_plan(text: str, cfg: dict) -> SegPlan:
    """
    请求 LLM 输出话题分段 JSON 计划。
    失败（网络、解析错误等）时返回空列表。
    """
    preview  = text[:cfg["planning_preview_chars"]]
    messages = [
        {"role": "system", "content": PLANNING_SYSTEM},
        {"role": "user",   "content": PLANNING_USER.format(text_preview=preview)},
    ]
    try:
        raw  = call_llm(messages, cfg, max_tokens=1500)
        raw  = re.sub(r"```(?:json)?|```", "", raw).strip()
        data = json.loads(raw)
        segs = data.get("segments", [])
        if segs and isinstance(segs, list):
            return segs
    except Exception as exc:
        safe_print(f"\n    ⚠ 分段规划解析失败（{exc}），将使用兜底分段")
    return []


def _apply_plan(text: str, plan: SegPlan) -> list[Chunk]:
    """
    用 start_hint 在原文中定位每段起始位置，切割出各段文本。
    无法定位的段落丢弃（兜底会补回）。
    """
    boundaries: list[tuple[int, str]] = []
    for seg in plan:
        hint = seg.get("start_hint", "").strip()
        if hint:
            pos = text.find(hint)
            if pos >= 0:
                boundaries.append((pos, seg.get("title", "（未命名）")))

    if not boundaries:
        return []

    # 按位置排序，去掉距离过近的重复边界（< 50 字）
    boundaries.sort(key=lambda x: x[0])
    deduped = [boundaries[0]]
    for b in boundaries[1:]:
        if b[0] - deduped[-1][0] > 50:
            deduped.append(b)

    chunks: list[Chunk] = []
    for i, (pos, title) in enumerate(deduped):
        end        = deduped[i + 1][0] if i + 1 < len(deduped) else len(text)
        chunk_text = text[pos:end].strip()
        if chunk_text:
            chunks.append((title, chunk_text))

    # 第一个边界前若有内容，并入第一段
    if deduped[0][0] > 0:
        prefix = text[: deduped[0][0]].strip()
        if prefix:
            chunks[0] = (chunks[0][0], prefix + "\n" + chunks[0][1]) if chunks else [("开篇", prefix)]

    return chunks


# ════════════════════════════════════════════════════════════════════════════
# 兜底分段
# ════════════════════════════════════════════════════════════════════════════

def _fallback_segment(text: str, chunk_size: int) -> list[Chunk]:
    """
    按自然段落（连续空行）切割，超过 chunk_size 字时强制分段。
    段落标题使用序号占位。
    """
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[Chunk] = []
    current: list[str]  = []
    cur_len = 0
    idx     = 1

    for para in paragraphs:
        if cur_len + len(para) > chunk_size and current:
            chunks.append((f"第 {idx} 段", "\n\n".join(current)))
            idx    += 1
            current = []
            cur_len = 0
        current.append(para)
        cur_len += len(para)

    if current:
        chunks.append((f"第 {idx} 段", "\n\n".join(current)))

    return chunks


# ════════════════════════════════════════════════════════════════════════════
# 对外接口
# ════════════════════════════════════════════════════════════════════════════

def segment(text: str, cfg: dict) -> tuple[list[Chunk], SegPlan]:
    """
    对原始文本进行分段，优先使用 LLM 智能分段，失败时降级到兜底方案。

    Returns:
        chunks:  [(title, chunk_text), ...]
        plan:    LLM 分段计划（兜底时为空列表，供渲染器生成目录用）
    """
    safe_print("  🗂 LLM 规划话题边界...", end=" ", flush=True)
    plan   = _llm_plan(text, cfg)
    chunks = _apply_plan(text, plan)

    if chunks:
        safe_print(f"✅  识别到 {len(chunks)} 个话题段落")
        return chunks, plan

    safe_print("⚠ 规划失败，使用兜底分段")
    return _fallback_segment(text, cfg["fallback_chunk_size"]), []
