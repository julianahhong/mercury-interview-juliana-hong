"""
A tiered alternative to solution.py's binary Match/Mismatch: classifies each
link's score into High/Medium/Low confidence and recommends an action per
tier, routing Medium-confidence links to micro-deposit verification instead
of a blind approve or block. See NOTES.md for the tier boundaries' rationale.
"""

from micro_deposit import initiate
from solution import evaluate_link, load_data

ACTIONS = {
    "High": "Auto-clear",
    "Medium": "Verify via micro-deposits",
    "Low": "Block / escalate to fraud team",
}


def main():
    links, customers_by_id, nickname_groups = load_data()

    print(f"{'Link':<6}{'Total':<7}{'Tier':<8}Action")
    for link in links:
        customer = customers_by_id[link["mercuryCompanyId"]]
        result = evaluate_link(link, customer, nickname_groups)
        link_id = link["linkId"]
        print(f"{link_id:<6}{result.total:<7}{result.tier:<8}{ACTIONS[result.tier]}")

        if result.tier == "Medium":
            challenge = initiate(link_id)
            a, b = challenge.amounts_cents
            print(f"       -> sent micro-deposits of ${a / 100:.2f} and ${b / 100:.2f}; awaiting customer confirmation")


if __name__ == "__main__":
    main()
