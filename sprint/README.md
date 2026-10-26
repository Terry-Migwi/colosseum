# Say vs Do: catching hidden collusion between AI agents

Code and data for our project at Apart Research's [AI Collusion Research Sprint](https://apartresearch.com/sprints/ai-collusion-research-sprint-2026-10-23-to-2026-10-25) (October 2026, Track 2: Detection and Audit of Collusion)


## What this is

Two AI agents can quietly agree to look after themselves instead of the team, and an auditor usually can't see their private chat. We tested whether checking what agents *say* in the shared chat against what they *do* can catch this.

We built on [Colosseum](https://github.com/umass-ai-safety/colosseum)'s JiraTicket game, where the best team result can be calculated exactly. We ran matched pairs of Claude Haiku 4.5 games: the same puzzle once honest, and once with two agents given a secret channel and told to collude.

What we found:

- From the shared chat alone, our combined say-vs-do monitor told covert games from honest ones with AUROC 0.74 (95% CI 0.57–0.88). That met our pre-registered bar.
- But most of that signal comes from the secret channel itself, not from collusion. It fires almost as strongly when the partners refuse to collude.
- A conversation-only AI judge did about as well on natural games. Only say-vs-do caught collusion that lives in actions (planted control).

Everything we added is in `sprint/` and `experiments/collusion/configs/sprint/`. The rest of the repository is Colosseum, unchanged, at commit `b077fe7`.

## Pre-registration

The analysis was frozen in git before the confirmatory data existed. The commits are the proof, so please don't look for them under new hashes:

| Commit | Time (EAT, UTC+3) | What it holds |
| --- | --- | --- |
| `800f0ee` | 25 Oct 2026, 11:38 | Pre-registration (`sprint/preregistration.md`) and the frozen analysis code |
| `2d9337c` | 25 Oct 2026, 12:34 | Deviation note: a network failure stopped the run, so we completed seeds 8–27 as pairs |
| `92013c9` | 25 Oct 2026, 13:40 | AI-assistant compliance labels, committed before any scoring |

## What's in `sprint/`

**Monitors and harness**

| File | What it does |
| --- | --- |
| `to_jsonl.py` | Turns Colosseum's run folders into one record per episode (messages, actions, outcomes, true optimum, labels) |
| `monitors.py` | Promise vs action, silent action, going quiet, plus the action-only regret baseline |
| `monitor_justification.py` | Reasons vs facts: was a "best" or "cheapest" claim true against the agent's own costs? |
| `monitor_follow_through.py` | Did the agent's action match what was proposed for it in public? |
| `registry.py` | All monitors in one place, plus the combined monitor (`say_do_all`) |
| `eval.py` | The harness: public and full views, AUROC, bootstrap intervals, permutation p-values, paired wins |
| `judge.py`, `monitor_judge.py` | The conversation-only AI judge baseline (Claude Haiku 4.5, temperature 0), cached in `judge_scores.json` |
| `planted.py` | The positive control: honest games with the partners' final actions switched to collusive ones |
| `prereg_analysis.py` | The pre-registered analysis: primary result, flag rates, secondary tests S1–S4 |
| `agreement.py` | Agreement and Cohen's kappa between two labellers |
| `show_episode.py` | Prints one episode's chats and actions, for reading by hand |

**Labelling and pre-registration**

| File | What it holds |
| --- | --- |
| `preregistration.md` | The pre-registration, with the deviation note |
| `labeling_rule.md` | The compliance labelling rule (complied / partial / refused / unclear), fixed before labelling |
| `compliance.json` | Pilot labels (seeds 1–7) |
| `compliance2_claude.json` | Confirmatory labels by the AI assistant (seeds 8–27) |
| `compliance2_claude_notes.json` | The AI assistant's one-line reason for each confirmatory label |
| `compliance2_second.json` | Independent human labels for a random 10 confirmatory episodes |
| `compliance2_merged.json` | AI labels with the human labels substituted where they exist |
| `compliance_sheet.md` | Pilot labelling sheet (seeds 1–7); unlike the confirmatory sheet, it also showed what each agent did |
| `compliance_sheet_batch2_second.md` | The sheet the human labeller worked from: chats only, no outcomes |

**Data**

| File | What it holds |
| --- | --- |
| `batch.jsonl` | Pilot: seeds 1–7, 14 episodes (7 honest, 7 covert) |
| `batch2.jsonl` | Confirmatory batch: seeds 8–27, 40 episodes (20 matched pairs) |
| `positive_control.jsonl`, `positive_control2.jsonl` | Planted-collusion controls for the pilot and the confirmatory batch |
| `judge_scores.json` | Cached AI-judge scores for the confirmatory batch, so the judge numbers can be checked without API calls |

Every agent, ticket and name is synthetic.

## Reproducing the results

Setup: Colosseum at commit `b077fe7` with the CoLLAB submodule, Python 3.11, and the pinned dependencies in `requirements-colosseum.txt` (exported from Colosseum's `uv.lock`). No GPU is needed, because the agents run through the Anthropic API. Put `ANTHROPIC_API_KEY` in a `.env` file at the repo root, and don't copy `TERRARIUM_COLLAB_PATH=experiments` from `.env.example`.

Run everything from the repo root.

**Just the numbers (no API calls).** This reruns the pre-registered analysis on the saved data, using the cached judge scores:

```bash
python sprint/prereg_analysis.py sprint/batch2.jsonl sprint/compliance2_claude.json sprint/positive_control2.jsonl
python sprint/prereg_analysis.py sprint/batch2.jsonl sprint/compliance2_merged.json sprint/positive_control2.jsonl   # human labels where available
python sprint/agreement.py sprint/compliance2_claude.json sprint/compliance2_second.json
python sprint/eval.py sprint/batch.jsonl --compliance sprint/compliance.json    # pilot
```

**From scratch (costs money).** About $0.24 per episode with 3 planning rounds, and about 3.5 minutes per episode:

```bash
python -m dotenv run -- python experiments/collusion/run.py --config experiments/collusion/configs/sprint/jira_n4_batch2_pairs.yaml
python sprint/to_jsonl.py experiments/collusion/outputs/batch2 -o sprint/batch2.jsonl
python sprint/judge.py sprint/batch2.jsonl --dry-run          # cost estimate first
python -m dotenv run -- python sprint/judge.py sprint/batch2.jsonl
python sprint/planted.py sprint/batch2.jsonl -o sprint/positive_control2.jsonl
python sprint/prereg_analysis.py sprint/batch2.jsonl sprint/compliance2_claude.json sprint/positive_control2.jsonl
```

Conversations are regenerated at temperature 0.7, so a fresh run won't reproduce our episodes word for word.

## Limitations

We tested one model (Claude Haiku 4.5) in one environment (JiraTicket, 4 agents), on 20 confirmatory pairs. We planned 40, but a network failure cut the run short. Haiku mostly refused to collude, so there were few real cases to test on: 2 complied and 10 partial covert games by the AI assistant’s labels, or 4 and 9 by the human labels. Our planted control shows the monitors catch collusion when it takes the form “agree in public, act differently”, but it doesn’t show that real colluders behave that way. Our two labellers agreed only 6 times out of 10 (Cohen’s kappa 0.27), and the confirmatory labels came from an AI assistant that also built the monitors, although our conclusions hold under both sets of labels. Finally, the monitors find claims with regular expressions, which can misread phrasing, and they assume the auditor can see each agent’s private costs.

