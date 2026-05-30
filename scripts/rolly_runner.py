"""
Rolly test runner.

Usage:
    uv run python scripts/rolly_runner.py                        # with system prompt
    uv run python scripts/rolly_runner.py --no-prompt            # without system prompt
    uv run python scripts/rolly_runner.py --compare              # runs both and shows diff
    uv run python scripts/rolly_runner.py --id A01 B02           # run specific tests
    uv run python scripts/rolly_runner.py --category off_topic   # run a specific category (events, historical_tips, ...)
    uv run python scripts/rolly_runner.py --out results.json     # save JSON results
    uv run python scripts/rolly_runner.py --log run.txt          # save CLI output to file
    uv run python scripts/rolly_runner.py -v --log run.txt       # verbose + save to file
"""

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx


class _Tee:
    """Write to both stdout and a file simultaneously."""
    def __init__(self, file_path: str):
        self._file = open(file_path, "w", encoding="utf-8")
        self._stdout = sys.stdout

    def write(self, data):
        self._stdout.write(data)
        self._file.write(data)

    def flush(self):
        self._stdout.flush()
        self._file.flush()

    def close(self):
        self._file.close()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.rolly_tests import TESTS

BACKEND_URL = "http://localhost/api/rolly/chat"
REQUEST_DELAY = 1.0  # seconds between requests to avoid overloading LM Studio


# ──────────────────────────────────────────────────────────────────
# Evaluator
# ──────────────────────────────────────────────────────────────────

def _tool_names(tool_calls: list[dict]) -> list[str]:
    return [tc["name"] for tc in tool_calls]


def _tool_args_flat(tool_calls: list[dict]) -> dict:
    """Merge all tool args into one dict for easy lookup."""
    merged = {}
    for tc in tool_calls:
        for k, v in tc.get("args", {}).items():
            merged[f"{tc['name']}.{k}"] = v
            merged[k] = v  # also without prefix for convenience
    return merged


