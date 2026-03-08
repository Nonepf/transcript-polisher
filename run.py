#!/usr/bin/env python3
"""
run.py — 直接运行入口（无需安装包）

用法：
    python run.py
    python run.py -i recording_raw -o recording_polished
    python run.py --api-key sk-xxx --workers 8
"""

from transcript_polisher.main import main

if __name__ == "__main__":
    main()
