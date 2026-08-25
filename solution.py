"""
Match Plaid-reported third-party bank account owners against Mercury customer
data, to flag links whose reported identity doesn't plausibly correspond to
the Mercury customer that created them.

Approach: score each link on three kinds of evidence (name, email, phone) and
sum a weighted score. A full name match (personal or business) is treated as
strong evidence on its own; email/phone matches are supporting evidence; a
bare first-name-or-last-name fragment is weak evidence. This weighting was
reverse-engineered from the fraud team's comments in the sample data -- e.g.
a phone-only match wasn't enough for them to be confident (Link 2), while a
nickname-resolved full name match with no contact-detail overlap at all was
(Link 6). See NOTES.md for the full reasoning and edge cases considered.
"""

import json
import re
from difflib import SequenceMatcher

FULL_NAME_MATCH = 3
BUSINESS_NAME_MATCH = 3
PARTIAL_NAME_MATCH = 1
EMAIL_MATCH = 2
PHONE_MATCH = 2
MATCH_THRESHOLD = 3

FUZZY_RATIO_THRESHOLD = 0.85

HONORIFICS = {"mr", "mrs", "ms", "mx", "dr", "jr", "sr", "ii", "iii", "iv"}
BUSINESS_SUFFIXES = {
    "inc", "incorporated", "llc", "corp", "corporation", "co", "company",
    "ltd", "limited", "technologies", "tech", "group", "holdings",
    "enterprises", "industries", "international", "intl",
}


def load_nickname_groups(path):
    """Maps a name to the set of equivalence-group line numbers it appears in.

    A name can appear in more than one line (e.g. "cy" is a nickname for both
    "cyrus"/"cyril" and, separately, "cyrenius"), so equivalence is "do their
    group sets overlap" rather than "do they map to the same single group".
    """
    name_to_groups = {}
    with open(path) as f:
        for line_no, line in enumerate(f):
            names = [n.strip().lower() for n in line.strip().split(",") if n.strip()]
            for name in names:
                name_to_groups.setdefault(name, set()).add(line_no)
    return name_to_groups


def normalize_phone(phone):
    digits = re.sub(r"\D", "", phone)
    return digits[-10:] if len(digits) >= 10 else digits


def normalize_email(email):
    return email.strip().lower()


def tokenize(name):
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", name.lower())
    tokens = cleaned.split()
    return [t for t in tokens if t not in HONORIFICS and len(t) > 1]


def personal_name_parts(name):
    """Best-guess (first, last) from a raw name string, dropping middle names/initials."""
    tokens = tokenize(name)
    if not tokens:
        return None, None
    if len(tokens) == 1:
        return tokens[0], None
    return tokens[0], tokens[-1]


def business_name_key(name):
    tokens = tokenize(name)
    tokens = [t for t in tokens if t not in BUSINESS_SUFFIXES]
    return " ".join(tokens)


def tokens_match(a, b, nickname_groups):
    if a is None or b is None:
        return False
    if a == b:
        return True
    if nickname_groups.get(a, set()) & nickname_groups.get(b, set()):
        return True
    return SequenceMatcher(None, a, b).ratio() >= FUZZY_RATIO_THRESHOLD


def score_personal_name(entry_name, first_name, last_name, nickname_groups):
    e_first, e_last = personal_name_parts(entry_name)
    if e_first is None:
        return 0

    first_ok = tokens_match(e_first, first_name.lower(), nickname_groups)
    last_ok = e_last is not None and tokens_match(e_last, last_name.lower(), nickname_groups)

    if e_last is not None and first_ok and last_ok:
        return FULL_NAME_MATCH
    if first_ok or last_ok:
        return PARTIAL_NAME_MATCH
    return 0


def score_business_name(entry_name, business_name):
    entry_key = business_name_key(entry_name)
    business_key = business_name_key(business_name)
    if not entry_key or not business_key:
        return 0
    if entry_key == business_key or SequenceMatcher(None, entry_key, business_key).ratio() >= FUZZY_RATIO_THRESHOLD:
        return BUSINESS_NAME_MATCH
    return 0


def score_names(names, customer, nickname_groups):
    best = 0
    business_names = [customer["tradeName"], customer["legalName"]]
    for entry_name in names:
        for user in customer["users"]:
            best = max(best, score_personal_name(entry_name, user["firstName"], user["lastName"], nickname_groups))
        for business_name in business_names:
            best = max(best, score_business_name(entry_name, business_name))
    return best


def score_emails(emails, customer):
    known_emails = {normalize_email(u["email"]) for u in customer["users"]}
    known_emails.add(normalize_email(customer["contactEmail"]))
    for email in emails:
        if normalize_email(email) in known_emails:
            return EMAIL_MATCH
    return 0


def score_phones(phones, customer):
    known_phone = normalize_phone(customer["contactPhoneNumber"])
    for phone in phones:
        if normalize_phone(phone) == known_phone:
            return PHONE_MATCH
    return 0


def evaluate_link(link, customer, nickname_groups):
    name_score = score_names(link["names"], customer, nickname_groups)
    email_score = score_emails(link["emails"], customer)
    phone_score = score_phones(link["phoneNumbers"], customer)
    total = name_score + email_score + phone_score
    return "Match" if total >= MATCH_THRESHOLD else "Mismatch"


def main():
    with open("mercury-customers.json") as f:
        customers = json.load(f)
    with open("third-party-banks.json") as f:
        links = json.load(f)
    nickname_groups = load_nickname_groups("extra-questions/nicknames.txt")

    customers_by_id = {c["mercuryCompanyId"]: c for c in customers}

    results = []
    for link in links:
        customer = customers_by_id[link["mercuryCompanyId"]]
        verdict = evaluate_link(link, customer, nickname_groups)
        results.append((link["linkId"], verdict))

    total_matches = sum(1 for _, v in results if v == "Match")
    total_mismatches = len(results) - total_matches

    print(f"Total matches: {total_matches}")
    print(f"Total mismatches: {total_mismatches}")
    print()
    for link_id, verdict in results:
        print(f"Link {link_id}: {verdict}")


if __name__ == "__main__":
    main()
