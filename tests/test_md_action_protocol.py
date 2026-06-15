"""Test Markdown-native action protocol"""
import sys
sys.path.insert(0, '.')

from deepforge.core.action_executor import parse_actions
from deepforge.core.context_manager import build_context

# Test 1: 两个 shell action
test1 = "我来帮你安装。\n\n```shell\ngit clone https://github.com/xxx/yyy /tmp/test\n```\n\n```shell\npip install -e /tmp/test\n```\n"
_, actions = parse_actions(test1)
print(f"Test1 (两个shell): {len(actions)} actions → types={[a.type for a in actions]}")
assert len(actions) == 2
assert actions[0].type == "shell"
assert "git clone" in actions[0].params

# Test 2: write_file heredoc
test2 = "```write_file\npath: /tmp/demo.py\n---\nimport os\nprint('hello')\n```\n"
_, actions2 = parse_actions(test2)
print(f"Test2 (write_file): {len(actions2)} actions, type={actions2[0].type}")
assert actions2[0].type == "write_file"
assert "path:" in actions2[0].params

# Test 3: XML fallback
test3 = '<action type="shell">ls -la</action>'
_, actions3 = parse_actions(test3)
print(f"Test3 (XML fallback): {len(actions3)} actions → {actions3[0].type}:{actions3[0].params}")
assert actions3[0].type == "shell"

# Test 4: 普通代码块不误判
test4 = "代码：\n```python\ndef hello():\n    print('hi')\n```\n"
_, actions4 = parse_actions(test4)
print(f"Test4 (普通代码不误判): {len(actions4)} actions (should be 0)")
assert len(actions4) == 0

# Test 5: memorize
test5 = "```memorize\n用户喜欢暗色主题\n```\n"
_, actions5 = parse_actions(test5)
print(f"Test5 (memorize): {len(actions5)} actions, type={actions5[0].type}")
assert actions5[0].type == "memorize"

# Test 6: build_context 输出格式
ctx = build_context()
assert "```shell" in ctx
assert "<action" not in ctx
print(f"Test6 (context prompt): Markdown format ✓, no XML ✓")

# Test 7: tool:connector.name 格式
test7 = "```tool:filesystem.search_files\n{\"path\":\".\",\"pattern\":\"test\"}\n```\n"
_, actions7 = parse_actions(test7)
print(f"Test7 (tool:connector): {len(actions7)} actions, type={actions7[0].type}, name={actions7[0].name}")
assert actions7[0].type == "use_tool"
assert actions7[0].name == "filesystem.search_files"

# Test 8: reply_text 正确剥离 action
test8 = "我来执行：\n\n```shell\nls\n```\n\n完成了。"
reply, actions8 = parse_actions(test8)
print(f"Test8 (reply_text): actions={len(actions8)}, reply='{reply[:30]}'")
assert len(actions8) == 1
assert "我来执行" in reply

print("\n=== ALL TESTS PASSED ===")
