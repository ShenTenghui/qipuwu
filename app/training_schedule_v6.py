"""Necessary helper excerpt for the v7 source showcase.

Only _separate_games is retained from the original v6 module. The function body
is unchanged; historical v6 selection policies are intentionally not packaged.
See docs/source-provenance.md for source hashes and extraction details.
"""
from functools import lru_cache


def _separate_games(ordered):
    """Minimize same-game neighbors without changing the selected questions.

    Keep each game's existing internal order (in particular R before N/F).
    Equal optima favor the early N/R opportunities and then the old order.
    This bounded search runs only for a newly selected batch of at most 10.
    """
    if not any(a['source_key'] == b['source_key'] for a, b in zip(ordered, ordered[1:])):
        return ordered
    groups, group_by_source = [], {}
    for position, item in enumerate(ordered):
        source = item['source_key']
        if source not in group_by_source:
            group_by_source[source] = len(groups)
            groups.append([])
        groups[group_by_source[source]].append((position, item))
    initial = tuple(len(group) for group in groups)
    early_goal = {pool: min(2, sum(i['pool'] == pool for i in ordered))
                  for pool in ('N', 'R')}

    def prefix_penalty(remaining):
        seen = {'N': 0, 'R': 0}
        for group, count in zip(groups, remaining):
            for _, item in group[:len(group) - count]:
                if item['pool'] in seen:
                    seen[item['pool']] += 1
        return sum(max(0, goal - seen[pool]) for pool, goal in early_goal.items())

    @lru_cache(maxsize=None)
    def minimum(remaining, previous):
        if not any(remaining):
            return (0, 0)
        presented = len(ordered) - sum(remaining)
        prefix = prefix_penalty(remaining) if presented == 4 else 0
        best = None
        for index, count in enumerate(remaining):
            if not count:
                continue
            following = list(remaining)
            following[index] -= 1
            tail = minimum(tuple(following), index)
            cost = (int(index == previous) + tail[0], prefix + tail[1])
            if best is None or cost < best:
                best = cost
        return best

    result, remaining, previous = [], initial, -1
    while any(remaining):
        choices = []
        for index, count in enumerate(remaining):
            if count:
                position, item = groups[index][initial[index] - count]
                following = list(remaining)
                following[index] -= 1
                tail = minimum(tuple(following), index)
                choices.append((int(index == previous) + tail[0], tail[1], position,
                                index, item, tuple(following)))
        _, _, _, previous, item, remaining = min(choices, key=lambda c: c[:3])
        result.append(item)
    return result

