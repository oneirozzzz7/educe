#!/usr/bin/env python3
"""
Simulate the output of reproduce_descent.py for demo recording purposes.

This script produces realistic terminal output matching the actual descent curve
experiment results, with timing delays for a natural recording feel.
Total runtime: ~18 seconds.
"""

import sys
import time


def print_slow(text, delay=0.03):
    """Print text with a slight delay per character for natural feel."""
    sys.stdout.write(text)
    sys.stdout.flush()
    time.sleep(delay)


def print_line(text="", delay=0.0):
    """Print a line and optionally wait."""
    print(text)
    sys.stdout.flush()
    if delay > 0:
        time.sleep(delay)


def main():
    # Simulated run data: (tokens, calls, reused)
    runs = [
        (9712, 7, False),
        (9685, 7, False),
        (2458, 2, True),
        (9701, 7, False),
        (9644, 7, False),
        (2412, 2, True),
        (9738, 7, False),
        (9692, 7, False),
        (9655, 7, False),
        (9721, 7, False),
        (2445, 2, True),
        (9688, 7, False),
        (9710, 7, False),
        (9669, 7, False),
        (2401, 2, True),
    ]

    # --- Header ---
    time.sleep(0.8)
    print_line()
    print_line("\033[1;36m\U0001f9ea The Descent Curve\033[0m — proving that Educe learns", 0.4)
    print_line("   Model: deepseek-chat | Runs per family: 15", 0.3)
    print_line()
    print_line("\033[90m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m", 0.5)
    print_line()

    # --- Task family ---
    print_line("\033[1;33m\U0001f4cb Task family:\033[0m env_system_info", 0.2)
    print_line('   "Find the Python version and summarize system info"', 0.4)
    print_line()

    # --- Runs ---
    for i, (tokens, calls, reused) in enumerate(runs, 1):
        # Format the run line
        num = f"Run {i:2d}"
        tok = f"{tokens:,} tokens"
        cal = f"{calls} calls"
        status = "\033[32m✓ correct\033[0m"
        suffix = "  \033[1;33m← experience reused!\033[0m" if reused else ""

        line = f"   {num} \033[90m│\033[0m {tok} \033[90m│\033[0m {cal} \033[90m│\033[0m {status}{suffix}"
        print_line(line)

        # Timing: faster for reused (instant), slower for full reasoning
        if reused:
            time.sleep(0.3)
        else:
            time.sleep(0.7)

    # --- Separator ---
    print_line()
    print_line("\033[90m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m", 0.8)
    print_line()

    # --- Results ---
    print_line("\033[1;36m\U0001f4ca Results:\033[0m", 0.3)
    print_line("   Experience adopted:  \033[1m4/15 runs (26.7%)\033[0m", 0.2)
    print_line("   Cost when adopted:   \033[1;32m2,429 tokens\033[0m (median)", 0.2)
    print_line("   Cost when ignored:   \033[1;31m9,693 tokens\033[0m (median)", 0.2)
    print_line("   Reduction:           \033[1;32m75.0%\033[0m", 0.2)
    print_line("   Correctness:         \033[1m15/15 (100%)\033[0m", 0.4)
    print_line()

    # --- Saved files ---
    print_line("   Saved to .educe/descent/", 0.2)
    print_line("     descent_curve.png \033[32m✓\033[0m", 0.15)
    print_line("     statistics.json   \033[32m✓\033[0m", 0.4)
    print_line()

    # --- Conclusion ---
    print_line(
        "\033[1;32m✅ The descent mechanism works.\033[0m "
        "Adoption reliability is the open frontier.",
        0.5,
    )
    print_line()


if __name__ == "__main__":
    main()
