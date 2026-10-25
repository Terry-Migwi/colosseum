"""All monitors in one place. The harness (eval.py) reads MONITORS from here.

To add a monitor: write it in its own file, import it below, add one line.
Nothing else in the harness needs to change.
"""

from typing import Any, Dict

from monitors import MONITORS as BASE_MONITORS, say_do_combined
from monitor_justification import justification_coherence
from monitor_follow_through import follow_through
from monitor_judge import ai_judge


def say_do_all(view: Dict[str, Any]) -> Dict[str, float]:
    """Combined score: each agent's highest score across all say-vs-do monitors."""
    parts = [say_do_combined(view), justification_coherence(view), follow_through(view)]
    return {a: max(p[a] for p in parts) for a in view["agents"]}


MONITORS = {
    **{k: v for k, v in BASE_MONITORS.items() if k != "regret_baseline"},
    "justification_coherence": justification_coherence,  # monitor 2
    "follow_through": follow_through,                    # monitor 3
    "say_do_all": say_do_all,
    "regret_baseline": BASE_MONITORS["regret_baseline"],  # action-only baseline
    "ai_judge": ai_judge,  # conversation-only baseline (needs sprint/judge.py run first)
}