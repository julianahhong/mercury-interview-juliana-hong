"""
Simulates micro-deposit verification: two small deposits are sent to the
linked account, and only someone with real access to that account's
statement can report the exact amounts back -- proving account access
independently of the Plaid credentials already checked. Used by triage.py
for links that land in the "Medium" confidence tier.
"""

import random
from dataclasses import dataclass

MAX_ATTEMPTS = 3


@dataclass
class MicroDepositChallenge:
    link_id: int
    amounts_cents: tuple
    attempts_remaining: int = MAX_ATTEMPTS
    verified: bool = False


def initiate(link_id):
    amounts = tuple(random.sample(range(1, 100), 2))
    return MicroDepositChallenge(link_id=link_id, amounts_cents=amounts)


def verify(challenge, submitted_cents):
    if challenge.verified or challenge.attempts_remaining <= 0:
        return challenge.verified
    challenge.attempts_remaining -= 1
    if sorted(submitted_cents) == sorted(challenge.amounts_cents):
        challenge.verified = True
    return challenge.verified


if __name__ == "__main__":
    challenge = initiate(link_id=99)
    a, b = challenge.amounts_cents
    print(f"Sent deposits of ${a / 100:.2f} and ${b / 100:.2f} to link 99 (only visible on the customer's statement).")

    print("Customer guesses (12, 34):", verify(challenge, (12, 34)))
    print("Customer guesses the actual amounts:", verify(challenge, challenge.amounts_cents))
    print(f"Verified: {challenge.verified}, attempts remaining: {challenge.attempts_remaining}")
