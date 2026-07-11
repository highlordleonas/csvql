import json
import re
from pathlib import Path

from csvql import CSVQLSession

REPO_ROOT = Path(__file__).resolve().parents[1]
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


def test_readme_is_a_curated_user_starting_point() -> None:
    readme = read_doc("README.md")

    assert "## Contents" in readme
    for expected_link in (
        "[Getting started](docs/getting-started.md)",
        "[CLI reference](docs/cli-reference.md)",
        "[Troubleshooting](docs/troubleshooting.md)",
        "[Terminal menu guide](docs/tui-guide.md)",
        "[Roadmap](docs/ROADMAP.md)",
        "[Contributing](CONTRIBUTING.md)",
        "[Security](SECURITY.md)",
        "[Support](SUPPORT.md)",
    ):
        assert expected_link in readme


def test_long_reference_docs_include_curated_navigation() -> None:
    for path in ("docs/cli-reference.md", "docs/json-contracts.md"):
        assert "## Contents" in read_doc(path)


def test_user_documentation_links_resolve() -> None:
    for path in USER_DOC_PATHS:
        document_path = REPO_ROOT / path
        for target in LINK_RE.findall(read_doc(path)):
            if "://" in target or target.startswith("mailto:"):
                continue
            target_path, separator, fragment = target.partition("#")
            target_document = document_path.parent / target_path if target_path else document_path
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
