#!/usr/bin/env python3
"""
录音稿自动润色分析脚本 v2
- 输入格式：.txt / .md
- 分段策略：LLM 智能分段（先规划话题边界，再按话题逐段润色）
- 输出格式：Markdown (.md)
- API：SiliconFlow (Kimi2.5)
"""

import os
import re
import json
import time
import argparse
import textwrap
from pathlib import Path

import requests

# ════════════════════════════════════════════════════════════════════════════
# 配置区 —— 按需修改
# ════════════════════════════════════════════════════════════════════════════
CONFIG = {
    # ── API ──────────────────────────────────────────────────────────────────
    "api_key":   os.getenv("SILICONFLOW_API_KEY", "YOUR_API_KEY_HERE"),
    "api_base":  "https://api.siliconflow.cn/v1",
    "model":     "Pro/deepseek-ai/DeepSeek-V3.2",

    # ── 智能分段参数 ──────────────────────────────────────────────────────────
    # 规划阶段：把全文（前 N 字）发给 LLM 做话题边界规划
    "planning_preview_chars": 6000,
    # 兜底：若 LLM 规划失败，回退到按字数粗切
    "fallback_chunk_size": 1200,
    # 每段润色时携带的"上文摘要"最大长度
    "context_summary_chars": 400,

    # ── LLM 请求参数 ──────────────────────────────────────────────────────────
    "max_tokens":  4096,
    "temperature": 0.3,
    "retry_times": 3,
    "retry_delay": 5,

    # ── 路径 ─────────────────────────────────────────────────────────────────
    "input_folder":  "recording_raw",
    "output_folder": "recording_polished",
}

# ════════════════════════════════════════════════════════════════════════════
# Prompts
# ════════════════════════════════════════════════════════════════════════════

PLANNING_SYSTEM = """你是一位专业的文稿结构分析师。
你的任务是阅读一段录音转录文本，识别其中的话题/议题切换点，将全文划分为若干个语义完整的段落。

输出要求：
- 只输出 JSON，不要有任何额外说明或 markdown 代码块标记
- 格式：{"segments": [{"title": "段落标题", "start_hint": "该段开头的前10个字", "end_hint": "该段结尾的后10个字"}, ...]}
- 每段标题简洁（10字以内），反映该段核心话题
- 段落数量根据内容自然划分，一般 3-8 段为宜；超短文本可只分 1-2 段
- start_hint 和 end_hint 必须是原文中实际存在的字符串片段"""

PLANNING_USER = """请对以下录音转录文本进行话题分段规划：

{text_preview}"""

POLISH_SYSTEM = """你是一位专业的文字编辑，擅长对语音转录稿件进行润色和整理。

处理规则：
1. 语法纠错：修正口语化表达、重复词、语气词（嗯、啊、那个、就是说等），使文本书面化
2. 重新排版：合理分段，段首不缩进，段间空行
3. 添加标题：用 ## 话题标题 作为本段标题（使用规划时确定的标题）
4. 保留原意：不得增加原文没有的观点，不得删除重要信息
5. 上下文连贯：注意与上文的衔接，开头过渡自然
6. 加粗重点：关键术语、核心结论、重要数字加粗

处理完毕后，在 ---SUMMARY--- 分隔线后，用 2-3 句话总结本段要点（供下一段参考上下文用）。"""

POLISH_USER = """【上文摘要（仅供参考，不输出）】
{context}

【本段话题标题】{title}
【本段位置】第 {idx}/{total} 段

【待润色文本】
{chunk}

请润色上述文本，然后在 ---SUMMARY--- 后给出本段摘要。"""

KEY_INFO_SYSTEM = """你是一位专业的信息分析师，擅长从文本中提取结构化信息。"""

KEY_INFO_USER = """请对以下录音稿润色文本进行关键信息提取，输出报告：

## 1. 核心主题
（1-2句概括本次录音的主题与目的）

## 2. 关键信息点
（要点列表，每条以 - 开头，重要内容加粗）

## 3. 行动项 / 待办事项
（如无则写"无"）

## 4. 关键人物 / 组织
（如无则写"无"）

## 5. 重要数据 / 时间节点
（数字、日期、截止时间；如无则写"无"）

---
{full_text}"""


# ════════════════════════════════════════════════════════════════════════════
# 文件读取（仅 .txt / .md）
# ════════════════════════════════════════════════════════════════════════════

def read_file(path: Path) -> str:
    if path.suffix.lower() not in (".txt", ".md"):
        raise ValueError(f"不支持的格式 {path.suffix}，仅支持 .txt / .md")
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb2312"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    raise ValueError(f"无法解码文件（尝试了 utf-8/gbk）: {path}")


# ════════════════════════════════════════════════════════════════════════════
# LLM API 调用（带重试）
# ════════════════════════════════════════════════════════════════════════════

