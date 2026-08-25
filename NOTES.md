# Notes on the ACH fraud-match solution

## How it works

- **Inputs**: `mercury-customers.json`, `third-party-banks.json`, and
  `extra-questions/nicknames.txt`.
- **Normalization**: names are lowercased with punctuation and
  honorifics/middle-initials stripped; business names additionally have
  common entity suffixes (`inc`, `llc`, `technologies`, ...) stripped;
  phone numbers are reduced to their last 10 digits; emails are
  lowercased/trimmed.
- **Nicknames**: `nicknames.txt` is parsed into a map of name → set of
  line numbers it appears on. Two names are nickname-equivalent if their
  sets overlap (a name can legitimately appear on more than one line,
  e.g. "cy" nicknames both "cyril" and, separately, "cyrenius").
- **Fuzzy fallback**: if a name isn't an exact or nickname match, Jaro-Winkler
  similarity (via `rapidfuzz`) ≥ 0.85 catches minor typos, skipped for tokens
  under 4 characters (see "Fuzzy matching: Jaro-Winkler" below).
- **Scoring**: each link earns points from three independent checks —
  a full personal or business name match scores 3, an email match scores
  2, a phone match scores 2, and a bare first-/last-name fragment scores
  1. The three category scores are summed.
- **Decision**: `Match` if the total is ≥ 3, else `Mismatch`.

## AI usage disclosure

