"""Extract every fenced phone-lines block; ignore notes outside the fences."""
from __future__ import annotations


class IssueLinesError(ValueError):
    pass


def extract_issue_lines(body: str, *, sport: str = "MLB") -> str:
    marker = "### Lines"
    if marker in body:
        body = body.split(marker, 1)[1]
        body = body.split("\n### ", 1)[0]
    if body.count("```") % 2:
        raise IssueLinesError(f"{sport}_INTAKE_UNCLOSED_FENCE")
    if "```" in body:
        blocks = []
        for block in body.split("```")[1::2]:
            if block.startswith("text"):
                block = block[4:]
            elif "\n" in block:
                first, rest = block.split("\n", 1)
                if first.strip().isalpha():
                    block = rest
            blocks.append(block.strip())
        return "\n\n".join(blocks).strip()
    return body.replace("```text", "").replace("```", "").strip()
