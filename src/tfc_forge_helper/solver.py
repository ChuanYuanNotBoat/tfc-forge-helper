"""Exact shortest path on (work, last three action categories).

Hit strengths share a rule category, but edges retain their distinct deltas.
Every action costs one step. The search keeps every intermediate work in 0..150.
"""
from collections import deque
from dataclasses import dataclass
from itertools import product

from .model import CATEGORIES, Action, Rule


@dataclass(frozen=True)
class Solution:
    current: int
    target: int
    actions: tuple[Action, ...]
    positions: tuple[int, ...]
    explored: int

    @property
    def steps(self) -> int:
        return len(self.actions)


def solve(current: int, target: int, rules: tuple[Rule, ...] = (),
          history: tuple[Action, ...] = (), tolerance: int = 0) -> Solution:
    if type(current) is not int or type(target) is not int or not 0 <= current <= 150 or not 0 <= target <= 150:
        raise ValueError("current 和 target 必须是 0–150 的整数")
    if type(tolerance) is not int or not 0 <= tolerance <= 150:
        raise ValueError("容差必须是 0–150 的整数，默认 0")
    rules, history = tuple(rules), tuple(history)
    if len(rules) > 3 or len(history) > 3:
        raise ValueError("规则和最近历史分别最多三项")
    if not all(isinstance(r, Rule) for r in rules) or not all(isinstance(a, Action) for a in history):
        raise ValueError("规则或历史的类型错误")
    if not any(all(r.matches(h) for r in rules) for h in product(CATEGORIES, repeat=3)):
        raise ValueError("规则互相冲突，没有可行的最后三步")

    # Precompute rule acceptance and history transitions independently of work.
    histories = [()]
    for length in (1, 2, 3):
        histories.extend(product(CATEGORIES, repeat=length))
    indexes = {h: i for i, h in enumerate(histories)}
    accepted = [all(r.matches(h) for r in rules) for h in histories]
    actions = tuple(Action)
    transitions = [[indexes[(h + (a.category,))[-3:]] for a in actions] for h in histories]
    width = len(histories)
    start = current * width + indexes[tuple(a.category for a in history)]
    parents = {start: None}
    edges = {}
    queue = deque([start])
    end = None
    while queue:
        state = queue.popleft()
        work, hi = divmod(state, width)
        if abs(work - target) <= tolerance and accepted[hi]:
            end = state
            break
        for ai, action in enumerate(actions):
            following = work + action.delta
            if 0 <= following <= 150:
                nxt = following * width + transitions[hi][ai]
                if nxt not in parents:
                    parents[nxt] = state
                    edges[nxt] = action
                    queue.append(nxt)
    if end is None:
        raise ValueError("在 0–150 的安全范围内没有满足规则的方案")
    path = []
    node = end
    while parents[node] is not None:
        path.append(edges[node])
        node = parents[node]
    path.reverse()
    positions = [current]
    for action in path:
        positions.append(positions[-1] + action.delta)
    return Solution(current, target, tuple(path), tuple(positions), len(parents))