def call_llm(messages: list[dict], cfg: dict, max_tokens: int = None) -> str:
    url = f"{cfg['api_base']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": max_tokens or cfg["max_tokens"],
        "temperature": cfg["temperature"],
    }
    for attempt in range(1, cfg["retry_times"] + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=180)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code
            print(f"\n    ⚠ HTTP {code}，第 {attempt}/{cfg['retry_times']} 次重试...", end="")
            if attempt == cfg["retry_times"]:
                raise
            time.sleep(cfg["retry_delay"] * attempt)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            print(f"\n    ⚠ 超时/连接失败，第 {attempt}/{cfg['retry_times']} 次重试...", end="")
            if attempt == cfg["retry_times"]:
                raise
            time.sleep(cfg["retry_delay"] * attempt)


# ════════════════════════════════════════════════════════════════════════════
# Step 1：LLM 智能分段规划
# ════════════════════════════════════════════════════════════════════════════

def llm_plan_segments(text: str, cfg: dict) -> list[dict]:
    """
    调用 LLM 识别话题边界。
    返回 [{"title": ..., "start_hint": ..., "end_hint": ...}, ...]
    失败时返回空列表（触发兜底方案）。
    """
    preview = text[:cfg["planning_preview_chars"]]
    messages = [
        {"role": "system", "content": PLANNING_SYSTEM},
        {"role": "user",   "content": PLANNING_USER.format(text_preview=preview)},
    ]
    try:
        raw = call_llm(messages, cfg, max_tokens=1500)
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        data = json.loads(raw)
        segs = data.get("segments", [])
        if segs and isinstance(segs, list):
            return segs
    except Exception as e:
        print(f"\n    ⚠ 分段规划解析失败（{e}），将使用兜底分段")
    return []


def apply_plan_to_text(text: str, plan: list[dict]) -> list[tuple[str, str]]:
    """
    根据 LLM 的 start_hint 定位每段起点，切割原文。
    返回 [(title, chunk_text), ...]
    """
    if not plan:
        return []

    boundaries = []
    for seg in plan:
        hint = seg.get("start_hint", "").strip()
        if hint:
            pos = text.find(hint)
            if pos >= 0:
                boundaries.append((pos, seg.get("title", "（未命名）")))

    if not boundaries:
        return []

    boundaries.sort(key=lambda x: x[0])
    # 去掉距离过近的重复边界
    deduped = [boundaries[0]]
    for b in boundaries[1:]:
        if b[0] - deduped[-1][0] > 50:
            deduped.append(b)

    chunks = []
    for i, (pos, title) in enumerate(deduped):
        end = deduped[i + 1][0] if i + 1 < len(deduped) else len(text)
        chunk_text = text[pos:end].strip()
        if chunk_text:
            chunks.append((title, chunk_text))

    # 如果第一个边界不在文本开头，把前面内容并入第一段
    if deduped[0][0] > 0:
        prefix = text[:deduped[0][0]].strip()
        if prefix and chunks:
            chunks[0] = (chunks[0][0], prefix + "\n" + chunks[0][1])
        elif prefix:
            chunks.insert(0, ("开篇", prefix))

    return chunks


def fallback_chunks(text: str, chunk_size: int) -> list[tuple[str, str]]:
    """兜底：按段落边界切割，超过 chunk_size 才强制分段。"""
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks, current, cur_len, idx = [], [], 0, 1
    for para in paragraphs:
        if cur_len + len(para) > chunk_size and current:
            chunks.append((f"第{idx}段", "\n\n".join(current)))
            idx += 1
            current, cur_len = [], 0
        current.append(para)
        cur_len += len(para)
    if current:
        chunks.append((f"第{idx}段", "\n\n".join(current)))
    return chunks


# ════════════════════════════════════════════════════════════════════════════
# Step 2：逐段润色
# ════════════════════════════════════════════════════════════════════════════

def polish_chunks(chunks: list[tuple[str, str]], cfg: dict) -> str:
    """逐段调用 LLM 润色，上下文摘要滚动传递。"""
    total = len(chunks)
    polished_parts = []
    context = "（无上文，这是第一段）"

    for i, (title, chunk) in enumerate(chunks, 1):
        print(f"  ⏳ 润色第 {i}/{total} 段「{title}」...", end=" ", flush=True)

        user_msg = POLISH_USER.format(
            context=context,
            title=title,
            idx=i,
            total=total,
            chunk=chunk,
        )
        messages = [
            {"role": "system", "content": POLISH_SYSTEM},
            {"role": "user",   "content": user_msg},
        ]
        raw = call_llm(messages, cfg)

        if "---SUMMARY---" in raw:
            parts = raw.split("---SUMMARY---", 1)
            polished_text = parts[0].strip()
            context = parts[1].strip()[:cfg["context_summary_chars"]]
        else:
            polished_text = raw.strip()
            context = polished_text[-cfg["context_summary_chars"]:]

        polished_parts.append(polished_text)
        print("✅")
        time.sleep(0.3)

    return "\n\n---\n\n".join(polished_parts)


# ════════════════════════════════════════════════════════════════════════════
# Step 3：关键信息提取
# ════════════════════════════════════════════════════════════════════════════

