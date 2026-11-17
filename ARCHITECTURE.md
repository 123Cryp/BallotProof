# BallotProof architecture

## Entities

- **Prefix**: an https URL prefix with a label, added by the contract owner. Ballots can only be registered under a current prefix. When a ballot URL matches more than one prefix, the longest one the URL is strictly longer than is used.
- **Evidence binding**: at registration the matched prefix and its label are copied onto the ballot (`prefix`, `label`). This binding is immutable and is the ballot's challenge authority: counter-evidence must sit under the stored `prefix`, never under the owner's current prefix list. Removing, re-adding or adding prefixes later affects only new registrations.
- **Ballot**: id `b1`, `b2`, ... with the canonical result page URL, registrant, state, optional assurance, the stored tally, the result code, and challenge data. One URL maps to the newest ballot; an older ballot of the same URL stays readable under its own id.
- **Tally**: the six grounded quotes (`raw`), the numbers and flags derived from them (`fields`), the result code and a short reason.

## Result codes

`PASSED`, `FAILED`, `INVALID` (still open, or quorum not reached) and `UNDETERMINED` (the page does not give enough clear, supported facts). They are computed only by `_decide` in the contract code. The model returns six quotes and nothing else is read from its answer.

## Ballot state machine

```
register_ballot -> REGISTERED
REGISTERED --assess, decided--> RATED (challenge_end = now + window)
REGISTERED --assess, undetermined (attempts+1)--> REGISTERED, or FINAL/UNDETERMINED on the 3rd attempt (assurance refunded)
REGISTERED --stale, expire_ballot--> FINAL/UNDETERMINED (assurance refunded)
RATED --challenge, before challenge_end, caps not reached--> CHALLENGED
RATED --finalize after challenge_end--> FINAL (assurance refunded)
CHALLENGED --resolve, merged result differs--> FINAL (challenger: bond + assurance), tally replaced, original_outcome kept
CHALLENGED --resolve, merged result equal--> RATED (registrant: bond), rejections+1, window reopened
CHALLENGED --resolve, counter page lacks the ballot URL--> RATED (registrant: bond), rejections+1, window reopened
CHALLENGED --resolve, undetermined--> RATED (challenger: bond back), inconclusive+1, window reopened
CHALLENGED --stale, cancel_challenge--> RATED (challenger: bond back), inconclusive+1, window reopened
```

Every state has an exit that needs no particular party: `assess` or `expire_ballot` for REGISTERED, `finalize` for RATED, `resolve_challenge` or (after `stale_after_seconds`) `cancel_challenge` for CHALLENGED. A consensus failure on the network leaves storage untouched and the stale timers open the exit. Only FINAL results are served by the registry views.

### Challenge windows

A challenge that cannot be decided (counter page unreachable, merged facts incomplete, stale cancellation) must not burn the chance to challenge or close the window. It refunds the bond, counts as `inconclusive` and reopens a fresh window: `challenge_end = max(challenge_end, now + challenge_window)`. A challenge that is decided against the challenger counts as a `rejection`, pays the bond to the registrant and also reopens a fresh window. The reopening is bounded: after 2 rejections or 3 inconclusive challenges no further challenge is accepted and the window is not extended again, so the original `challenge_end` applies. A griefing challenger can therefore delay finalization by a bounded amount only, and a bond is lost on every rejection. Only a challenge that changes the result code ends the ballot early.

## Extraction and result pipeline

`_assess_page` (and, for the counter page, `_assess_counter`) runs identically on the leader and on every validator:

1. Fetch the page (first 12,000 characters). A failed fetch is UNDETERMINED.
2. Ask the model for six quotes: votes in favor, votes against, abstentions, quorum, threshold rule, closed or open. The prompt declares the page untrusted and forbids deciding or counting.
3. `_ground`: a quote is kept only if it is 3 to 200 characters, occurs in the page after whitespace and case normalisation, and its wording fits the field (the votes-in-favor quote must name the in-favor side and neither the against nor the abstain side, and so on; the threshold quote must not be about quorum). Anything else becomes an empty string. Non-string model values are treated as empty, never as the text "None".
4. `_derive`: numbers, the threshold type and the closed state are parsed from the quotes by regular expressions, never by the model. A quote with more than one candidate number, a malformed grouping such as `1.200.000`, more than six decimals, or only a percentage is not guessed; the fact stays unstated.
5. `_decide`: applies the rules in the README table and returns the result code. A missing or unsupported fact gives UNDETERMINED.

Conservative defaults: a fact that cannot be grounded or parsed is unstated, and an unstated closed flag, count, quorum or threshold never produces `PASSED`. Text the model invents is dropped by the quote check, and a quote taken from the wrong field is dropped by the label check, so neither can change a count.

## Consensus

