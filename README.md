# BallotProof

Verification of DAO vote results on GenLayer, with a registry other contracts can read before they execute.

Someone registers the URL of a vote result page. GenLayer validators fetch the page and locate six facts, each as an exact quote: votes in favor, votes against, abstentions, the required quorum, the approval threshold rule, and whether voting is closed. The contract code checks every quote against the page text, parses the numbers, counts the votes and compares them with the threshold. The result is one of `PASSED`, `FAILED`, `INVALID` or `UNDETERMINED`. No model ever writes the result, and no model output is accepted without an exact quote from the fetched page. Anyone can challenge a result with a bond and corrected evidence. The final result is stored in an on-chain registry, so a payout or upgrade contract can run only after a valid vote.

## What the model does and what the code does

| Step | Done by |
|---|---|
| Check the URL is https, clean, and under an owner-approved prefix | code |
| Fetch the page | each validator |
| Locate six facts on the page and copy exact quotes | model |
| Drop every quote that is not an exact substring of the page, or whose wording does not match its field (a quote about votes against cannot fill the votes-in-favor field) | code |
| Parse vote counts, the quorum, the threshold type and the closed/open state from the quotes | code |
| Compare quorum and threshold and assign the result code | code |
| Agree on the facts that drive the rules and on the result code | validators (exact match) |
| Re-check that the leader's quotes occur on the validator's own copy of the page and that the leader's numbers and result follow from its quotes | each validator, in code |
| Challenge, bonds, payouts, windows, accounting | code |

## Result rules

| Condition | Result |
|---|---|
| The page says voting is still open | `INVALID` |
| The page does not state clearly that voting is closed | `UNDETERMINED` |
| Votes in favor, votes against, the quorum or the threshold is missing, ambiguous or not supported | `UNDETERMINED` |
| Quorum stated as a percentage (the contract cannot know total supply) | `UNDETERMINED` |
| `for + against + abstain` is below the quorum | `INVALID` |
| Abstentions not stated and `for + against` is below the quorum (quorum cannot be checked) | `UNDETERMINED` |
| No votes for or against | `FAILED` |
| Simple majority: `for > against` | `PASSED`, otherwise `FAILED` (a tie fails) |
| Two-thirds: `3 * for >= 2 * (for + against)` | `PASSED`, otherwise `FAILED` |

Abstentions count toward the quorum and are ignored by the threshold. Supported threshold wording: simple majority, more than half, `>50%`, `50% plus one`, two-thirds, `2/3`, `66%`, `66.67%`, `67%`. Anything else (for example "supermajority", "absolute majority" or `75%`) gives `UNDETERMINED`. Vote numbers may use thousands separators, up to six decimals and the suffixes `k`, `m`, `b`; a number that is ambiguous or not exact (for example `1.200.000`, two candidate numbers in one quote, only a percentage, a negative number, or wording such as "more than", "at least", "approximately", "100+") is not guessed and the fact stays unstated; for the quorum only "at least" and "minimum" are accepted as exact. A bare "majority" or a majority with another percentage (for example "60% majority") is not a simple majority and gives `UNDETERMINED`. Negated status wording such as "not open" or "not closed" is not read as open or closed. Quotes that read like instructions to a model (for example "ignore previous instructions") are dropped; ordinary words such as "system" are fine. Negated or qualified threshold wording ("not a simple majority", "qualified majority") is unsupported. `get_rules()` returns the same rules from the contract.

Vote counts are stored multiplied by `vote_scale` (1,000,000) so decimals stay exact integers.

## Lifecycle

```
register_ballot -> REGISTERED
REGISTERED --assess, decided--> RATED (challenge window opens)
REGISTERED --assess, undetermined, 3rd time--> FINAL (UNDETERMINED)
REGISTERED --stale, expire_ballot--> FINAL (UNDETERMINED)
RATED --challenge (2 GEN bond)--> CHALLENGED
RATED --finalize after the window--> FINAL
CHALLENGED --resolve_challenge, result changes--> FINAL (challenger gets bond + assurance)
CHALLENGED --resolve_challenge, result holds or counter evidence does not cite the ballot URL--> RATED (registrant gets bond, window reopens)
CHALLENGED --resolve_challenge, undetermined--> RATED (bond refunded, window reopens)
CHALLENGED --stale, cancel_challenge--> RATED (bond refunded, window reopens)
```

The registrant may attach an optional assurance of 0 to 100 whole GEN when registering. It is returned when the ballot reaches FINAL, unless a challenge changes the result, in which case the challenger receives it together with their bond.

A challenge is only about the evidence. The counter-evidence page must cite the full ballot URL as a whole token and sit under the prefix the ballot was registered under. That prefix is stored on the ballot at registration and never changes, so later prefix edits by the owner cannot block or widen challenges. The original page is not extracted again: every fact the counter page quotes replaces the same fact in the stored, consensus-accepted result (a counter quote that cannot be read as an exact value makes the merged result `UNDETERMINED`, so the challenge is refunded instead of the old value being kept), the merged facts go through the same rules, and the challenge wins only if the result code changes.

