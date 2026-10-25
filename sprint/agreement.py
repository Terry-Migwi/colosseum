"""How much do two labellers agree? Raw agreement and Cohen's kappa.

Usage (from the colosseum repo root):
    python sprint/agreement.py sprint/compliance_terry.json sprint/compliance_partner.json

Why kappa and not just "% agreed"? Two people labelling at random would still
agree some of the time by luck. Kappa subtracts that luck:
    kappa = (observed agreement - agreement expected by chance) / (1 - chance)
1 = perfect, 0 = no better than chance. Rough guide: above 0.6 is good,
0.4 to 0.6 moderate, below 0.4 means the rule is too vague and needs rewriting.
"""

import json
import sys
from collections import Counter


def main() -> None:
    a = {str(k): str(v).strip().lower() for k, v in json.load(open(sys.argv[1])).items()}
    b = {str(k): str(v).strip().lower() for k, v in json.load(open(sys.argv[2])).items()}
    keys = sorted(set(a) & set(b), key=lambda k: (len(k), k))
    if not keys:
        sys.exit("No episodes labelled by both people.")

    n = len(keys)
    observed = sum(a[k] == b[k] for k in keys) / n
    count_a, count_b = Counter(a[k] for k in keys), Counter(b[k] for k in keys)
    chance = sum(count_a[c] * count_b[c] for c in set(count_a) | set(count_b)) / (n * n)
    kappa = (observed - chance) / (1 - chance) if chance < 1 else 1.0

    print(f"episodes labelled by both: {n}")
    print(f"raw agreement:  {observed:.0%}")
    print(f"Cohen's kappa:  {kappa:.2f}")
    print("\ndisagreements to discuss:")
    for k in keys:
        if a[k] != b[k]:
            print(f"  seed/episode {k}: {a[k]} vs {b[k]}")


if __name__ == "__main__":
    main()