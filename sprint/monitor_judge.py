"""Conversation-only AI judge as a monitor.

Reads the scores that judge.py saved in sprint/judge_scores.json; it never calls
the API itself. If an episode has not been judged yet, every agent scores 0 and a
warning is printed once, so a missing judgement is visible rather than silent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from judge import CACHE, fingerprint

_cache: Dict[str, Any] = {}
_warned = False


def ai_judge(view: Dict[str, Any]) -> Dict[str, float]:
    global _cache, _warned
    if not _cache and CACHE.exists():
        _cache = json.load(open(CACHE))
    result = _cache.get(fingerprint(view))
    if result is None:
        if not _warned:
            print("  [ai_judge] some episodes have no judgement yet: run sprint/judge.py first")
            _warned = True
        return {a: 0.0 for a in view["agents"]}
    return {a: float(result["agents"].get(a, 0.0)) for a in view["agents"]}