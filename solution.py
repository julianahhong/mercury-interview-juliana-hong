"""
Flags Plaid-linked third-party bank accounts whose reported owner doesn't
plausibly match the Mercury customer that linked them. See NOTES.md for the
scoring rationale and edge cases considered.
"""

import json
import re
from dataclasses import dataclass

from rapidfuzz.distance import JaroWinkler

FULL_NAME_MATCH = 3
BUSINESS_NAME_MATCH = 3
PARTIAL_NAME_MATCH = 1
EMAIL_MATCH = 2
PHONE_MATCH = 2
MATCH_THRESHOLD = 3

# A second cut above MATCH_THRESHOLD for triage.py's confidence tiers: total
# score of 0 means no evidence at all (block/escalate), >=5 means a full
# name match plus a contact detail or better (auto-clear), and anything in
# between has some but not enough evidence to trust alone (verify).
HIGH_CONFIDENCE_THRESHOLD = 5

# Jaro-Winkler is the record-linkage standard for name matching (it weights
# matching prefixes, which suits typical name typos better than generic edit
# distance). 0.85 catches real typos (e.g. "Smith"/"Smyth" = 0.89) while
# still rejecting different-but-similar-looking surnames (e.g.
# "Windal"/"Windhorst" = 0.82). Below MIN_FUZZY_LENGTH we skip it entirely --
# short tokens like "cy" are already handled by nickname lookup, and
# fuzzy-matching them risks spurious hits against unrelated short strings.
FUZZY_SIMILARITY_THRESHOLD = 0.85
MIN_FUZZY_LENGTH = 4

HONORIFICS = {"mr", "mrs", "ms", "mx", "dr", "jr", "sr", "ii", "iii", "iv"}
BUSINESS_SUFFIXES = {
    "inc", "incorporated", "llc", "corp", "corporation", "co", "company",
    "ltd", "limited", "technologies", "tech", "group", "holdings",
    "enterprises", "industries", "international", "intl",
}


def load_nickname_groups(path):
    """Maps a name to the set of equivalence-group line numbers it appears in (a name can be on more than one line)."""
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


def fuzzy_match(a, b):
    if len(a) < MIN_FUZZY_LENGTH or len(b) < MIN_FUZZY_LENGTH:
        return False
    return JaroWinkler.normalized_similarity(a, b) >= FUZZY_SIMILARITY_THRESHOLD


def tokens_match(a, b, nickname_groups):
    if a is None or b is None:
        return False
    if a == b:
        return True
    if nickname_groups.get(a, set()) & nickname_groups.get(b, set()):
        return True
    return fuzzy_match(a, b)


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
    if entry_key == business_key or fuzzy_match(entry_key, business_key):
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


def tier(total):
    if total >= HIGH_CONFIDENCE_THRESHOLD:
        return "High"
    if total > 0:
        return "Medium"
    return "Low"


@dataclass
class MatchResult:
    name_score: int
    email_score: int
    phone_score: int
    total: int
    verdict: str
    tier: str


def evaluate_link(link, customer, nickname_groups):
    name_score = score_names(link["names"], customer, nickname_groups)
    email_score = score_emails(link["emails"], customer)
    phone_score = score_phones(link["phoneNumbers"], customer)
    total = name_score + email_score + phone_score
    verdict = "Match" if total >= MATCH_THRESHOLD else "Mismatch"
    return MatchResult(name_score, email_score, phone_score, total, verdict, tier(total))


def load_data():
    with open("mercury-customers.json") as f:
        customers = json.load(f)
    with open("third-party-banks.json") as f:
        links = json.load(f)
    nickname_groups = load_nickname_groups("extra-questions/nicknames.txt")
    customers_by_id = {c["mercuryCompanyId"]: c for c in customers}
    return links, customers_by_id, nickname_groups


def main():
    links, customers_by_id, nickname_groups = load_data()

    results = []
    for link in links:
        customer = customers_by_id[link["mercuryCompanyId"]]
        result = evaluate_link(link, customer, nickname_groups)
        results.append((link["linkId"], result.verdict))

    total_matches = sum(1 for _, v in results if v == "Match")
    total_mismatches = len(results) - total_matches

    print(f"Total matches: {total_matches}")
    print(f"Total mismatches: {total_mismatches}")
    print()
    for link_id, verdict in results:
        print(f"Link {link_id}: {verdict}")


if __name__ == "__main__":
    main()
