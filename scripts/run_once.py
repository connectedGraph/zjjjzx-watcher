#!/usr/bin/env python3
"""
一次性快速抓取测试脚本 (One-shot run script)
直接以编程方式调用 zjjjzx 流水线。
"""
import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from zjjjzx import load_config, load_dotenv, run_pipeline


def main() -> int:
    load_dotenv()
    config = load_config()
    print("开始执行一次性抓取与评估流水线...")
    result = run_pipeline(config, dry_run=True, ignore_schedule=True)
    print(f"抓取完成: 共发现 {result['fetched']} 条，合格候选 {len(result['candidates'])} 条")
    if result.get("report_path"):
        print(f"HTML 报告已写入: {result['report_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
