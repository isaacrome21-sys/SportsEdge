import importlib.util
import json
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "post_github_issue_comment", Path("scripts/post_github_issue_comment.py")
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class _Response:
    status = 201

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b"{}"


class PostGithubIssueCommentTest(unittest.TestCase):
    def test_posts_expected_issue_comment_request(self):
        seen = []

        def opener(req, timeout=15):
            seen.append((req, timeout))
            return _Response()

        MODULE.post_issue_comment(
            "hello card",
            issue=1210,
            repository="isaacrome21-sys/SportsEdge",
            token="secret-token",
            opener=opener,
        )
        self.assertEqual(len(seen), 1)
        req, timeout = seen[0]
        self.assertEqual(timeout, 15)
        self.assertEqual(
            req.full_url,
            "https://api.github.com/repos/isaacrome21-sys/SportsEdge/issues/1210/comments",
        )
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(json.loads(req.data.decode("utf-8")), {"body": "hello card"})
        headers = {k.lower(): v for k, v in req.header_items()}
        self.assertEqual(headers["authorization"], "Bearer secret-token")
        self.assertEqual(headers["accept"], "application/vnd.github+json")
        self.assertEqual(headers["x-github-api-version"], "2022-11-28")

    def test_empty_body_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "COMMENT_BODY_EMPTY"):
            MODULE.post_issue_comment(
                "  ", issue=1210, repository="isaacrome21-sys/SportsEdge", token="secret"
            )


if __name__ == "__main__":
    unittest.main()
