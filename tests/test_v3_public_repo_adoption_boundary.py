from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_repo_adoption_requires_license_and_revision_before_code_copy():
    text = (ROOT / "docs/public_repo_v3_pattern_adoptions.md").read_text()
    assert "No third-party source code is copied" in text
    assert "exact revision" in text
    assert "license" in text
    assert "provider/book identity" in text