A challenge that does not change the result (or whose page does not cite the ballot) pays its bond to the registrant. A challenge that cannot be decided (for example the counter page cannot be fetched) refunds the bond and does not use up the chance to challenge. Both cases reopen a fresh window, bounded: at most 2 rejected and 3 inconclusive challenges per ballot, after which no more challenges are accepted and the original window simply runs out.

A ballot URL whose ballot ended `UNDETERMINED`, or ended `INVALID` because voting was still open, may be registered again later (for example after the vote closes). The URL then points to the newest ballot.

## Contract

`contracts/ballotproof.py` (single file, deploy as is). Constructor: `challenge_window_seconds`, `stale_after_seconds` (each 60 to 604800). Suggested values: `900, 1800` for testing and `172800, 259200` for production.

| Method | Who | Purpose |
|---|---|---|
| `add_prefix(prefix, label)` / `remove_prefix(prefix)` | owner | manage the https URL prefixes new ballots may be registered under; existing ballots keep their stored prefix |
| `register_ballot(url)` payable, 0-100 whole GEN | anyone | register a vote result page; invalid input is refunded to the caller's balance, not reverted |
| `assess(ballot_id)` | anyone | consensus extraction and result |
| `challenge(ballot_id, counter_evidence_url)` payable, exactly 2 GEN | anyone but the registrant | dispute the result |
| `resolve_challenge(ballot_id)` | anyone | consensus extraction of the counter evidence, merged with the stored result |
| `cancel_challenge(ballot_id)` | anyone | refund a challenge that stayed unresolved past the stale limit |
| `finalize(ballot_id)` | anyone | close a result after the window |
| `expire_ballot(ballot_id)` | anyone | release a ballot stuck before its first result |
| `withdraw()` | anyone | pull payment of the caller's balance |

Views: `get_params`, `get_rules`, `get_stats`, `list_prefixes`, `list_ballots(offset, limit)`, `get_ballot`, `find_ballot(url)`, `get_outcome(ballot_id)`, `get_outcome_by_url(url)`, `is_passed(ballot_id)`, `is_passed_by_url(url)`, `get_balance`, `get_accounting`.

## Using the registry from another contract

Only FINAL results are exposed through `get_outcome`, `get_outcome_by_url`, `is_passed` and `is_passed_by_url`. An empty string or `False` means "no final result yet". `is_passed` is `True` only for a FINAL `PASSED` ballot.

```python
# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *


class ExecuteIfPassed(gl.Contract):
    registry: str
    executed: TreeMap[str, u256]

    def __init__(self, registry_address: str):
        self.registry = registry_address

    @gl.public.write
    def execute(self, ballot_id: str) -> str:
        if ballot_id in self.executed:
            raise Exception("already executed")
        registry = gl.get_contract_at(Address(self.registry))
        if not registry.view().is_passed(ballot_id):
            raise Exception("ballot has no final PASSED outcome")
        self.executed[ballot_id] = u256(1)
        return "EXECUTED"
```

Deploy it with the BallotProof address as `registry_address`. `execute("b1")` reverts until ballot `b1` is FINAL and `PASSED`, and can run only once per ballot. This sample is exercised by the test suite.

## Deployment

Deploy `contracts/ballotproof.py` unchanged on GenLayer Studio with constructor `900, 1800`, then add the deployed address and explorer link here. The contract is submitted on its own; there is no frontend in this repository.

`evidence/` holds sample vote result pages for live testing. The sample prefix is `https://raw.githubusercontent.com/123Cryp/BallotProof/main/evidence/`.

| Page | Facts | Expected result |
|---|---|---|
| `v1.txt` | closed, 1,200,000 for, 800,000 against, quorum met, simple majority | `PASSED` |
| `v1-correction.txt` | cites `v1.txt`, states 1,500,000 against | challenge on `v1.txt` changes the result to `FAILED` |
| `v2.txt` | closed, 420,000 votes cast, quorum 1,000,000 | `INVALID` |
| `v3.txt` | voting still open | `INVALID` |
| `v4.txt` | closed, 600,000 for, 400,000 against, two-thirds required | `FAILED` |
| `v4-note.txt` | cites `v4.txt`, repeats the same numbers | challenge on `v4.txt` is rejected |

## Tests

```
python3 -m unittest discover -s tests -p "test_*.py"
```

No pip install is needed. The suite runs against a small offline stand-in for the GenLayer SDK (`tests/genlayer_stub.py`) with a scripted stand-in for the model. After every call it checks that the contract's real GEN balance equals its recorded obligations. It covers the URL rules, each parser, an exhaustive comparison of the rule engine with an independent oracle, quote grounding, the validator checks against a tampered leader, all challenge paths, stuck-state exits, randomized sequences, and the README sample contract. `tests/test_mutation.py` changes the contract source in many small ways and requires the suite to fail for every change. The stand-in model cannot show how a real model behaves; that is covered by the live tests on Studio.

See `ARCHITECTURE.md` for the state machine, consensus design, accounting and trust assumptions.

## License

MIT
