"""
从200通对话中随机选100通，写sample_ids.txt
"""
import random
import sys
from pathlib import Path


def select(input_file: Path, output_dir: Path, n: int = 100, seed: int = 42):
    """随机选择n条session_id"""
    random.seed(seed)
    with input_file.open(encoding="utf-8") as f:
        ids = [json.loads(line)["session_id"] for line in f if line.strip()]
    if len(ids) < n:
        raise ValueError(f"总样本数{len(ids)}不足{n}")
    chosen = random.sample(ids, n)
    out = output_dir / "sample_ids.txt"
    with out.open("w", encoding="utf-8") as f:
        for sid in chosen:
            f.write(sid + "\n")
    print(f"✅ 已选{len(chosen)}条，写入{out}")


if __name__ == "__main__":
    import json

    root = Path(__file__).parent.parent
    in_file = root / "eval" / "gold.jsonl"
    if not in_file.exists():
        print("请准备gold.jsonl")
        sys.exit(1)
    select(in_file, root / "eval")