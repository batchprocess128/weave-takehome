import unittest

from scripts.analyze import affiliated, in_window, issue_refs


class IssueReferenceTests(unittest.TestCase):
    def pr(self, text: str) -> dict:
        return {"title": text, "body": ""}

    def test_github_closing_forms(self):
        self.assertEqual(issue_refs(self.pr("Fixes #12, #13")), [12, 13])
        self.assertEqual(issue_refs(self.pr("Resolves PostHog/posthog#99")), [99])
        self.assertEqual(
            issue_refs(self.pr("Closes https://github.com/PostHog/posthog/issues/42")),
            [42],
        )

    def test_non_closing_keyword_is_ignored(self):
        self.assertEqual(issue_refs(self.pr("Implements #12")), [])


class PopulationTests(unittest.TestCase):
    def test_affiliation_rules(self):
        members = {"public-member", "different-company"}
        self.assertTrue(affiliated({"login": "a", "company": "@PostHog"}, members))
        self.assertTrue(affiliated({"login": "engineer-ph", "company": ""}, members))
        self.assertTrue(affiliated({"login": "public-member", "company": ""}, members))
        self.assertFalse(
            affiliated({"login": "different-company", "company": "Elsewhere"}, members)
        )
        self.assertFalse(affiliated({"login": "release-bot", "type": "Bot"}, members))

    def test_window_is_inclusive(self):
        self.assertTrue(in_window("2026-05-20T00:00:00Z"))
        self.assertTrue(in_window("2026-08-18T23:59:59Z"))
        self.assertFalse(in_window("2026-05-19T23:59:59Z"))
        self.assertFalse(in_window("2026-08-19T00:00:00Z"))


if __name__ == "__main__":
    unittest.main()
