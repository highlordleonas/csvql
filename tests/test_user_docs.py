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
INSTALLED_USER_DOC_PATHS = tuple(
    path for path in USER_DOC_PATHS if path not in {"CONTRIBUTING.md", "docs/development.md"}
)


def read_doc(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


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


def test_readme_guides_an_installed_user_from_setup_to_support() -> None:
    readme = read_doc("README.md")

    for heading in (
        "## Install and first query",
        "## Optional terminal menu",
        "## Compatibility and safety",
        "## Get help and stay current",
    ):
        assert heading in readme

    assert readme.index("## Install and first query") < readme.index("## Optional terminal menu")
    assert readme.index("## Optional terminal menu") < readme.index("## Compatibility and safety")
    assert "python -m pip install localql" in readme
    assert 'csvql query orders.csv "SELECT * FROM orders LIMIT 5"' in readme
    assert 'python -m pip install "localql[tui]"' in readme
    assert "Python 3.11 through 3.14" in readme
    assert "macOS, Linux, and Windows" in readme
    assert "trusted local DuckDB SQL" in readme
    for label in ("Support", "Security", "Changelog", "v1 release notes"):
        assert f"[{label}](" in readme


def test_getting_started_orders_the_core_query_before_the_optional_tui() -> None:
    getting_started = read_doc("docs/getting-started.md")

    install_index = getting_started.index("## Install LocalQL")
    query_index = getting_started.index("## Query a CSV")
    first_query_index = getting_started.index(
        'csvql query orders.csv "SELECT * FROM orders LIMIT 5"'
    )
    tui_install_index = getting_started.index('python -m pip install "localql[tui]"')
    terminal_menu_index = getting_started.index("## Use the optional terminal menu")

    assert install_index < query_index < first_query_index < terminal_menu_index < tui_install_index


def test_readme_links_are_safe_for_pypi_rendering() -> None:
    for target in LINK_RE.findall(read_doc("README.md")):
        assert target.startswith(("https://", "mailto:", "#")), target


def test_installed_user_docs_do_not_use_source_checkout_commands() -> None:
    for path in INSTALLED_USER_DOC_PATHS:
        assert "uv run" not in read_doc(path), path


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