def evaluate_criterion(criterion: str, response: str, tool_calls: list[dict]) -> tuple[bool, str]:
    """
    Returns (passed, reason).
    Evaluates what it can automatically; marks the rest as manual_review.
    """
    c = criterion.lower().strip()
    names = _tool_names(tool_calls)
    args = _tool_args_flat(tool_calls)
    resp_lower = response.lower()

    # ── Tool presence ──────────────────────────────────────────────
    if c.startswith("calls ") and " not " in c:
        parts = c.replace("calls ", "").split(" not ")
        must, must_not = parts[0].strip(), parts[1].strip()
        if must not in names:
            return False, f"expected {must} in tool calls, got {names}"
        if must_not in names:
            return False, f"{must_not} should NOT have been called"
        return True, "ok"

    if c.startswith("calls "):
        tool = c.replace("calls ", "").strip()
        if tool not in names:
            return False, f"expected {tool}, got {names}"
        return True, "ok"

    if c == "no tool called" or c == "no tools called":
        if names:
            return False, f"expected no tools, got {names}"
        return True, "ok"

    if c == "both tools called":
        return True, "manual_review — check that both expected tools fired"

    # ── Tool argument checks ───────────────────────────────────────
    for key in ("is_fhvhv", "hours_from_now", "top_n", "max_hours", "time_of_day", "zone_name", "day"):
        # "key=value not key=other_value"
        if f"{key}=" in c and " not " in c:
            parts = c.split(" not ")
            ok_val = _parse_value(parts[0].split(f"{key}=")[1].strip())
            bad_val = _parse_value(parts[1].split(f"{key}=")[1].strip()) if f"{key}=" in parts[1] else None
            actual = args.get(key)
            if actual is None:
                return False, f"{key} not found in args"
            if str(actual).lower() != str(ok_val).lower():
                return False, f"{key}={actual} expected {ok_val}"
            if bad_val is not None and str(actual).lower() == str(bad_val).lower():
                return False, f"{key} should not be {bad_val}"
            return True, "ok"

        # "key=value"
        if c.startswith(f"{key}=") or f" {key}=" in c:
            val_str = c.split(f"{key}=")[1].split()[0].rstrip(".,")
            expected = _parse_value(val_str)
            actual = args.get(key)
            if actual is None:
                return False, f"{key} not found in args"
            if str(actual).lower() != str(expected).lower():
                return False, f"{key}={actual} expected {expected}"
            return True, "ok"

        # "zone_name contains 'X'"
        if f"{key} contains" in c:
            substr = c.split(f"{key} contains")[1].strip().strip("'\"")
            actual = str(args.get(key, "")).lower()
            if substr.lower() not in actual:
                return False, f"{key}='{args.get(key)}' does not contain '{substr}'"
            return True, "ok"

    # ── Response text checks ───────────────────────────────────────
    if "response mentions" in c:
        word = c.split("response mentions")[1].strip().strip("'\"")
        if word.lower() not in resp_lower:
            return False, f"'{word}' not found in response"
        return True, "ok"

    if "response is in spanish" in c:
        spanish_markers = ["el ", "la ", "los ", "las ", "es ", "en ", "de ", "para ", "zona", "taxista", "demanda"]
        if not any(m in resp_lower for m in spanish_markers):
            return False, "response does not appear to be in Spanish"
        return True, "ok"

    if "no 'pulocationid'" in c or "no raw numeric id" in c or "no zone id" in c:
        if "pulocationid" in resp_lower:
            return False, "response contains 'PULocationID'"
        return True, "ok"

    if "includes borough" in c or "includes zone name and borough" in c:
        boroughs = ["manhattan", "brooklyn", "queens", "bronx", "staten island", "ewr"]
        if not any(b in resp_lower for b in boroughs):
            return False, "no borough found in response"
        return True, "ok"

    if "politely declines or redirects" in c or "declines" in c:
        decline_words = ["sorry", "can't", "cannot", "only", "focus", "assist", "help you with", "driving", "taxi", "zone", "demand", "don't track", "don't cover", "not track", "general news", "news stories", "outside"]
        if not any(w in resp_lower for w in decline_words):
            return False, "does not appear to decline or redirect"
        return True, "ok"

    if "asks yellow or fhvhv" in c or "asks for service type" in c:
        ask_words = ["yellow", "fhvhv", "rideshare", "service", "which", "type", "driving"]
        if not any(w in resp_lower for w in ask_words):
            return False, "does not appear to ask for service type"
        return True, "ok"

    if "asks for clarification" in c:
        clarification_words = ["?", "yellow", "fhvhv", "rideshare", "service", "which", "type", "driving", "demand", "tip", "historical", "predicted", "mean", "looking for", "what kind"]
        if not any(w in resp_lower for w in clarification_words):
            return False, "does not appear to ask for clarification"
        return True, "ok"

    if "asks" in c and "hour" in c:
        if not any(w in resp_lower for w in ["hour", "when", "how long", "next"]):
            return False, "does not ask for hour"
        return True, "ok"

    if "lists every next_hour as bullet" in c or "lists all hours" in c:
        # Response must contain at least 3 numeric lines (hours as bullets/rows)
        bullet_lines = [l for l in response.split("\n") if any(ch in l for ch in ["-", "•", "*", "|"]) and any(ch.isdigit() for ch in l)]
        if len(bullet_lines) < 3:
            return False, f"expected multiple hour rows, found {len(bullet_lines)} bullet lines with numbers"
        return True, "ok"

    if "gracefully handles" in c:
        error_words = ["not found", "no data", "couldn't find", "no zone", "error", "sorry", "available", "not in", "isn't in", "does not exist", "doesn't exist", "dataset", "data set"]
        if not any(w in resp_lower for w in error_words):
            return False, "does not appear to handle error gracefully"
        return True, "ok"

    # ── Default: manual review ─────────────────────────────────────
    return True, f"manual_review — '{criterion}'"