I used Claude Code throughout: to reverse-engineer the fraud team's implicit
decision logic from their comments on the 9 sample links, to design the
weighted-scoring approach in `solution.py`, and to write the implementation
and this write-up. I reviewed the logic against every sample link by hand
(see the reasoning below and in `solution.py`'s docstring) and can walk
through any part of it.

## Why a weighted score instead of "N of 3 fields match"

Reading the `mercuryFraudTeamComments` against the underlying data, a simple
"how many of {name, email, phone} overlap" rule doesn't reproduce the fraud
team's actual judgment:

- **Link 2**: only the phone number matches (no name or email overlap at
  all). The fraud team isn't confident — they call the customer to check.
- **Link 6**: no phone or email overlap at all; the only signal is a name
  match, and only via nickname resolution ("Cy" → "Cyril") plus a matching
  last name. The fraud team calls this "probably good".
- **Link 8**: a first-name-only match ("Cyril", no last name given) plus a
  phone match — two individually weak signals — is again "probably good".

So a single contact-detail match (phone or email alone) isn't trusted, but a
full name match (personal or business) is trusted on its own, and two weaker
signals together are enough. `solution.py` encodes this as a point score:
full name match = 3, business name match = 3, first/last-name-only fragment
= 1, email match = 2, phone match = 2, with a threshold of 3 to call it a
Match. This reproduces the fraud team's call on all 9 sample links.

## Edge cases handled

- Honorifics/suffixes in names ("Mr.", "Jr.", etc.)
- Middle initials vs. full middle names (both dropped when guessing
  first/last name, since Plaid's `names` field isn't structured)
- Punctuation differences ("Rams Kitchen" vs. "Ram's Kitchen")
- Business entity suffixes ("InfoLinks" vs. "InfoLinks Technologies, Inc.")
- Phone formatting variance — parens, dashes, spaces, all normalized to
  digits-only
- Nicknames, via `nicknames.txt` — including names that appear in more than
  one nickname-equivalence group (e.g. "cy" is a nickname under three
  different lines in the file; a naive "map name -> one group id" approach
  breaks this, so equivalence is computed as group-set overlap instead)
- Minor spelling variation, via Jaro-Winkler fuzzy matching, on top of
  exact/nickname matching
- The `names` array mixing personal names and business names in the same
  list — every name entry is checked against both

## Edge cases not in this dataset, but worth handling in a real system

- International phone numbers / country codes (current normalization
  assumes a 10-digit US number)
- Multi-part or hyphenated last names, and cultures where a single name
  isn't split into first/last at all
- Unicode, accented, or transliterated names (e.g. "José" vs. "Jose")
- Generic/very common business names (e.g. two unrelated "Consulting LLC"
  companies) causing a false-positive business-name match
- A link reused after employee turnover — the account is legitimately owned
  by a different person than when it was first linked
- A company's legal name changing after incorporation/rebrand, so historical
  Mercury data no longer matches current bank records
- Email aliasing (`name+tag@domain.com`) that a strict equality check would
  treat as a non-match
- Joint personal accounts, or business accounts with several authorized
  signers, where only one of several legitimate names appears in Plaid data
- Adversarial input: an attacker who already knows the victim's name/email
  and only needs to fabricate a phone number, or vice versa — the scoring
  weights should be revisited periodically against what's actually cheap for
  an attacker to spoof

## Fuzzy matching: Jaro-Winkler over generic edit distance

The initial version used `difflib.SequenceMatcher` (Ratcliff/Obershelp) as a
catch-all fuzzy fallback. Swapped it for **Jaro-Winkler** (via `rapidfuzz`),
the standard similarity metric in record-linkage literature for personal
names specifically, because it weights agreement in the common prefix —
which is where most real name typos preserve similarity (e.g. "Smith" vs.
"Smyth") — more heavily than a generic edit-distance-style metric would.

Two calibration points worth noting:
- The threshold (0.85) was picked empirically, not just carried over from the
  old metric: "Smith"/"Smyth" scores 0.89 (should match) while two
  different-but-similar surnames like "Windal"/"Windhorst" score 0.82
  (should not) — 0.85 separates these correctly.
- Short tokens (under 4 characters) skip fuzzy matching entirely. Below that
  length, similarity scores stop being meaningful discriminators (e.g. "cy"
  vs. "by" looks deceptively close) — legitimate short-name cases are already
  covered by exact or nickname matching, so this only removes noise.

## Evaluation: `evaluate.py`

`solution.py`'s required output is just a Match/Mismatch verdict per link,
which doesn't say anything about how good the algorithm actually is.
`evaluate.py` adds a separate evaluation harness, reusing `solution.py`'s
loading/scoring functions rather than duplicating logic:

- Compares each link's predicted verdict against a **hand-labeled ground
  truth** (`extra-questions/ground_truth.json`), which was created by reading
  `mercuryFraudTeamComments` — the same way the scoring weights themselves
  were derived. This is strictly an offline evaluation fixture: it is never
  read by the matching algorithm, consistent with the prompt's note that
  those comments "are not meant to be considered by your code."
- Reports a confusion matrix (TP/FP/TN/FN) and precision/recall/F1/accuracy,
  with **Match as the positive class** (the algorithm approving a transfer).
- On this 9-link sample, the algorithm scores perfectly (by construction,
  since the weights were tuned against these same comments) — the harness's
  value is in being ready to run against a larger, independently-labeled
  dataset, not in this number.

**Why the confusion matrix matters more than accuracy here**: a false
positive (approving a link that's actually a mismatch) risks real fraud
loss, while a false negative (flagging a legitimate customer for review)
only costs friction. Those aren't symmetric costs, so a real deployment
should optimize for high recall on the Mismatch/review class even at the
expense of precision — i.e., tune the threshold to over-flag rather than
under-flag — and accuracy alone would hide that tradeoff.

## Toward a better-than-binary system

The score computed in `solution.py` is already a natural confidence signal,
not just an intermediate value for a threshold. Rather than collapsing it to
Match/Mismatch, a real system could expose three tiers:

- **High confidence** (well above threshold, e.g. full name + a contact
  detail): auto-clear.
- **Medium confidence** (right at/near threshold, e.g. Link 2's phone-only
  match): route to the fraud team's review queue instead of silently
  approving or blocking.
- **Low confidence** (well below threshold, e.g. no overlap at all): block
  or require additional verification.

This also opens the door to weighting the score by transfer risk (e.g. dollar
amount, first-time vs. repeat transfer) rather than using one fixed
threshold for every case.

## Other ways to curtail this type of fraud

- Micro-deposit verification as a secondary check alongside Plaid, especially
  for medium-confidence links
- Periodic re-authentication through Plaid rather than trusting a link
  indefinitely after the first check
- Device/IP/behavioral fingerprinting at link-creation time, correlated
  against the customer's usual patterns
- Velocity and anomaly checks on transfer size/frequency relative to the
  account's history, independent of identity matching
- Out-of-band confirmation (push notification, call, or SMS) for first-time
  or unusually large transfers from a newly linked account
