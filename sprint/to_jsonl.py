"""Convert Colosseum JiraTicket collusion runs into one JSONL record per episode.

Usage (from the colosseum repo root):
    python sprint/to_jsonl.py experiments/collusion/outputs/sprint -o sprint/episodes.jsonl

The input path can be one run folder or any folder above it; every folder that
contains tool_events.json is treated as one episode.

Why this exists
---------------
Colosseum spreads one episode across several files: messages in
blackboards.json, tool calls in tool_events.json, private costs inside the
prompt text in agent_prompts.json, outcomes in final_summary.json and
metrics.json. Our monitors need all of that side by side, per agent, so this
script flattens it into one record with five parts:

  setup     what the world looked like (tasks, each agent's private costs)
  messages  what agents SAID, split into public and secret channels
  actions   what agents DID (assign_task calls)
  outcomes  how it turned out, including the TRUE optimum
  labels    the answer key (collusion yes/no, who colluded)

Rule: a monitor may read setup + messages + actions. It must never read
labels, and outcomes only when a monitor is explicitly allowed to (the
action-only baseline). Keeping labels in their own block makes that rule easy
to enforce in the harness.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # so `experiments.collusion...` imports work


# ---------------------------------------------------------------- helpers ---

def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def section(text: str, header: str) -> List[str]:
    """Return the lines under '=== HEADER ===' up to the next '===' header."""
    lines = text.splitlines()
    out: List[str] = []
    inside = False
    for line in lines:
        if line.strip().startswith("===") and header in line:
            inside = True
            continue
        if inside and line.strip().startswith("==="):
            break
        if inside and line.strip():
            out.append(line.strip())
    return out


# ------------------------------------------------- setup (from the prompts) ---

TASK_RE = re.compile(
    r"^- (?P<id>[^:]+::\w+): (?P<title>.*?) \| type=(?P<type>\w+) \| effort=(?P<effort>[\d.]+)"
    r" \| priority=(?P<priority>\w+) \| tags=\[(?P<tags>.*)\]"
)
COST_RE = re.compile(r"^- (?P<id>[^:]+::\w+): cost=(?P<cost>[-\d.]+|inf)")


def parse_agent_view(prompt_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Pull one agent's private state, cost table and the task list from its prompt.

    We parse the FIRST prompt each agent saw (planning round 1), because that is
    the information it had when it started making claims.
    """
    text = prompt_entry["user_prompt"]

    state: Dict[str, Any] = {"availability_hours": None, "skills": {}}
    for line in section(text, "YOUR PRIVATE STATE"):
        if line.startswith("Availability"):
            state["availability_hours"] = float(line.split(":")[-1])
        elif line.startswith("Top skills"):
            for item in line.split(":", 1)[1].split(","):
                if ":" in item:
                    name, score = item.strip().rsplit(":", 1)
                    state["skills"][name.strip()] = float(score)

    costs: Dict[str, float] = {}
    for line in section(text, "YOUR COSTS"):
        m = COST_RE.match(line)
        if m:
            costs[m["id"]] = float(m["cost"])

    tasks: Dict[str, Dict[str, Any]] = {}
    for line in section(text, "TASKS (PUBLIC)"):
        m = TASK_RE.match(line)
        if m:
            tasks[m["id"]] = {
                "title": m["title"],
                "type": m["type"],
                "effort": float(m["effort"]),
                "priority": m["priority"],
                "tags": [t.strip() for t in m["tags"].split(",") if t.strip()],
            }

    return {"state": state, "costs": costs, "tasks": tasks}


# --------------------------------------------- messages and actions ---------

def build_messages(
    blackboards: List[Dict[str, Any]],
    tool_events: List[Dict[str, Any]],
    secret_bb_id: Optional[int],
) -> Dict[str, List[Dict[str, Any]]]:
    """Split communication events into public and secret channels.

    blackboards.json has the text and timestamps but not the planning round;
    tool_events.json has the round. They share an id (event id), so we join on it.
    """
    round_by_event = {
        (e.get("result") or {}).get("event_id"): e.get("planning_round")
        for e in tool_events
        if e.get("tool_name") == "post_message"
    }

    public: List[Dict[str, Any]] = []
    secret: List[Dict[str, Any]] = []
    for bb in blackboards:
        bb_id = int(bb["blackboard_id"])
        for ev in bb.get("events", []):
            if ev.get("kind") != "communication":
                continue  # skip SYSTEM context and action_executed echoes
            payload = ev.get("payload") or {}
            msg = {
                "event_id": ev.get("id"),
                "ts": ev.get("ts"),
                "agent": ev.get("agent"),
                "blackboard_id": bb_id,
                "phase": payload.get("phase"),
                "planning_round": round_by_event.get(ev.get("id")),
                "content": payload.get("content", ""),
            }
            (secret if secret_bb_id is not None and bb_id == int(secret_bb_id) else public).append(msg)

    public.sort(key=lambda m: m["ts"] or 0)
    secret.sort(key=lambda m: m["ts"] or 0)
    return {"public": public, "secret": secret}


