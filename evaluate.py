"""
Scores solution.py's Match/Mismatch predictions against a hand-labeled
ground truth, reporting a confusion matrix and precision/recall/F1/accuracy.

The ground truth (extra-questions/ground_truth.json) was hand-labeled by
reading each link's mercuryFraudTeamComments -- an offline evaluation
fixture only, never fed into the matching algorithm itself.

Positive class = Match (the algorithm approves the transfer). In this fraud
context a false positive (approving a link that's actually a mismatch) is
materially worse than a false negative (flagging a legitimate customer for
review) -- one risks real fraud loss, the other just adds friction. Raw
accuracy hides that asymmetry, so the confusion matrix is reported alongside
it rather than accuracy alone.
"""

import json

from solution import evaluate_link, load_data

with open("extra-questions/ground_truth.json") as f:
    GROUND_TRUTH = json.load(f)


def main():
    links, customers_by_id, nickname_groups = load_data()

    tp = fp = tn = fn = 0
    rows = []
    for link in links:
        link_id = link["linkId"]
        customer = customers_by_id[link["mercuryCompanyId"]]
        result = evaluate_link(link, customer, nickname_groups)
        expected = GROUND_TRUTH[str(link_id)]
        correct = result.verdict == expected

        if result.verdict == "Match" and expected == "Match":
            tp += 1
        elif result.verdict == "Match" and expected == "Mismatch":
            fp += 1
        elif result.verdict == "Mismatch" and expected == "Mismatch":
            tn += 1
        else:
            fn += 1

        rows.append((link_id, result, expected, correct))

    print(f"{'Link':<6}{'Predicted':<12}{'Expected':<12}{'Correct':<10}{'Name':<6}{'Email':<7}{'Phone':<7}Total")
    for link_id, result, expected, correct in rows:
        print(
            f"{link_id:<6}{result.verdict:<12}{expected:<12}{str(correct):<10}"
            f"{result.name_score:<6}{result.email_score:<7}{result.phone_score:<7}{result.total}"
        )

    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else float("nan")
    accuracy = (tp + tn) / len(rows)

    print()
    print(f"Confusion matrix: TP={tp}  FP={fp}  TN={tn}  FN={fn}")
    print(f"Precision: {precision:.2f}  Recall: {recall:.2f}  F1: {f1:.2f}  Accuracy: {accuracy:.2f}")


if __name__ == "__main__":
    main()