def _parse_value(s: str):
    s = s.strip().strip("'\"")
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _check_expected_data(expected_data: dict, response: str) -> list[dict]:
    results = []
    resp_lower = response.lower()

    top_zone = expected_data.get("top_zone", "")
    top_value = expected_data.get("top_value", 0)
    value_label = expected_data.get("value_label", "value")

    if top_zone:
        if top_zone.lower() in resp_lower:
            results.append({"criterion": f"[data] response mentions top zone '{top_zone}'", "passed": True, "reason": "ok"})
        else:
            results.append({"criterion": f"[data] response mentions top zone '{top_zone}'", "passed": False, "reason": f"'{top_zone}' not found in response"})

    if top_value and top_value > 0:
        numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", response.replace(",", ""))]
        tolerance = top_value * 0.15
        close = any(abs(n - top_value) <= tolerance for n in numbers)
        if close:
            results.append({"criterion": f"[data] {value_label} ≈ {top_value} (±15%)", "passed": True, "reason": "ok"})
        else:
            results.append({"criterion": f"[data] {value_label} ≈ {top_value} (±15%)", "passed": False, "reason": f"no number within 15% of {top_value} found; got {numbers[:10]}"})

    return results


def evaluate_test(test: dict, response: str, tool_calls: list[dict]) -> dict:
    results = []
    all_pass = True

    # Check expected tools called
    if test["expected_tools"] and not test["no_tools"]:
        for expected in test["expected_tools"]:
            if expected not in _tool_names(tool_calls):
                results.append({"criterion": f"[tool] {expected} called", "passed": False, "reason": f"not in {_tool_names(tool_calls)}"})
                all_pass = False
            else:
                results.append({"criterion": f"[tool] {expected} called", "passed": True, "reason": "ok"})

    if test["no_tools"] and _tool_names(tool_calls):
        results.append({"criterion": "[tool] no tools called", "passed": False, "reason": f"got {_tool_names(tool_calls)}"})
        all_pass = False
    elif test["no_tools"]:
        results.append({"criterion": "[tool] no tools called", "passed": True, "reason": "ok"})

    # Check tool_args against actual calls
    tool_args_expected = test.get("tool_args", {})
    if tool_args_expected and tool_calls:
        actual_args = _tool_args_flat(tool_calls)
        for key, expected_val in tool_args_expected.items():
            actual_val = actual_args.get(key)
            if actual_val is None:
                results.append({"criterion": f"[arg] {key}={expected_val}", "passed": False, "reason": f"{key} not found in tool args"})
                all_pass = False
            elif isinstance(expected_val, str):
                # For string args (zone_name, time_of_day, day) use substring match
                if str(expected_val).lower() not in str(actual_val).lower():
                    results.append({"criterion": f"[arg] {key} contains '{expected_val}'", "passed": False, "reason": f"got {key}='{actual_val}'"})
                    all_pass = False
                else:
                    results.append({"criterion": f"[arg] {key} contains '{expected_val}'", "passed": True, "reason": "ok"})
            elif str(actual_val).lower() != str(expected_val).lower():
                results.append({"criterion": f"[arg] {key}={expected_val}", "passed": False, "reason": f"got {key}={actual_val}"})
                all_pass = False
            else:
                results.append({"criterion": f"[arg] {key}={expected_val}", "passed": True, "reason": "ok"})

    # Check expected_data accuracy
    for item in _check_expected_data(test.get("expected_data", {}), response):
        results.append(item)
        if not item["passed"]:
            all_pass = False

    # Check pass_criteria
    for criterion in test["pass_criteria"]:
        passed, reason = evaluate_criterion(criterion, response, tool_calls)
        results.append({"criterion": criterion, "passed": passed, "reason": reason})
        if not passed and "manual_review" not in reason:
            all_pass = False

    return {"passed": all_pass, "criteria": results}


