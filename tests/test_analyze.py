import unittest

from scripts.analyze import affiliated, in_window, issue_refs


class IssueReferenceTests(unittest.TestCase):
    def pr(self, text: str) -> dict:
        return {"title": text, "body": ""}

    def test_github_closing_forms(self):
        self.assertEqual(
            issue_refs(self.pr("Fixes #12, #13 and PostHog/posthog#14")),
            [12, 13, 14],
        )
        self.assertEqual(issue_refs(self.pr("Resolves PostHog/posthog#99")), [99])
        self.assertEqual(
            issue_refs(self.pr("Closes https://github.com/PostHog/posthog/issues/42")),
            [42],
        )
        self.assertEqual(
            issue_refs(
                self.pr(
                    "Closes [**#76914**]"
                    "(https://github.com/PostHog/posthog/issues/76914)"
                )
            ),
            [76914],
        )

    def test_non_closing_keyword_is_ignored(self):
        self.assertEqual(issue_refs(self.pr("Implements #12")), [])

    def test_keyword_must_be_immediately_followed_by_reference(self):
        pr = {
            "title": "fix(deltalite): close the three delta-rs MERGE fallback causes",
            "body": "Context mentions #1, #2, and #3 later.",
        }
        self.assertEqual(issue_refs(pr), [])

    def test_reference_list_stops_at_unrelated_text(self):
        self.assertEqual(issue_refs(self.pr("Fixes #12. Related: #99")), [12])

    def test_reference_must_exist_when_census_is_provided(self):
        self.assertEqual(issue_refs(self.pr("Fixes #12, #13"), {13}), [13])


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
