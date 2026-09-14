from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "index.html"
JOURNAL_JS = ROOT / "docs" / "assets" / "rigp_shell_case_journal.js"
JOURNAL_CSS = ROOT / "docs" / "assets" / "rigp_shell_case_journal.css"


def test_case_journal_assets_are_wired_once():
    html = INDEX.read_text(encoding="utf-8")
    assert html.count("assets/rigp_shell_case_journal.js") == 1
    assert html.count("assets/rigp_shell_case_journal.css") == 1
    assert JOURNAL_JS.exists()
    assert JOURNAL_CSS.exists()


def test_case_journal_keeps_local_pilot_contract_explicit():
    js = JOURNAL_JS.read_text(encoding="utf-8")
    assert "RIGP-CASE-BACKUP-v1" in js
    assert "rigp_cases_v1" in js
    assert "case_notes" in js
    assert "NOTA_ESTRUCTURADA_REGISTRADA" in js
    assert "navegador local" in js
    assert "no está sincronizado con backend" in js
    assert "no acreditan irregularidad, delito ni responsabilidad" in js
    assert "data/investigative_findings.json" not in js


def test_case_journal_javascript_syntax():
    node = shutil.which("node")
    assert node, "Node.js is required to validate browser JavaScript syntax"
    subprocess.run([node, "--check", str(JOURNAL_JS)], check=True)
