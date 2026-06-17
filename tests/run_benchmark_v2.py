"""
Educe Benchmark v2 全量运行脚本

用法:
  BENCH_API_KEY=xxx python3 tests/run_benchmark_v2.py [--model Kimi-K2] [--cases CODE-01,TECH-01]

环境变量:
  BENCH_API_KEY  - API key
  BENCH_BASE_URL - API base URL (默认 http://api.example.com/v1)
  BENCH_MODEL    - 模型名 (默认 Kimi-K2)
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, ".")

from tests.benchmark_cases import ALL_CASES
from educe.core.benchmark_runner import BenchmarkRunner


def main():
    parser = argparse.ArgumentParser(description="Educe Benchmark v2")
    parser.add_argument("--model", default=os.environ.get("BENCH_MODEL", "Kimi-K2"))
    parser.add_argument("--api-key", default=os.environ.get("BENCH_API_KEY", ""))
    parser.add_argument("--base-url", default=os.environ.get("BENCH_BASE_URL", "http://api.example.com/v1"))
    parser.add_argument("--cases", default="", help="逗号分隔的 case_id 过滤，空=全跑")
    parser.add_argument("--level", default="", help="L1/L2/L3 过滤")
    parser.add_argument("--domain", default="", help="CODE/FIN/TECH/EDU/LIFE/SCI 过滤")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: 需要设置 BENCH_API_KEY 环境变量")
        sys.exit(1)

    # Filter cases
    cases = ALL_CASES
    if args.cases:
        ids = set(args.cases.split(","))
        cases = [c for c in cases if c.case_id in ids]
    if args.level:
        cases = [c for c in cases if c.level == args.level]
    if args.domain:
        cases = [c for c in cases if c.domain == args.domain]

    if not cases:
        print("ERROR: 没有匹配的 case")
        sys.exit(1)

    print(f"Selected {len(cases)} cases (model={args.model})")

    runner = BenchmarkRunner(
        cases=cases,
        model_name=args.model,
        api_key=args.api_key,
        base_url=args.base_url,
        timeout_s=args.timeout,
    )
    asyncio.run(runner.run_all())


if __name__ == "__main__":
    main()
