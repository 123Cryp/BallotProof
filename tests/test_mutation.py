import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "..", "contracts", "ballotproof.py")

MUTATIONS = [
    ("simple majority counts a tie", 'ok = f["for"] > f["against"]', 'ok = f["for"] >= f["against"]'),
    ("two-thirds is strict", 'ok = 3 * f["for"] >= 2 * decisive', 'ok = 3 * f["for"] > 2 * decisive'),
    ("quorum is inclusive of the limit", 'if cast < f["quorum"]:', 'if cast <= f["quorum"]:'),
    ("abstentions ignored for quorum", 'cast = decisive + (f["abstain"] if f["abstain"] >= 0 else 0)', "cast = decisive"),
    ("zero decisive votes can pass", "if decisive == 0:", "if decisive == -1:"),
    ("open voting is not invalid", '"INVALID", "voting is still open"', '"FAILED", "voting is still open"'),
    ("unstated closed state accepted", 'if f["closed"] != "CLOSED":', "if False:"),
    ("quotes are not grounded", "            and _norm(q) in page_norm\n", ""),
    ("labels are not checked", "            and _label_ok(key, q)\n", ""),
    ("quote length not capped", "[:MAX_QUOTE]", ""),
    ("page length not capped", "return str(text)[:MAX_PAGE]", "return str(text)"),
    ("ambiguous vote numbers accepted", "    if len(plain) > 1:\n        return None\n", "    if len(plain) > 99:\n        return None\n"),
    ("bad thousands grouping accepted", 'if "," in tok and not GROUPED_RE.match(tok):', "if False:"),
    ("inexact decimals truncated", "    if num % den:\n        return None\n", "    if False:\n        return None\n"),
    ("vote cap removed", "return value if value <= MAX_SCALED else None", "return value"),
    ("percent not excluded from vote numbers", "if PERCENT_RE.match(low, m.end()):", "if False:"),
    ("suffix multiplier ignored", "mult = SUFFIX_MULT[sm.group(1)] if sm else 1", "mult = 1"),
    ("zero words ignored", "    if VOTES_ZERO_RE.search(low):\n        return 0\n", "    if VOTES_ZERO_RE.search(low):\n        return None\n"),
    ("percent quorum not flagged", '    if percent:\n        return "PERCENT", -1', '    if percent:\n        return "UNSTATED", -1'),
            ("conflicting or missing thresholds accepted", "    if two == simple:\n        return None\n", "    if False:\n        return None\n"),
        ("closed and open together accepted", "    if closed == opened:\n        return None\n", "    if False:\n        return None\n"),
    ("for label accepts against words", "return has_for and not has_against and not has_abstain", "return has_for"),
    ("counter ignores unreadable quotes", '        if _as_text(counter.get(key)):\n', '        if _as_text(counter.get(key)) and _parse_votes(counter[key]) is not None:\n'),
    ("counter overrides with empty quotes", '        if _as_text(counter.get(key)):\n', '        if True:\n'),
    ("validator skips grounding", "    if not _grounded(raw, page):\n        return False\n", "    if False:\n        return False\n"),
    ("pair validator skips raw check", 'and m["raw"] == merged_raw', "and True"),
    ("validator skips outcome check", 'and again["outcome"] == lead["outcome"]', "and True"),
    ("validator skips key check", "return _key(lead) == _key(mine) and _verify_single(lead, page)", "return _verify_single(lead, page)"),
    ("key includes irrelevant abstentions", 'relevant = f["abstain"] if f["for"] + f["against"] < f["quorum"] else -2', 'relevant = f["abstain"]'),
    ("anchor may be a prefix of a longer URL", 'r"(?![a-z0-9_~%/-])(?!\\.[a-z0-9])"', 'r""'),
    ("anchor may be glued to text", 'r"(?<![a-z0-9+.-])"', 'r""'),
    ("anchor not required", "    if not _cites(page, url):", "    if False:"),
    ("recheck removed", 'if again["status"] != "DECIDED" or again["outcome"] != res.get("outcome"):', "if False:"),
    ("bond may exceed exact amount", "if value != bond:", "if value < bond:"),
    ("registrant may challenge", 'if who.lower() == b["registrant"].lower():', "if False:"),
    ("counter may equal ballot page", 'if cu == b["url"]:', "if False:"),
    ("counter checked against live prefixes", "cu = _check_evidence(counter_evidence_url, [bound]) if bound else None", "cu = _check_evidence(counter_evidence_url, [item[0] for item in self._prefixes()])"),
    ("challenge after window", 'if now >= b["challenge_end"]:', "if False:"),
    ("challenge caps removed", 'if b["rejections"] >= MAX_REJECTIONS or b["inconclusive"] >= MAX_INCONCLUSIVE:', "if False:"),
    ("challenge wins without a change", 'if status == "OK" and merged["outcome"] != b["outcome"]:', 'if status == "OK":'),
    ("upheld pays registrant", 'self._credit(b["challenger"], bond + prize)', 'self._credit(b["registrant"], bond + prize)'),
    ("rejected pays challenger", 'self._credit(b["registrant"], bond)', 'self._credit(b["challenger"], bond)'),
    ("undetermined keeps the bond", '            self._credit(b["challenger"], bond)\n            b["inconclusive"] += 1', '            self._credit(b["registrant"], bond)\n            b["inconclusive"] += 1'),
    ("window closes after a failed challenge", 'b["challenge_end"] = max(b["challenge_end"], now + int(self.challenge_window))', 'b["challenge_end"] = now'),
    ("window always reopens", 'if b["rejections"] < MAX_REJECTIONS and b["inconclusive"] < MAX_INCONCLUSIVE:', "if True:"),
    ("rejections not counted", '            b["rejections"] += 1\n', ""),
    ("resolve ignores staleness", 'if now - b["challenge_filed"] > int(self.stale_after):', "if False:"),
    ("cancel before stale", 'if now - b["challenge_filed"] <= int(self.stale_after):', "if False:"),
    ("finalize inside the window", 'if self._now() < b["challenge_end"]:', "if False:"),
    ("assess after stale", '        if self._is_stale(b, now):\n            raise Exception("assessment window expired, call expire_ballot")\n', ""),
    ("expire before stale", "if not self._is_stale(b, self._now()):", "if False:"),
    ("attempt limit off by one", 'if b["attempts"] >= MAX_ATTEMPTS:', 'if b["attempts"] > MAX_ATTEMPTS:'),
    ("attempts not counted", '        b["attempts"] += 1\n', ""),
    ("window not set on rating", 'b["challenge_end"] = now + int(self.challenge_window)', 'b["challenge_end"] = now'),
    ("fractional assurance accepted", "if value % WEI != 0 or value > MAX_ASSURANCE_GEN * WEI:", "if value > MAX_ASSURANCE_GEN * WEI:"),
    ("duplicate URL accepted", "if u in self.url_index and not self._replaceable(self._load(self.url_index[u])):", "if False:"),
    ("any invalid ballot replaceable", 'return b["outcome"] == "INVALID" and b["tally"]["fields"]["closed"] == "OPEN"', 'return b["outcome"] == "INVALID"'),
    ("active ballot replaceable", '        if b["state"] != "FINAL":\n            return False\n', ""),
    ("ballot cap removed", "if int(self.ballot_count) >= MAX_BALLOTS:", "if False:"),
    ("prefix cap removed", "if len(items) >= MAX_PREFIXES:", "if False:"),
    ("anyone can add prefixes", '        if self._sender().lower() != self.owner.lower():\n            raise Exception("only the owner can manage prefixes")\n        p = _norm_prefix(prefix)\n        if p is None:', "        p = _norm_prefix(prefix)\n        if p is None:"),
    ("pending result served", 'return b["outcome"] if b["state"] == "FINAL" else ""', 'return b["outcome"]'),
    ("failed counts as passed", 'return self._final_outcome(ballot_id) == "PASSED"', 'return self._final_outcome(ballot_id) in ("PASSED", "FAILED")'),
    ("withdraw keeps the balance", "        self.balances[k] = u256(0)\n", ""),
    ("assurance not zeroed on release", '            b["assurance"] = 0\n        return amount', "        return amount"),
    ("rejected payable keeps the money", "        self._credit(self._sender(), value)\n        return", "        return"),
    ("evidence equal to prefix accepted", "if c.startswith(pre) and len(c) > len(pre):", "if c.startswith(pre):"),
    ("port check removed", "if port not in (None, 443):", "if False:"),
    ("dot segments accepted", 'if "." in segments or ".." in segments:', 'if ".." in segments:'),
    ("credentials accepted", ' or "@" in parts.netloc', ""),
    ("page size lookup lost", "min(max(int(limit), 1), PAGE_LIMIT)", "min(int(limit), PAGE_LIMIT)"),
    ("find accepts queries", 'if u is None or "?" in u or "#" in u:\n            return ""', 'if u is None:\n            return ""'),
    ("unknown ballot raises in payable", 'if str(ballot_id) not in self.ballots:\n            return self._reject("unknown ballot", value)', "pass"),
    ("challenge outside RATED", 'if b["state"] != "RATED":\n            return self._reject("ballot is not awaiting challenge", value)', "pass"),
    ("binding ignores strict length", "if u.startswith(item[0]) and len(u) > len(item[0]) and len(item[0]) > len(bound):", "if u.startswith(item[0]) and len(item[0]) > len(bound):"),
    ("upheld keeps the old reason", '            b["reason"] = merged["reason"]\n', ""),
    ("inconclusive reason overwrites the result reason", '            b["challenge_reason"] = str(res.get("reason", ""))[:200]\n            self._reopen(b, now)\n        self._save(b)', '            b["reason"] = str(res.get("reason", ""))[:200]\n            self._reopen(b, now)\n        self._save(b)'),
    ("inexact vote numbers accepted", "    if VOTES_INEXACT_RE.search(low) or NEGATIVE_RE.search(low):\n        return None\n", "    if False:\n        return None\n"),
    ("inexact quorum accepted", '    if QUORUM_INEXACT_RE.search(low) or NEGATIVE_RE.search(low):\n        return "UNSTATED", -1\n', "    if False:\n        return 0\n"),
    ("other percentages accepted as majority", "if any(not ok.match(n) for n in PERCENT_NUM_RE.findall(low)):", "if False:"),
    ("negated status accepted", "    if NEGATED_RE.search(low):\n        return None\n", "    if False:\n        return None\n"),
    ("instruction-like quotes kept", "            and INSTRUCTION_RE.search(_norm(q)) is None\n", ""),
    ("qualified majority accepted", "    if QUALIFIED_RE.search(low) or NEGATION_RE.search(low):\n        return None\n", "    if False:\n        return None\n"),
    ("bonds missing from accounting", 'bonds += b["bond"]', "bonds += 0"),
]


