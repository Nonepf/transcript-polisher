"""
pipeline.py — 处理流程编排

read_file():      读取 .txt / .md 文件，自动探测编码。
process_file():   单文件完整处理流程（分段 → 润色 → 提取 → 写出）。
process_folder(): 批量扫描文件夹，顺序调用 process_file()。
"""

import time
from pathlib import Path

from .api_client   import init_rate_limiter
from .polisher     import extract_key_info, polish_all_chunks
from .rate_limiter import safe_print
from .renderer     import render_report
from .segmenter    import segment

SUPPORTED_SUFFIXES = {".txt", ".md"}


# ════════════════════════════════════════════════════════════════════════════
# 文件读取
# ════════════════════════════════════════════════════════════════════════════

def read_file(path: Path) -> str:
    """
    读取文本文件，自动尝试常见编码。

    Raises:
        ValueError: 不支持的文件格式，或所有编码均解码失败。
    """
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"不支持的格式 {path.suffix}，仅支持 .txt / .md")

    for enc in ("utf-8", "utf-8-sig", "gbk", "gb2312"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue

    raise ValueError(f"无法解码文件（已尝试 utf-8 / gbk）: {path}")


# ════════════════════════════════════════════════════════════════════════════
# 单文件处理
# ════════════════════════════════════════════════════════════════════════════

def process_file(file: Path, output_path: Path, cfg: dict) -> bool:
    """
    对单个录音稿文件执行完整润色流程：
      1. 读取原文
      2. LLM 分段（含兜底）
      3. 并发润色各段落
      4. 提取关键信息
      5. 渲染并写出 Markdown 报告

    Returns:
        True 表示成功，False 表示跳过（如文件过短）。
    """
    original = read_file(file)
    if len(original.strip()) < 30:
        safe_print("  ⚠ 内容过短，跳过")
        return False

    t0 = time.monotonic()
    safe_print(f"  📄 {file.name}  ·  {len(original):,} 字")

    # Step 1：分段
    chunks, plan = segment(original, cfg)

    # Step 2：并发润色
    polished = polish_all_chunks(chunks, cfg)

    # Step 3：关键信息提取
    key_info = extract_key_info(polished, cfg)

    # Step 4：渲染 & 写出
    content  = render_report(file.name, original, polished, key_info, plan)
    out_file = output_path / f"{file.stem}_polished.md"
    out_file.write_text(content, encoding="utf-8")

    elapsed = time.monotonic() - t0
    safe_print(f"  💾 已保存 → {out_file}  （耗时 {elapsed:.1f}s）")
    return True


# ════════════════════════════════════════════════════════════════════════════
# 批量处理
# ════════════════════════════════════════════════════════════════════════════

def process_folder(input_folder: str, output_folder: str, cfg: dict) -> None:
    """
    扫描 input_folder 中所有支持格式的文件，逐个调用 process_file()。
    文件间串行处理；段落内并发由 polish_all_chunks() 控制。
    """
    input_path  = Path(input_folder)
    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    files = sorted(
        f for f in input_path.iterdir()
        if f.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not files:
        print(f"⚠ 在 '{input_folder}' 中未找到 .txt / .md 文件")
        return

    # 初始化全局令牌桶（整个批次共享）
    init_rate_limiter(cfg["rpm_limit"], cfg["tpm_limit"])

    print(f"\n🎙 共找到 {len(files)} 个录音稿")
    print(
        f"⚙  并发线程: {cfg['max_workers']}  |  "
        f"RPM 上限: {cfg['rpm_limit']}  |  "
        f"TPM 上限: {cfg['tpm_limit']:,}"
    )
    print("═" * 60)

    ok = fail = 0
    for f in files:
        print(f"\n📂 开始处理：{f.name}")
        try:
            if process_file(f, output_path, cfg):
                ok += 1
            else:
                fail += 1
        except Exception as exc:
            print(f"  ❌ 失败：{exc}")
            fail += 1

    print(f"\n{'═' * 60}")
    print(f"✅ 完成！成功 {ok} 个，失败 {fail} 个")
    print(f"📁 输出目录：{output_path.resolve()}")
