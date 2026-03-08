"""
transcript_polisher — 录音稿自动润色工具包

公共接口（可被外部脚本直接 import 使用）：
    from transcript_polisher import process_folder, process_file, CONFIG
"""

from .config   import CONFIG
from .pipeline import process_file, process_folder

__all__ = ["CONFIG", "process_file", "process_folder"]
