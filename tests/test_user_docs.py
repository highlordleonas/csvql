import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml

from csvql import CSVQLSession
from csvql.cli import app

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_BLOB_PREFIX = "https://github.com/highlordleonas/csvql/blob/main/"
REPO_RAW_PREFIX = "https://raw.githubusercontent.com/highlordleonas/csvql/main/"
REPO_RAW_URL = urlparse(REPO_RAW_PREFIX)
LINK_RE = re.compile(r"!?\[[^]]*\]\(([^)]+)\)")
HTTPS_TARGET_RE = re.compile(
    r"""https://[^\s<>()\[\]{}"'`]+""",
    flags=re.IGNORECASE,
)
HEADING_RE = re.compile(r"^#{1,6} +(.+?) *#* *$", flags=re.MULTILINE)
JSON_FENCE_RE = re.compile(r"```json\n(.*?)\n```", flags=re.DOTALL)
API_FACTORY_RE = re.compile(r"CSVQLSession\.(from_[a-z_]+)\(")
FENCE_OPEN_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
ALLOWED_HTTPS_HOSTS = {
    "github.com",
    "img.shields.io",
    "pypi.org",
    "raw.githubusercontent.com",
}
NON_LIVE_EXAMPLE_HOSTS = {"api.example.com"}
IMAGE_RE = re.compile(r"!\[([^]]*)\]\(([^)]+)\)")
IMAGE_START_RE = re.compile(r"!\[")
HTML_IMAGE_RE = re.compile(r"<img\b", flags=re.IGNORECASE)
EXPECTED_CLI_COMMANDS = {
    "add",
    "check",
    "doctor",
    "export",
    "init",
    "inspect",
    "menu",
    "profile",
    "query",
    "run",
    "sample",
    "tables",
}
CSVQL_COMMAND_RE = re.compile(r"(?:^|[\s;&|(){}`])csvql[ \t]+([a-z][a-z-]*)\b")
PUBLIC_PRODUCT_DOCS = {
    "CHANGELOG.md",
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/cli-reference.md",
    "docs/faq.md",
    "docs/getting-started.md",
    "docs/json-contracts.md",
    "docs/release-notes/v1.md",
    "docs/troubleshooting.md",
    "docs/tui-guide.md",
    "examples/saas_revenue/README.md",
}
CONTRIBUTOR_SUPPORT_DOCS = {
    ".github/pull_request_template.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "SUPPORT.md",
    "docs/development.md",
}
MAINTAINER_RELEASE_DOCS = {"docs/releasing.md"}
PRODUCT_DIRECTION_DOCS = {
    "docs/ROADMAP.md",
    "docs/v1.0.2-tui-spill-reliability-design.md",
    "docs/v2-point-and-query-design.md",
}
EXCLUDED_INTERNAL_DOCS = {
    "AGENTS.md",
    "docs/governance/audits/2026_07_12_project_stewardship_audit.md",
}


def tracked_markdown_paths() -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--", "*.md"],
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(sorted(completed.stdout.splitlines()))


def fenced_blocks(document: str, language: str) -> tuple[str, ...]:
    lines = document.splitlines()
    blocks: list[str] = []
    line_index = 0
    while line_index < len(lines):
        opening = FENCE_OPEN_RE.fullmatch(lines[line_index])
        if opening is None:
            line_index += 1
            continue

        fence = opening.group("fence")
        info = opening.group("info")
        if fence.startswith("`") and "`" in info:
            line_index += 1
            continue

        fence_width = len(fence)
        fence_character = re.escape(fence[0])
        closing_re = re.compile(rf"^ {{0,3}}{fence_character}{{{fence_width},}}[ \t]*$")
        content_start = line_index + 1
        closing_index = content_start
        while closing_index < len(lines) and closing_re.fullmatch(lines[closing_index]) is None:
            closing_index += 1

        info = info.strip()
        block_language = info.split(maxsplit=1)[0] if info else ""
        if block_language == language:
            blocks.append("\n".join(lines[content_start:closing_index]))
        line_index = closing_index + 1

    return tuple(blocks)


def assert_reviewed_https_targets(document: str, *, path: str) -> None:
    for target in https_targets(document):
        host = urlparse(target).hostname
        assert host in ALLOWED_HTTPS_HOSTS | NON_LIVE_EXAMPLE_HOSTS, (
            path,
            target,
        )


def repository_raw_asset(target: str) -> Path | None:
    parsed = urlparse(target)
    host = parsed.hostname.lower() if parsed.hostname is not None else None
    if (
        parsed.scheme.lower() != REPO_RAW_URL.scheme
        or host != REPO_RAW_URL.hostname
        or not parsed.path.startswith(REPO_RAW_URL.path)
    ):
        return None

    relative_path = parsed.path.removeprefix(REPO_RAW_URL.path)
    asset = (REPO_ROOT / relative_path).resolve()
    assert asset.is_relative_to(REPO_ROOT), (target, "asset path escapes repository")
    return asset


def assert_public_images_are_valid(document: str, *, path: str) -> None:
    html_image = HTML_IMAGE_RE.search(document)
    assert html_image is None, f"{path}: unsupported image syntax: HTML <img>"

    for image_start in IMAGE_START_RE.finditer(document):
        image = IMAGE_RE.match(document, image_start.start())
        assert image is not None, f"{path}: unsupported image syntax"
        alt_text, target = image.groups()
        assert alt_text.strip(), (path, target)
        asset = repository_raw_asset(target)
        if asset is None and "://" not in target:
            asset = (REPO_ROOT / path).parent / target.partition("#")[0]
        elif asset is None:
            continue
        assert asset.is_file(), (path, target)


def https_targets(document: str) -> tuple[str, ...]:
    return tuple(HTTPS_TARGET_RE.findall(document))


