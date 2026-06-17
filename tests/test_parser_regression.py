"""
Parser/Normalizer 回归测试集

从真实 Kimi-K2 benchmark 输出中收集的样本，验证 parse_actions 不回归。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from educe.core.action_executor import parse_actions


def run_tests():
    fixtures = json.loads(Path("tests/parser_fixtures.json").read_text())
    passed = 0
    failed = 0

    for i, f in enumerate(fixtures):
        text = f["input"]
        expected_count = f["expected_actions"]
        expected_type = f.get("expected_type", "")
        category = f["category"]

        reply, actions = parse_actions(text)

        # Check action count
        ok = True
        reason = ""
        if len(actions) != expected_count:
            ok = False
            reason = f"expected {expected_count} actions, got {len(actions)}"
        elif expected_type and actions and actions[0].type != expected_type:
            ok = False
            reason = f"expected type '{expected_type}', got '{actions[0].type}'"

        if ok:
            passed += 1
            print(f"  ✓ [{category}] fixture {i+1}")
        else:
            failed += 1
            print(f"  ✗ [{category}] fixture {i+1}: {reason}")
            print(f"    input preview: {text[:80]}...")
            if actions:
                print(f"    got: {[(a.type, a.params[:40]) for a in actions]}")

    print(f"\n{'='*40}")
    print(f"  {passed}/{passed+failed} passed, {failed} failed")
    print(f"{'='*40}")
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
