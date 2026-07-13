import json
import re
from pathlib import Path

from csvql import CSVQLSession

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_BLOB_PREFIX = "https://github.com/highlordleonas/csvql/blob/main/"
REPO_RAW_PREFIX = "https://raw.githubusercontent.com/highlordleonas/csvql/main/"
LINK_RE = re.compile(r"!?\[[^]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^#{1,6} +(.+?) *#* *$", flags=re.MULTILINE)
JSON_FENCE_RE = re.compile(r"```json\n(.*?)\n```", flags=re.DOTALL)
API_FACTORY_RE = re.compile(r"CSVQLSession\.(from_[a-z_]+)\(")
USER_DOC_PATHS = tuple(
    sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for pattern in ("*.md", "docs/**/*.md", "examples/**/*.md")
        for path in REPO_ROOT.glob(pattern)
    )
)


def read_doc(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def normalized_markdown_section(path: str, heading: str) -> str:
    marker = f"## {heading}\n"
    _, separator, remainder = read_doc(path).partition(marker)
    assert separator, f"{path}: missing {heading!r} section"
    section, _, _ = remainder.partition("\n## ")
    return " ".join(section.split())


def test_readme_is_a_curated_user_starting_point() -> None:
    readme = read_doc("README.md")

    assert "## Contents" in readme
    for expected_link in (
        f"[Getting started]({REPO_BLOB_PREFIX}docs/getting-started.md)",
        f"[CLI reference]({REPO_BLOB_PREFIX}docs/cli-reference.md)",
        f"[Troubleshooting]({REPO_BLOB_PREFIX}docs/troubleshooting.md)",
        f"[Terminal menu guide]({REPO_BLOB_PREFIX}docs/tui-guide.md)",
        f"[Roadmap]({REPO_BLOB_PREFIX}docs/ROADMAP.md)",
        f"[Contributing]({REPO_BLOB_PREFIX}CONTRIBUTING.md)",
        f"[Security]({REPO_BLOB_PREFIX}SECURITY.md)",
        f"[Support]({REPO_BLOB_PREFIX}SUPPORT.md)",
    ):
        assert expected_link in readme


def test_readme_links_are_safe_for_pypi_rendering() -> None:
    for target in LINK_RE.findall(read_doc("README.md")):
        assert target.startswith(("https://", "mailto:", "#")), target


def test_long_reference_docs_include_curated_navigation() -> None:
    for path in ("docs/cli-reference.md", "docs/json-contracts.md"):
        assert "## Contents" in read_doc(path)


def test_user_documentation_links_resolve() -> None:
    for path in USER_DOC_PATHS:
        document_path = REPO_ROOT / path
        for target in LINK_RE.findall(read_doc(path)):
            repository_target = False
            for prefix in (REPO_BLOB_PREFIX, REPO_RAW_PREFIX):
                if target.startswith(prefix):
                    target = target.removeprefix(prefix)
                    repository_target = True
                    break
            if "://" in target or target.startswith("mailto:"):
                continue
            target_path, separator, fragment = target.partition("#")
            if repository_target:
                target_document = REPO_ROOT / target_path
            else:
                target_document = (
                    document_path.parent / target_path if target_path else document_path
                )
            assert target_document.is_file(), f"{path}: {target}"
            if separator and target_document.suffix.lower() == ".md":
                anchors = _markdown_anchors(target_document.read_text(encoding="utf-8"))
                assert fragment in anchors, f"{path}: {target}"


def test_json_reference_examples_are_valid_json() -> None:
    examples = JSON_FENCE_RE.findall(read_doc("docs/json-contracts.md"))

    assert examples
    for example in examples:
        json.loads(example)


def test_documented_session_factories_exist() -> None:
    factories = API_FACTORY_RE.findall(read_doc("docs/cli-reference.md"))

    assert factories
    for factory in factories:
        assert hasattr(CSVQLSession, factory), factory


def test_tui_docs_disclose_large_result_temporary_storage() -> None:
    history = normalized_markdown_section("docs/tui-guide.md", "History")
    components = normalized_markdown_section("docs/ARCHITECTURE.md", "Components")
    design_choices = normalized_markdown_section("docs/ARCHITECTURE.md", "Design Choices")

    for expected in (
        "Large query results are written",
        "session-owned temporary files",
        "secure operating-system temporary storage",
        "same-directory atomic completion",
        "normal exit removes expected temporary files directly",
    ):
        assert expected in history
    for expected in (
        "at least 24 hours old",
        "exactly match the expected structure",
        "validate fully",
        "are unlocked",
        "Recovery is bounded and conservative",
        "skips anything uncertain",
        "Hard kills can leave temporary files",
        "later launch or operating-system cleanup",
    ):
        assert expected in history
    assert "tui_result_store.py" in components
    assert "spill automatically" in design_choices


def test_tui_docs_explain_unavailable_spill_storage() -> None:
    history = normalized_markdown_section("docs/tui-guide.md", "History")

    for expected in (
        "spill storage is unavailable",
        "Small in-memory results still work",
        "A large result that requires spill storage fails",
        "sanitized storage error",
        "does not retain it",
        "unbounded memory fallback",
    ):
        assert expected in history


def test_tui_docs_explain_cleanup_warning_contract() -> None:
    history = normalized_markdown_section("docs/tui-guide.md", "History")
    components = normalized_markdown_section("docs/ARCHITECTURE.md", "Components")

    for expected in (
        "After the menu returns normally",
        "cleanup failure",
        "at most one",
        "sanitized warning",
        "does not change",
        "otherwise successful exit code",
    ):
        assert expected in history
    assert "at most one sanitized warning" in components
    assert "does not change an otherwise successful exit code" in components


def test_tui_docs_explain_lost_spilled_result_contract() -> None:
    history = normalized_markdown_section("docs/tui-guide.md", "History")

    assert "older spilled result" in history
    assert "History and its bounded preview remain available" in history
    assert "Full-result load, export" in history
    assert "export, and save-result are unavailable" in history


def test_tui_docs_distinguish_spill_retention_from_query_execution() -> None:
    history = normalized_markdown_section("docs/tui-guide.md", "History")
    design_choices = normalized_markdown_section("docs/ARCHITECTURE.md", "Design Choices")

    assert "fully materializes each Python `QueryResult`" in history
    assert "before deciding whether to spill" in history
    assert "does not bound DuckDB query execution memory" in design_choices
    assert "does not stream query execution" in design_choices


def _markdown_anchors(document: str) -> set[str]:
    anchors: set[str] = set()
    occurrences: dict[str, int] = {}
    for heading in HEADING_RE.findall(document):
        base = re.sub(r"[^a-z0-9_ -]", "", heading.lower())
        base = re.sub(r"[ -]+", "-", base.strip())
        occurrence = occurrences.get(base, 0)
        anchor = base if occurrence == 0 else f"{base}-{occurrence}"
        anchors.add(anchor)
        occurrences[base] = occurrence + 1
    return anchors
