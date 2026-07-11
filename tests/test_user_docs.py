import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LINK_RE = re.compile(r"!?\[[^]]*\]\(([^)]+)\)")
USER_DOC_PATHS = (
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "SUPPORT.md",
    "docs/getting-started.md",
    "docs/cli-reference.md",
    "docs/faq.md",
    "docs/troubleshooting.md",
    "docs/tui-guide.md",
    "docs/json-contracts.md",
    "docs/release-notes/v1.md",
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
        "[Contributing](CONTRIBUTING.md)",
        "[Security](SECURITY.md)",
        "[Support](SUPPORT.md)",
    ):
        assert expected_link in readme

    for internal_section in (
        "Maintainer-facing docs",
        "Benchmark And Release Hardening",
        "Development Checks",
    ):
        assert internal_section not in readme


def test_long_reference_docs_include_curated_navigation() -> None:
    for path in ("docs/cli-reference.md", "docs/json-contracts.md"):
        assert "## Contents" in read_doc(path)


def test_internal_process_material_is_not_tracked_as_public_documentation() -> None:
    for path in (
        "docs/PRODUCT_DIRECTION.md",
        "docs/benchmarking.md",
        "docs/failure-gallery.md",
        "docs/release-readiness.md",
        "docs/tui-qol-qa.md",
        "docs/v1-manual-qa.md",
    ):
        assert not (REPO_ROOT / path).exists(), path
    assert not (REPO_ROOT / "docs" / "superpowers").exists()


def test_user_docs_describe_the_product_without_release_proof_or_agent_language() -> None:
    user_docs = "\n".join(
        read_doc(path)
        for path in (
            "README.md",
            "CHANGELOG.md",
            "docs/getting-started.md",
            "docs/cli-reference.md",
            "docs/faq.md",
            "docs/troubleshooting.md",
            "docs/tui-guide.md",
            "docs/json-contracts.md",
            "docs/release-notes/v1.md",
        )
    )

    for internal_language in (
        "same-`HEAD`",
        "release-candidate eligible",
        "TUI QoL QA",
        "Codex Steering",
        "docs/superpowers",
    ):
        assert internal_language not in user_docs


def test_user_documentation_links_resolve() -> None:
    for path in USER_DOC_PATHS:
        document_path = REPO_ROOT / path
        for target in LINK_RE.findall(read_doc(path)):
            target_path = target.split("#", maxsplit=1)[0]
            if not target_path or "://" in target_path or target_path.startswith("mailto:"):
                continue
            assert (document_path.parent / target_path).is_file(), f"{path}: {target}"
