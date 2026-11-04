"""Run the selected scheduler against a fully synthetic question bank.

Usage: python -B examples/schedule_demo.py --scenario all
       python -B examples/schedule_demo.py --scenario balanced --json
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import training_schedule_v7 as scheduler


# An abstract clock for reproducible examples, not a real user's timestamp.
NOW = 100 * scheduler.DAY
DEFAULT_SEED = "qipuwu-showcase-v1"
SCENARIOS = {
    "balanced": (12, 12, 8),
    "new-short": (2, 12, 8),
    "review-short": (12, 2, 8),
    "small": (3, 4, 5),
    "concentrated": (12, 12, 2),
}


def validate_settings(new_count, review_count, source_count, seed):
    for label, value in (("new", new_count), ("review", review_count)):
        if type(value) is not int or not 0 <= value <= 100:
            raise ValueError(f"{label} must be an integer from 0 to 100")
    if type(source_count) is not int or not 1 <= source_count <= 100:
        raise ValueError("sources must be an integer from 1 to 100")
    if not isinstance(seed, str) or not seed or len(seed) > 96:
        raise ValueError("seed must contain 1 to 96 characters")


def make_candidates(new_count=12, review_count=12, source_count=8):
    """Create fictional IDs, sources, timing and outcomes; never read a file."""
    validate_settings(new_count, review_count, source_count, DEFAULT_SEED)
    candidates = []
    for pool, count in (("N", new_count), ("R", review_count)):
        for index in range(count):
            days_ago = 1 + index % 12
            waiting_days = 1 + index % 30
            candidates.append({
                "id": f"{pool.lower()}{index + 1:02d}",
                "pool": pool,
                "source_key": f"synthetic-game-{index % source_count + 1:02d}",
                "created": NOW - 30 * scheduler.DAY,
                "learned": NOW - days_ago * scheduler.DAY,
                "ticket": NOW - waiting_days * scheduler.DAY,
                "last_submitted": NOW - days_ago * scheduler.DAY if pool == "R" else 0,
                "interval_days": 3,
                "next_due": NOW + (3 - days_ago) * scheduler.DAY,
                "practice_learning": {
                    "outcomes": (["blunder", "improve", "pass"]
                                 if pool == "R" and index % 3 == 0 else ["pass", "pass"])
                },
            })
    return candidates


def priority_examples():
    """Hold all other inputs fixed to explain the weight, not a pass rate."""
    base = make_candidates(0, 1, 1)[0]
    comparisons = []
    for label, days, outcomes in (
        ("近期完成，近期通过", 1, ["pass", "pass"]),
        ("等待较久，近期通过", 10, ["pass", "pass"]),
        ("近期完成，近期未达标", 1, ["blunder", "improve"]),
        ("等待较久，近期未达标", 10, ["blunder", "improve"]),
    ):
        candidate = dict(base, last_submitted=NOW - days * scheduler.DAY,
                         practice_learning={"outcomes": list(outcomes)})
        weight, components = scheduler.priority(candidate, NOW)
        comparisons.append(dict(label=label, days_since_answer=days,
                                weight=round(weight, 4), components=components))
    return comparisons


def run_demo(new_count=12, review_count=12, source_count=8, seed=DEFAULT_SEED):
    validate_settings(new_count, review_count, source_count, seed)
    candidates = make_candidates(new_count, review_count, source_count)
    selected = scheduler.select(candidates, seed=seed, now=NOW)
    sources = Counter(item["source_key"] for item in selected)
    mix = Counter(item["pool"] for item in selected)
    neighbors = sum(left["source_key"] == right["source_key"]
                    for left, right in zip(selected, selected[1:]))
    return {
        "kind": "synthetic scheduling demonstration",
        "policy": scheduler.POLICY,
        "settings": dict(new=new_count, review=review_count, sources=source_count, seed=seed),
        "plan": scheduler.plan(candidates, now=NOW),
        "summary": {
            "available": len(candidates), "selected": len(selected),
            "new": mix["N"], "review": mix["R"],
            "unique_sources": len(sources), "same_source_neighbors": neighbors,
        },
        "source_distribution": dict(sorted(sources.items())),
        "selected": selected,
        "priority_examples": priority_examples(),
    }


def print_result(name, result):
    summary = result["summary"]
    print(f"\n[{name}] seed={result['settings']['seed']}")
    print(f"Available: {summary['available']} | Selected: {summary['selected']} | "
          f"New/Review: {summary['new']}/{summary['review']} | "
          f"Sources: {summary['unique_sources']} | Same-source neighbors: {summary['same_source_neighbors']}")
    print(" #  item  pool  synthetic source       weight  mode")
    for position, item in enumerate(result["selected"], 1):
        metadata = item["selection_meta"]
        print(f"{position:2d}  {item['id']:4s}  {item['pool']:4s}  "
              f"{item['source_key']:22s}  {metadata['weight']:6.3f}  {metadata['mode']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=["all", *SCENARIOS], default="all")
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    args = parser.parse_args(argv)
    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    try:
        results = {name: run_demo(*SCENARIOS[name], seed=args.seed) for name in names}
    except ValueError as error:
        parser.error(str(error))
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    print("Qipuwu source showcase | synthetic inputs | no engine or database")
    for name, result in results.items():
        print_result(name, result)
    print("\nControlled priority comparison (weight affects sampling; it is not a guaranteed pick):")
    for row in priority_examples():
        print(f"  {row['label']}: {row['weight']:.3f}")
    print("\nSix-new/four-review is a product policy, not a proven optimal learning ratio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
