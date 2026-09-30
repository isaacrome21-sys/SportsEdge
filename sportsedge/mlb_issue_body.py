"""Extract phone lines from a GitHub issue body. Notes outside the fence are ignored."""
from __future__ import annotations


class IssueLinesError(ValueError):
    pass


def extract_issue_lines(body: str) -> str:
    marker = "### Lines"
    if marker in body:
        body = body.split(marker, 1)[1]
        body = body.split("\n### ", 1)[0]
    if body.count("```") == 1:
        raise IssueLinesError("MLB_INTAKE_UNCLOSED_FENCE")
    if "```" in body:
        block = body.split("```", 2)[1]
        if block.startswith("text"):
            block = block[4:]
        elif "\n" in block:
            first, rest = block.split("\n", 1)
            if first.strip().isalpha():
                block = rest
        return block.strip()
    return body.replace("```text", "").replace("```", "").strip()
