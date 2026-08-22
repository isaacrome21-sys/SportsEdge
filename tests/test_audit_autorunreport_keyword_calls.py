import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "audit_autorunreport_keyword_calls.py"
spec = importlib.util.spec_from_file_location("audit_autorunreport_keyword_calls", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def _write(tmp_path: Path, text: str) -> None:
    (tmp_path / "sample.py").write_text(text, encoding="utf-8")


def test_flags_positional_autorunreport(tmp_path):
    _write(tmp_path, "x = AutoRunReport(a, b, c)\n")
    violations = module.find_violations(tmp_path)
    assert violations == [f"POSITIONAL_AUTORUNREPORT {tmp_path / 'sample.py'}:1 positional_args=3"]


def test_accepts_keyword_only_autorunreport(tmp_path):
    _write(tmp_path, "x = AutoRunReport(a=a, b=b, c=c)\n")
    assert module.find_violations(tmp_path) == []


def test_flags_attribute_constructor_too(tmp_path):
    _write(tmp_path, "x = pkg.AutoRunReport(a, b)\n")
    violations = module.find_violations(tmp_path)
    assert violations == [f"POSITIONAL_AUTORUNREPORT {tmp_path / 'sample.py'}:1 positional_args=2"]
