# Descent Curve: Episode Adoption Analysis

## Summary

In the 15-run sysinfo_report experiment, episode injection produced a bimodal outcome:
- **4 runs adopted** the episode (2 LLM calls, ~2,450 tokens)
- **11 runs ignored** the episode (7 LLM calls, ~9,700 tokens)

Adoption rate: 26%. Cost reduction when adopted: 75%.

## Trace Analysis

### What "adoption" looks like
When the model adopts the episode, it executes all necessary shell commands in a single LLM response (batching 3-4 commands), then produces a summary. Total: 2 LLM calls.

### What "ignoring" looks like
When the model ignores the episode, it explores step-by-step: try `lscpu` (fail on macOS), try `uname`, try `sysctl`, try `df`, etc. Each command is a separate LLM call. Total: 7 LLM calls.

### Adoption pattern
Hits occurred at runs [3, 4, 10, 11] — always in consecutive pairs. No trend over time (not improving with more episodes). This rules out "model learns over time" — adoption is stochastic, not progressive.

## Root Cause: Hypothesis A Confirmed

The episode hint is injected as one item in the `knowledge_hints` list within the system prompt. The model treats it as optional context — sometimes it reads and follows it, sometimes it ignores it entirely.

Evidence:
- No correlation between run index and adoption (not learning)
- Consecutive pairs suggest session-level randomness (same prompt → same behavior on retry)
- The hint format ("You may reuse this approach") is explicitly non-directive

## Failed Fix Attempt

We tried reformatting the episode as a `<plan>` block with "IMPORTANT: Execute directly" prefix. Result: **0% adoption** (worse than baseline). The plan-format injection conflicted with the V3 action loop's own plan mechanism, causing the model to generate even more exploratory steps.

## Proposed Improvements (Not Yet Implemented)

1. **Position the hint earlier** — move from knowledge_hints (buried in system prompt) to the user message itself or as an assistant-prefill
2. **Make adoption a binary decision** — force the model to output "ADOPT" or "EXPLORE" before acting, so it cannot silently ignore
3. **Add confidence metadata** — "verified 5/5 times, last used 30s ago" gives the model reason to trust
4. **Conditional injection** — only inject when task signature matches with high similarity, preventing irrelevant episodes from reducing overall trust

## Implications for the Descent Curve Claim

The mechanism works. The reliability doesn't. This means:
- Educe CAN reduce cost by 75% on repeated tasks
- Educe DOES NOT reliably do so yet (26% of the time)
- The remaining 74% is not "failed execution" — the model simply solves the task from scratch successfully, just at full cost

This is architecturally significant: the bottleneck is in the **model's attention/compliance**, not in the framework's episode storage or retrieval.