PUBLIC_RENDERED_DOCS = tuple(
    sorted(
        PUBLIC_PRODUCT_DOCS
        | CONTRIBUTOR_SUPPORT_DOCS
        | MAINTAINER_RELEASE_DOCS
        | PRODUCT_DIRECTION_DOCS
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


def test_every_tracked_markdown_file_has_one_publication_classification() -> None:
    tracked = set(tracked_markdown_paths())
    classified = (
        PUBLIC_PRODUCT_DOCS
        | CONTRIBUTOR_SUPPORT_DOCS
        | MAINTAINER_RELEASE_DOCS
        | PRODUCT_DIRECTION_DOCS
        | EXCLUDED_INTERNAL_DOCS
    )
    assert tracked == classified
    classes = (
        PUBLIC_PRODUCT_DOCS,
        CONTRIBUTOR_SUPPORT_DOCS,
        MAINTAINER_RELEASE_DOCS,
        PRODUCT_DIRECTION_DOCS,
        EXCLUDED_INTERNAL_DOCS,
    )
    assert all(
        left.isdisjoint(right)
        for index, left in enumerate(classes)
        for right in classes[index + 1 :]
    )
    assert not any(path.startswith("docs/superpowers/") for path in tracked)


def test_https_target_discovery_includes_nested_badges_and_bare_urls() -> None:
    document = (
        "[![CI](https://img.shields.io/x)]"
        "(https://github.com/highlordleonas/csvql)\n"
        "https://pypi.org/project/localql/\n"
    )

    assert https_targets(document) == (
        "https://img.shields.io/x",
        "https://github.com/highlordleonas/csvql",
        "https://pypi.org/project/localql/",
    )


def test_remote_domain_review_rejects_mixed_case_unreviewed_scheme() -> None:
    with pytest.raises(AssertionError, match=r"unreviewed\.example"):
        assert_reviewed_https_targets(
            "[x](HTTPS://unreviewed.example/path)",
            path="fixture.md",
        )


def test_fenced_blocks_support_commonmark_width_and_indentation() -> None:
    document = (
        "````bash\n"
        'echo "$(csvql nonexistent)"\n'
        "````\n"
        "   ```bash\n"
        "echo ready;csvql nonexistent\n"
        "   ```\n"
    )

    assert fenced_blocks(document, "bash") == (
        'echo "$(csvql nonexistent)"',
        "echo ready;csvql nonexistent",
    )


def test_csvql_command_discovery_supports_shell_control_boundaries() -> None:
    block = 'echo "$(csvql nonexistent)"\necho ready;csvql nonexistent'

    assert CSVQL_COMMAND_RE.findall(block) == ["nonexistent", "nonexistent"]


def test_fenced_blocks_support_tilde_fences() -> None:
    document = "~~~bash\necho ready\n~~~\n"

    assert fenced_blocks(document, "bash") == ("echo ready",)
    subprocess.run(
        ["bash", "-n", "-c", fenced_blocks(document, "bash")[0]],
        check=True,
        capture_output=True,
    )


def test_csvql_command_discovery_supports_legacy_backticks() -> None:
    block = 'echo "`csvql nonexistent`"'

    assert CSVQL_COMMAND_RE.findall(block) == ["nonexistent"]


def test_public_image_enforcement_rejects_reference_and_html_forms() -> None:
    unsupported_documents = (
        "![Reference alt][diagram]\n\n[diagram]: docs/assets/example.svg\n",
        '<img src="docs/assets/example.svg" alt="HTML alt">\n',
    )

    for document in unsupported_documents:
        with pytest.raises(AssertionError, match="unsupported image syntax"):
            assert_public_images_are_valid(document, path="fixture.md")


def test_public_image_enforcement_checks_mixed_case_raw_repo_targets() -> None:
    target = "HTTPS://raw.githubusercontent.com/highlordleonas/csvql/main/does-not-exist.png"

    with pytest.raises(AssertionError, match="does-not-exist"):
        assert_public_images_are_valid(f"![Alt text]({target})", path="fixture.md")


def test_public_documentation_remote_domains_are_reviewed() -> None:
    for path in PUBLIC_RENDERED_DOCS:
        assert_reviewed_https_targets(read_doc(path), path=path)


def test_public_documentation_images_have_alt_text_and_real_targets() -> None:
    for path in PUBLIC_RENDERED_DOCS:
        assert_public_images_are_valid(read_doc(path), path=path)


def test_issue_forms_cover_bug_docs_feature_and_private_security_routes() -> None:
    forms = {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted((REPO_ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml"))
    }
    assert {
        "bug_report.yml",
        "docs_issue.yml",
        "feature_request.yml",
        "config.yml",
    } <= forms.keys()
    config = forms["config.yml"]
    assert config["blank_issues_enabled"] is False
    assert any("SECURITY.md" in link["url"] for link in config["contact_links"])


def test_public_shell_examples_name_real_cli_commands() -> None:
    registered = {
        command.name or command.callback.__name__.replace("_", "-")
        for command in app.registered_commands
    }
    assert registered == EXPECTED_CLI_COMMANDS
    documented: set[str] = set()
    for path in PUBLIC_RENDERED_DOCS:
        document = read_doc(path)
        for language in ("bash", "console"):
            for block in fenced_blocks(document, language):
                documented.update(CSVQL_COMMAND_RE.findall(block))
    assert documented <= registered


def test_public_bash_fences_are_syntactically_valid() -> None:
    for path in PUBLIC_RENDERED_DOCS:
        for block in fenced_blocks(read_doc(path), "bash"):
            subprocess.run(
                ["bash", "-n", "-c", block],
                check=True,
                capture_output=True,
            )


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
    for path in PUBLIC_RENDERED_DOCS:
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