def extract_key_info(polished_text: str, cfg: dict) -> str:
    print("  🔍 提取关键信息...", end=" ", flush=True)
    messages = [
        {"role": "system", "content": KEY_INFO_SYSTEM},
        {"role": "user",   "content": KEY_INFO_USER.format(full_text=polished_text[:8000])},
    ]
    result = call_llm(messages, cfg, max_tokens=2000)
    print("✅")
    return result


# ════════════════════════════════════════════════════════════════════════════
# 构建输出文档
# ════════════════════════════════════════════════════════════════════════════

def build_output(filename: str, original: str, polished: str,
                 key_info: str, seg_plan: list[dict]) -> str:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    stem = Path(filename).stem

    toc_block = ""
    if seg_plan:
        toc_lines = "\n".join(f"- {s.get('title', '—')}" for s in seg_plan)
        toc_block = f"**话题段落规划**\n\n{toc_lines}\n\n"

    return (
        f"# 录音稿润色报告：{stem}\n\n"
        f"> 生成时间：{timestamp}  \n"
        f"> 原文字数：{len(original)} 字 ｜ 润色后字数：{len(polished)} 字\n\n"
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


# ════════════════════════════════════════════════════════════════════════════
# 单文件处理
# ════════════════════════════════════════════════════════════════════════════

def process_file(file: Path, output_path: Path, cfg: dict) -> bool:
    original = read_file(file)
    if len(original.strip()) < 30:
        print("  ⚠ 内容过短，跳过")
        return False

    print(f"  📄 {file.name}  ·  {len(original)} 字")

    # Step 1：LLM 智能分段
    print("  🗂 LLM 规划话题边界...", end=" ", flush=True)
    plan = llm_plan_segments(original, cfg)
    chunks = apply_plan_to_text(original, plan)

    if chunks:
        print(f"✅  识别到 {len(chunks)} 个话题段落")
    else:
        print("⚠ 规划失败，使用兜底分段")
        plan = []
        chunks = fallback_chunks(original, cfg["fallback_chunk_size"])

    # Step 2：逐段润色
    polished = polish_chunks(chunks, cfg)

    # Step 3：关键信息提取
    key_info = extract_key_info(polished, cfg)

    # 写出文件
    content = build_output(file.name, original, polished, key_info, plan)
    out_file = output_path / f"{file.stem}_polished.md"
    out_file.write_text(content, encoding="utf-8")
    print(f"  💾 已保存 → {out_file}")
    return True


# ════════════════════════════════════════════════════════════════════════════
# 批量处理
# ════════════════════════════════════════════════════════════════════════════

def process_folder(input_folder: str, output_folder: str, cfg: dict):
    input_path  = Path(input_folder)
    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    files = sorted(f for f in input_path.iterdir() if f.suffix.lower() in {".txt", ".md"})
    if not files:
        print(f"⚠ 在 '{input_folder}' 中未找到 .txt / .md 文件")
        return

    print(f"\n🎙 共找到 {len(files)} 个录音稿\n{'═' * 60}")
    ok = fail = 0
    for f in files:
        print(f"\n📂 开始处理：{f.name}")
        try:
            if process_file(f, output_path, cfg):
                ok += 1
            else:
                fail += 1
        except Exception as e:
            print(f"  ❌ 失败：{e}")
            fail += 1

    print(f"\n{'═' * 60}")
    print(f"✅ 完成！成功 {ok} 个，失败 {fail} 个")
    print(f"📁 输出目录：{output_path.resolve()}")


# ════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="录音稿自动润色脚本 v2（SiliconFlow / Kimi2.5，LLM智能分段）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              python transcript_polisher.py
              python transcript_polisher.py -i my_raws -o my_output
              python transcript_polisher.py --api-key sk-xxx
        """),
    )
    parser.add_argument("-i", "--input",     default=CONFIG["input_folder"],  help="输入文件夹")
    parser.add_argument("-o", "--output",    default=CONFIG["output_folder"], help="输出文件夹")
    parser.add_argument("--api-key",         default=None,                    help="SiliconFlow API Key")
    parser.add_argument("--model",           default=CONFIG["model"],         help="模型名称")
    parser.add_argument("--api-base",        default=CONFIG["api_base"],      help="API Base URL")
    parser.add_argument("--temperature",     type=float, default=CONFIG["temperature"])
    args = parser.parse_args()

    cfg = CONFIG.copy()
    if args.api_key:
        cfg["api_key"] = args.api_key
    cfg.update(model=args.model, api_base=args.api_base, temperature=args.temperature)

    if cfg["api_key"] in ("YOUR_API_KEY_HERE", "", None):
        print("❌ 未设置 API Key，请使用以下任一方式：")
        print("   export SILICONFLOW_API_KEY=sk-xxx")
        print("   python transcript_polisher.py --api-key sk-xxx")
        return

    process_folder(args.input, args.output, cfg)


if __name__ == "__main__":
    main()