def run_suite(path):
    env = dict(os.environ, BALLOTPROOF_CONTRACT=path, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "test_ballotproof", "-f"],
        cwd=HERE,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return proc.returncode


class TestMutations(unittest.TestCase):
    def test_every_mutation_is_caught(self):
        with open(SOURCE, encoding="utf-8") as fh:
            src = fh.read()
        with tempfile.TemporaryDirectory() as tmp:
            control = os.path.join(tmp, "control.py")
            with open(control, "w", encoding="utf-8") as fh:
                fh.write(src)
            self.assertEqual(run_suite(control), 0, "the unmodified contract must pass the suite")
            jobs = []
            for i, (name, old, new) in enumerate(MUTATIONS):
                self.assertEqual(src.count(old), 1, "mutation target must occur exactly once: " + name)
                path = os.path.join(tmp, "m%d.py" % i)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(src.replace(old, new))
                jobs.append((name, path))
            with ThreadPoolExecutor(max_workers=4) as pool:
                codes = list(pool.map(lambda j: run_suite(j[1]), jobs))
        survivors = [name for (name, _), code in zip(jobs, codes) if code == 0]
        self.assertEqual(survivors, [], "mutations the tests did not catch")
        self.assertGreaterEqual(len(MUTATIONS), 70)


if __name__ == "__main__":
    unittest.main()