Both consensus calls use `gl.vm.run_nondet_unsafe(leader, validator)` called positionally from module-level functions that capture only plain strings, never the contract.

- The leader returns the full result as canonical JSON. Errors inside the closure become an ordinary UNDETERMINED result.
- A validator re-runs the whole pipeline on its own copy of the page and requires an exact match of the consensus key: status, result code, closed state, threshold type, votes in favor, votes against and quorum, plus abstentions only when the quorum outcome depends on them (that is, when `for + against` is below the quorum). For a page that says voting is open the key is just the status and the result code, because no number can change `INVALID`. Facts that cannot change any rule are not part of the key, so harmless wording differences (for example one model quoting the abstention line and another skipping it) do not block consensus.
- The validator also checks the leader's output deterministically: every leader quote occurs in the validator's page and passes the label check, and re-deriving the leader's quotes reproduces the leader's fields and result code. A leader therefore cannot store a fabricated quote or a number that does not follow from its quotes. A tampered or malformed leader result is rejected.
- After consensus the contract recomputes `_decide` from the accepted quotes before it stores anything, so the stored result code always follows from the stored quotes.
- A challenge does not re-extract the original page. It starts from the grounded quotes stored with the consensus-accepted result, so a challenger cannot win just because a second extraction of the same page came out differently. Only the counter page is fetched and extracted. It must contain the full stored ballot URL as a whole token (case-insensitive, within the first 12,000 characters, not glued to other text and not followed by more URL characters); without it the result is NO_ANCHOR and no model call is made. Counter facts replace stored facts only where the counter page states them with a grounded, parseable quote. The merged quotes are decided by the same rules and compared with the stored result code. Validators check that the leader's counter quotes occur on their own copy of the counter page, that the merge reproduces the leader's merged quotes, fields and result code, and the contract recomputes the merge again before it pays anyone.

Pages should be static text, ideally pinned to a commit. If the page changes between validators' fetches, validators disagree and the transaction does not complete; the stale paths cover that.

## URL rules

Ballot and counter-evidence URLs must be https, ASCII with no whitespace or control characters, no credentials, no non-443 port, no `.` or `..` path segments, no `//` in the path, no `%2e`, `%2f`, `%5c` or `%00`, no query and no fragment, and, after lower-casing the host and dropping `:443`, start with one of the owner's current prefixes (registration) or with the ballot's stored prefix (counter-evidence) and be longer than it. Prefixes themselves must end with `/`, have a non-empty path and no query. Look-alike hosts and `host@evil` forms fail the parsed-URL checks.

## Money

All amounts are wei internally; users enter whole GEN. Payouts are pull-based: every credit goes to `balances` and `withdraw` transfers after it zeroes the balance. Payable methods (`register_ballot`, `challenge`) never raise on bad input; they credit the attached value back to the caller's balance. Invariant checked in tests after every call:

```
contract balance == sum(balances) + sum(open challenge bonds) + sum(open assurances)
```

`get_accounting` computes the right side by scanning every ballot and also reports whether it matches the running totals.

## Trust assumptions

- The owner is trusted to choose prefixes under content the DAO controls. The owner cannot change results, windows, bonds or any balance, and changing the prefix list does not affect existing ballots.
- The page text is the source of truth. The contract proves that the numbers it uses are on the page and that the arithmetic is right; it cannot prove that the page itself is honest. A prefix on a place where anyone can publish lets anyone author a result page, and a page that contains two conflicting lines for the same fact can only be resolved by what the validators quote (if they quote different lines, consensus fails and nothing is stored). Consumers of the registry should check the ballot's `label` and URL, and production prefixes should point at static pages pinned to a commit.
- A counter-evidence page is treated as an authoritative correction for the facts it states. Challenging requires a page under the ballot's own stored prefix that cites the ballot URL.
- Validators are trusted only to locate quoted facts. They never produce the result code, and the code checks their quotes.
- A registrant who attaches assurance accepts that a successful challenge pays it to the challenger, including when the cause is an ambiguous page.

## Known limits

- The quorum must be an absolute vote count; a quorum stated only as a percentage gives UNDETERMINED. Supported thresholds are simple majority and two-thirds. Pages that name vote options differently (for example "Option A") are not understood.
- Abstentions count toward the quorum and are ignored by the threshold; DAOs that define these differently need a different rule set.
- Decimal separators are assumed to be US style (`1,200,000.5`).
- Quotes are capped at 200 characters and pages at 12,000 characters, so a result must appear near the top of the page.
- At most 500 ballots and 10 prefixes; list views are paginated (50 per page).
- A ballot is final after its challenge window; a changed vote page needs a new URL, except that an `UNDETERMINED` ballot or one that ended `INVALID` because voting was open can be registered again under the same URL.
- Time comes from `datetime.datetime.now()` as seen by GenVM.