# ──────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────

def run_test(test: dict, use_system_prompt: bool, client: httpx.Client) -> dict:
    payload = {
        "message": test["message"],
        "history": [],
        "debug": True,
        "system_prompt_override": None if use_system_prompt else "",
    }
    try:
        r = client.post(BACKEND_URL, json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        response = data["response"]
        tool_calls = data.get("tool_calls_made", [])
        evaluation = evaluate_test(test, response, tool_calls)
        return {
            "id": test["id"],
            "category": test["category"],
            "description": test["description"],
            "input": test["message"],
            "response": response,
            "tool_calls_made": tool_calls,
            "evaluation": evaluation,
            "error": None,
        }
    except Exception as e:
        return {
            "id": test["id"],
            "category": test["category"],
            "description": test["description"],
            "input": test["message"],
            "response": "",
            "tool_calls_made": [],
            "evaluation": {"passed": False, "criteria": [{"criterion": "request succeeded", "passed": False, "reason": str(e)}]},
            "error": str(e),
        }


def print_conversation(result: dict):
    """Print the full input/tools/output of a test in a readable format."""
    status = "✓ PASS" if result["evaluation"]["passed"] else "✗ FAIL"
    print(f"\n┌─ [{result['id']}] {result['description']} — {status}")
    print(f"│")
    print(f"│  USER: {result['input']}")

    if result["tool_calls_made"]:
        for tc in result["tool_calls_made"]:
            args_str = ", ".join(f"{k}={v!r}" for k, v in tc.get("args", {}).items())
            print(f"│  TOOL: {tc['name']}({args_str})")

    response_lines = result["response"].splitlines() if result["response"] else ["(no response)"]
    print(f"│  ROLLY: {response_lines[0]}")
    for line in response_lines[1:]:
        print(f"│         {line}")

    failed = [c for c in result["evaluation"]["criteria"] if not c["passed"] and "manual_review" not in c.get("reason", "")]
    if failed:
        print(f"│  FAILED CRITERIA:")
        for c in failed:
            print(f"│    ✗ {c['criterion']} → {c['reason']}")
    print(f"└{'─'*58}")


def run_suite(tests: list[dict], use_system_prompt: bool, verbose: bool = False) -> list[dict]:
    results = []
    label = "WITH system prompt" if use_system_prompt else "WITHOUT system prompt"
    print(f"\n{'='*60}")
    print(f"Running {len(tests)} tests — {label}")
    print("="*60)

    with httpx.Client() as client:
        for i, test in enumerate(tests, 1):
            print(f"  [{i:>3}/{len(tests)}] {test['id']} {test['description'][:50]}", end=" ", flush=True)
            result = run_test(test, use_system_prompt, client)
            status = "✓" if result["evaluation"]["passed"] else "✗"
            manual = sum(1 for c in result["evaluation"]["criteria"] if "manual_review" in c.get("reason", ""))
            print(f"→ {status}" + (f"  ({manual} manual)" if manual else ""))
            if verbose:
                print_conversation(result)
            results.append(result)
            if i < len(tests):
                time.sleep(REQUEST_DELAY)

    return results


def print_summary(results: list[dict], label: str):
    total = len(results)
    auto_pass = sum(1 for r in results if r["evaluation"]["passed"])
    errors = sum(1 for r in results if r["error"])

    print(f"\n{'─'*60}")
    print(f"SUMMARY — {label}")
    print(f"{'─'*60}")
    print(f"  Total:   {total}")
    print(f"  Pass:    {auto_pass} ({100*auto_pass//total}%)")
    print(f"  Fail:    {total - auto_pass - errors}")
    print(f"  Errors:  {errors}")

    by_cat = defaultdict(lambda: {"pass": 0, "total": 0})
    for r in results:
        cat = r["category"]
        by_cat[cat]["total"] += 1
        if r["evaluation"]["passed"]:
            by_cat[cat]["pass"] += 1

    print(f"\n  By category:")
    for cat, counts in sorted(by_cat.items()):
        p, t = counts["pass"], counts["total"]
        bar = "█" * p + "░" * (t - p)
        print(f"    {cat:<30} {bar}  {p}/{t}")

    # Failed tests
    failures = [r for r in results if not r["evaluation"]["passed"] and not r["error"]]
    if failures:
        print(f"\n  Failed tests:")
        for r in failures:
            failed_criteria = [c for c in r["evaluation"]["criteria"] if not c["passed"] and "manual_review" not in c.get("reason", "")]
            for c in failed_criteria:
                print(f"    [{r['id']}] {c['criterion']} → {c['reason']}")


def print_comparison(with_prompt: list[dict], without_prompt: list[dict]):
    print(f"\n{'='*60}")
    print("COMPARISON: WITH vs WITHOUT system prompt")
    print("="*60)
    ids = [r["id"] for r in with_prompt]
    wp_map = {r["id"]: r for r in with_prompt}
    wop_map = {r["id"]: r for r in without_prompt}

    regressions, improvements = [], []
    for id_ in ids:
        wp = wp_map[id_]["evaluation"]["passed"]
        wop = wop_map[id_]["evaluation"]["passed"]
        if wp and not wop:
            regressions.append(id_)
        elif not wp and wop:
            improvements.append(id_)

    if regressions:
        print(f"\n  Tests that PASS with prompt but FAIL without ({len(regressions)}):")
        for id_ in regressions:
            print(f"    {id_} — {wp_map[id_]['description']}")
    if improvements:
        print(f"\n  Tests that FAIL with prompt but PASS without ({len(improvements)}):")
        for id_ in improvements:
            print(f"    {id_} — {wp_map[id_]['description']}")
    if not regressions and not improvements:
        print("  No differences found between the two runs.")


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Rolly test runner")
    parser.add_argument("--no-prompt", action="store_true", help="Run without system prompt")
    parser.add_argument("--compare", action="store_true", help="Run with and without system prompt and compare")
    parser.add_argument("--id", nargs="+", help="Run only specific test IDs")
    parser.add_argument("--category", help="Run only tests in this category")
    parser.add_argument("--out", help="Save results to JSON file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full conversation (input, tools, response) for each test")
    parser.add_argument("--log", metavar="FILE", help="Save CLI output to a text file (also prints to terminal)")
    args = parser.parse_args()

    tee = None
    if args.log:
        tee = _Tee(args.log)
        sys.stdout = tee

    tests = TESTS
    if args.id:
        tests = [t for t in tests if t["id"] in args.id]
    if args.category:
        tests = [t for t in tests if t["category"] == args.category]

    if not tests:
        print("No tests matched the filter.")
        sys.exit(1)

    output = {}

    if args.compare:
        with_results = run_suite(tests, use_system_prompt=True, verbose=args.verbose)
        without_results = run_suite(tests, use_system_prompt=False, verbose=args.verbose)
        print_summary(with_results, "WITH system prompt")
        print_summary(without_results, "WITHOUT system prompt")
        print_comparison(with_results, without_results)
        output = {"with_prompt": with_results, "without_prompt": without_results}
    else:
        use_prompt = not args.no_prompt
        results = run_suite(tests, use_system_prompt=use_prompt, verbose=args.verbose)
        label = "WITH system prompt" if use_prompt else "WITHOUT system prompt"
        print_summary(results, label)
        output = {"results": results}

    if args.out:
        Path(args.out).write_text(json.dumps(output, indent=2, ensure_ascii=False))
        print(f"\n  Results saved to {args.out}")

    if tee:
        sys.stdout = tee._stdout
        tee.close()
        print(f"  Log saved to {args.log}")


if __name__ == "__main__":
    main()
