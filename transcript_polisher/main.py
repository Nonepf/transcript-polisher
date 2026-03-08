"""
main.py — CLI 入口

解析命令行参数，覆盖 CONFIG 中对应键，然后启动批量处理流程。
该文件只负责参数解析和启动，不含任何业务逻辑。
"""

import argparse
import textwrap

from .config   import CONFIG
from .pipeline import process_folder


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="transcript-polisher",
        description="录音稿自动润色脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例：
              transcript-polisher
              transcript-polisher -i my_raws -o my_output
              transcript-polisher --api-key sk-xxx --workers 5
              transcript-polisher --rpm 450 --tpm 1800000
        """),
    )

    # ── 路径 ─────────────────────────────────────────────────────────────────
    parser.add_argument("-i", "--input",  default=CONFIG["input_folder"],  help="输入文件夹（默认 recording_raw）")
    parser.add_argument("-o", "--output", default=CONFIG["output_folder"], help="输出文件夹（默认 recording_polished）")

    # ── API ───────────────────────────────────────────────────────────────────
    parser.add_argument("--api-key",  default=None,            help="SiliconFlow API Key（也可设环境变量 SILICONFLOW_API_KEY）")
    parser.add_argument("--api-base", default=CONFIG["api_base"], help="API Base URL")
    parser.add_argument("--model",    default=CONFIG["model"],    help="模型名称")

    # ── LLM 参数 ──────────────────────────────────────────────────────────────
    parser.add_argument("--temperature", type=float, default=CONFIG["temperature"], help="采样温度（默认 0.3）")

    # ── 并发 & 限速 ───────────────────────────────────────────────────────────
    parser.add_argument(
        "--workers", type=int, default=CONFIG["max_workers"],
        help=f"并发线程数（默认 {CONFIG['max_workers']}，设为 1 可严格保证串行上下文）",
    )
    parser.add_argument(
        "--rpm", type=int, default=CONFIG["rpm_limit"],
        help=f"每分钟最大请求数（默认 {CONFIG['rpm_limit']}）",
    )
    parser.add_argument(
        "--tpm", type=int, default=CONFIG["tpm_limit"],
        help=f"每分钟最大 token 数（默认 {CONFIG['tpm_limit']:,}）",
    )

    args = parser.parse_args()

    # ── 构建运行时 cfg ────────────────────────────────────────────────────────
    cfg = CONFIG.copy()
    if args.api_key:
        cfg["api_key"] = args.api_key
    cfg.update(
        input_folder  = args.input,
        output_folder = args.output,
        api_base      = args.api_base,
        model         = args.model,
        temperature   = args.temperature,
        max_workers   = args.workers,
        rpm_limit     = args.rpm,
        tpm_limit     = args.tpm,
    )

    if cfg["api_key"] in ("YOUR_API_KEY_HERE", "", None):
        print("❌ 未设置 API Key，请使用以下任一方式：")
        print("   export SILICONFLOW_API_KEY=sk-xxx")
        print("   transcript-polisher --api-key sk-xxx")
        return

    process_folder(cfg["input_folder"], cfg["output_folder"], cfg)


if __name__ == "__main__":
    main()