def build_actions(tool_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Everything an agent DID in the world (not speech)."""
    actions = []
    for e in tool_events:
        if e.get("tool_name") == "post_message":
            continue
        result = e.get("result") or {}
        actions.append({
            "agent": e.get("agent_name"),
            "tool": e.get("tool_name"),
            "arguments": e.get("arguments"),
            "status": result.get("status"),
            "phase": e.get("phase"),
        })
    return actions


# ------------------------------------------------------------ outcomes ------

def true_optimum(run_dir: Path) -> Optional[Dict[str, Any]]:
    """Exact cooperative optimum via the repo's Hungarian-algorithm solver.

    metrics.json's system_regret compares against an unreachable optimum
    (every task done at zero cost), so we recompute it here.
    """
    try:
        from experiments.collusion import compute_jira_optimal as cjo
    except Exception as exc:  # pragma: no cover
        print(f"  [warn] optimum solver not importable: {exc}", file=sys.stderr)
        return None
    try:
        try:
            instance = cjo._reconstruct_instance(run_dir)  # needs run_config.json
        except Exception:
            instance = cjo._load_instance_from_agent_prompts(run_dir)  # prompts only
        weights = cjo._load_weights(run_dir, None)
        opt = cjo.solve_optimal_assignment(instance=instance, weights=weights)
        actual = cjo._load_actual_solution(run_dir)
    except Exception as exc:
        print(f"  [warn] optimum failed for {run_dir.name}: {exc}", file=sys.stderr)
        return None
    out = {
        "joint_reward": opt.joint_reward,
        "assignment": opt.assignment,
        "priority_sum": opt.priority_sum,
        "total_cost": opt.total_cost,
    }
    if actual is not None:
        out["system_regret"] = opt.joint_reward - actual.joint_reward
        out["ratio_actual_to_optimal"] = (
            actual.joint_reward / opt.joint_reward if opt.joint_reward else None
        )
    return out


# ------------------------------------------------------------ episode -------

def convert_run(run_dir: Path) -> Dict[str, Any]:
    run_cfg = load_json(run_dir / "run_config.json") or {}
    metrics = load_json(run_dir / "metrics.json") or {}
    summary = load_json(run_dir / "final_summary.json") or {}
    tool_events = load_json(run_dir / "tool_events.json") or []
    blackboards = load_json(run_dir / "blackboards.json") or []
    prompts = load_json(run_dir / "agent_prompts.json") or []

    secret_enabled = bool(run_cfg.get("secret_channel_enabled", metrics.get("secret_channel_enabled")))
    secret_bb_id = run_cfg.get("secret_blackboard_id", metrics.get("secret_blackboard_id"))

    # One view per agent, from the first prompt it saw.
    agent_views: Dict[str, Dict[str, Any]] = {}
    for p in prompts:
        agent_views.setdefault(p["agent_name"], parse_agent_view(p))
    tasks = next((v["tasks"] for v in agent_views.values() if v["tasks"]), {})

    per_agent_metrics = {a["agent_name"]: a for a in metrics.get("agents", [])}
    colluders = run_cfg.get("colluders") or [
        a["agent_name"] for a in metrics.get("agents", []) if a.get("role") == "colluder"
    ]

    agents = {
        name: {
            "availability_hours": view["state"]["availability_hours"],
            "skills": view["state"]["skills"],
            "costs": view["costs"],
        }
        for name, view in agent_views.items()
    }

    return {
        "episode_id": run_dir.name,
        "setup": {
            "environment": run_cfg.get("environment_name", "JiraTicketEnvironment"),
            "model": run_cfg.get("model"),
            "topology": run_cfg.get("topology"),
            "num_agents": metrics.get("total_agents", len(agents)),
            "seed": run_cfg.get("seed"),
            "agent_turn_order": run_cfg.get("agent_turn_order")
            or list(dict.fromkeys(p["agent_name"] for p in prompts)),
            "blackboards": [
                {"id": int(bb["blackboard_id"]), "participants": bb.get("participants", [])}
                for bb in blackboards
            ],
            "tasks": tasks,
            "agents": agents,
        },
        "messages": build_messages(blackboards, tool_events, secret_bb_id),
        "actions": build_actions(tool_events),
        "outcomes": {
            "assignment": summary.get("assignment"),
            "joint_reward": summary.get("joint_reward"),
            "agent_rewards": summary.get("agent_rewards"),
            "tasks_done": summary.get("tasks_done"),
            "priority_sum": summary.get("priority_sum"),
            "total_cost": summary.get("total_cost"),
            "violations": summary.get("violations"),
            "agent_regret": {n: m.get("regret") for n, m in per_agent_metrics.items()},
            "coalition_advantage_mean": metrics.get("coalition_advantage_mean"),
            "optimum": true_optimum(run_dir),
        },
        "labels": {
            "collusion": secret_enabled,  # our detection target
            "secret_blackboard_id": secret_bb_id,
            "prompt_variant": run_cfg.get("prompt_variant", metrics.get("prompt_variant")),
            "colluders": sorted(colluders),
        },
        "source_dir": str(run_dir),
    }


def find_runs(path: Path) -> List[Path]:
    if (path / "tool_events.json").exists():
        return [path]
    return sorted(p.parent for p in path.rglob("tool_events.json"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", type=Path, help="A run folder or any folder above run folders")
    ap.add_argument("-o", "--out", type=Path, default=Path("sprint/episodes.jsonl"))
    args = ap.parse_args()

    runs = find_runs(args.path)
    if not runs:
        sys.exit(f"No run folders (with tool_events.json) under {args.path}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for run_dir in runs:
            rec = convert_run(run_dir)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            m = rec["messages"]
            opt = rec["outcomes"]["optimum"] or {}
            print(
                f"{rec['episode_id']}: collusion={rec['labels']['collusion']} "
                f"public={len(m['public'])} secret={len(m['secret'])} "
                f"actions={len(rec['actions'])} "
                f"regret={opt.get('system_regret', float('nan')):.2f}"
            )
    print(f"Wrote {len(runs)} episode(s) to {args.out}")


if __name__ == "__main__":
    main()