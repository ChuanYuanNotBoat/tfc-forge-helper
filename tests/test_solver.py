from collections import deque
from itertools import product

import pytest

from tfc_forge_helper.model import Action, Rule, parse_history, parse_rules
from tfc_forge_helper.solver import solve


def valid(history, rules):
    # Independent rule oracle over raw action names, chronological order.
    recent = ["hit" if a.name.startswith("HIT_") else a.name.lower() for a in history[-3:]][::-1]
    for rule in rules:
        indexes = {"last": [0], "second_last": [1], "third_last": [2],
                   "any": [0, 1, 2], "not_last": [1, 2]}[rule.order]
        if not any(i < len(recent) and recent[i] == rule.category for i in indexes):
            return False
    return True


def test_example_and_safety():
    rules = parse_rules("hit_third_last,draw_second_last,draw_last")
    result = solve(83, 108, rules)
    assert result.steps == 7
    assert result.positions[-1] == 108
    assert all(0 <= p <= 150 for p in result.positions)
    assert valid(result.actions, rules)


@pytest.mark.parametrize("strength", [Action.HIT_LIGHT, Action.HIT_MEDIUM, Action.HIT_HARD])
def test_any_hit_strength(strength):
    result = solve(100, 100 + strength.delta, (Rule("hit", "last"),))
    assert result.actions == (strength,)


def test_existing_history_zero_and_one_step():
    assert solve(100, 100, parse_rules("bend_second_last,punch_last"),
                 parse_history("bend,punch")).steps == 0
    result = solve(100, 102, parse_rules("bend_third_last,draw_second_last,punch_last"),
                   parse_history("bend,draw"))
    assert result.actions == (Action.PUNCH,)


def test_any_rules_can_share_a_step_and_not_last():
    assert solve(90, 92, parse_rules("punch_any,punch_last")).steps == 1
    result = solve(90, 92, parse_rules("punch_not_last"))
    assert result.steps > 1
    assert valid(result.actions, parse_rules("punch_not_last"))


def test_work_150_is_legal():
    assert solve(134, 150, parse_rules("shrink_last")).actions == (Action.SHRINK,)
    result = solve(0, 1, parse_rules("hit_last"))
    assert all(0 <= p <= 150 for p in result.positions)


def test_tolerance():
    assert solve(100, 101, parse_rules("punch_last"), tolerance=1).actions == (Action.PUNCH,)
    assert solve(100, 101, (), tolerance=1).steps == 0


@pytest.mark.parametrize("current,target,rules,history", [
    (0, 29, "upset_second_last,shrink_last", ""),
    (149, 134, "draw_last", ""),
    (3, 2, "hit_any,punch_last", ""),
    (110, 112, "bend_not_last,punch_last", "bend"),
    (50, 48, "hit_last", "draw,punch"),
])
def test_shortest_against_bruteforce(current, target, rules, history):
    rules, history = parse_rules(rules), parse_history(history)
    result = solve(current, target, rules, history)
    # Enumerate every shorter action sequence directly, without category graph compression.
    for length in range(result.steps):
        for candidate in product(Action, repeat=length):
            pos = current
            safe = True
            for action in candidate:
                pos += action.delta
                if not 0 <= pos <= 150:
                    safe = False
                    break
            assert not (safe and pos == target and valid(history + candidate, rules))
    assert valid(history + result.actions, rules)


def test_unconstrained_all_targets():
    distances = {0: 0}
    queue = deque([0])
    while queue:
        pos = queue.popleft()
        for delta in (-3, -6, -9, -15, 2, 7, 13, 16):
            nxt = pos + delta
            if 0 <= nxt <= 150 and nxt not in distances:
                distances[nxt] = distances[pos] + 1
                queue.append(nxt)
    for target in range(0, 151, 5):
        assert solve(0, target).steps == distances[target]


@pytest.mark.parametrize("args", [(-1, 30), (30, 151), (1.5, 80), (True, 80)])
def test_invalid_bounds(args):
    with pytest.raises(ValueError):
        solve(*args)


def test_conflicting_rules():
    with pytest.raises(ValueError, match="冲突"):
        solve(0, 100, parse_rules("bend_last,punch_last"))
