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
MARKDOWN_BLOCK_RE = re.compile(r"(?ms)^#{2,3} .+?(?=^#{2,3} |\Z)")
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


def markdown_blocks(document: str) -> tuple[str, ...]:
    return tuple(match.group(0).strip() for match in MARKDOWN_BLOCK_RE.finditer(document))


def markdown_block_containing(document: str, *markers: str) -> str:
    normalized_markers = tuple(" ".join(marker.casefold().split()) for marker in markers)
    matches = tuple(
        block
        for block in markdown_blocks(document)
        if all(marker in " ".join(block.casefold().split()) for marker in normalized_markers)
    )
    assert len(matches) == 1, (
        f"expected one Markdown block containing {markers!r}, found {len(matches)}"
    )
    return matches[0]


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


def test_roadmap_is_canonical_future_direction_not_shipped_behavior() -> None:
    roadmap = read_doc("docs/ROADMAP.md")
    authority = markdown_block_containing(
        roadmap,
        "canonical public source",
        "future product direction",
    )
    authority_text = " ".join(authority.casefold().split())

    for shipped_source in (
        "code",
        "tests",
        "user documentation",
        "changelog",
        "release notes",
    ):
        assert shipped_source in authority_text
    assert "roadmap status does not make a feature available" in authority_text
    assert "Install LocalQL, point it at a structured source, and query it with SQL." in roadmap

    point_and_query = markdown_block_containing(
        roadmap,
        "Point-and-Query",
        "planned product direction",
        "not shipped behavior",
    )
    point_and_query_text = " ".join(point_and_query.casefold().split())
    assert re.search(r"\bstatus\b.{0,20}\bplanned\b", point_and_query_text)


def test_roadmap_defines_complete_status_vocabulary() -> None:
    roadmap = read_doc("docs/ROADMAP.md")

    markdown_block_containing(
        roadmap,
        "Shipped",
        "Active",
        "Planned",
        "Candidate",
        "Deferred",
        "Superseded",
    )


def test_roadmap_preserves_milestone_statuses_dependencies_and_scope() -> None:
    roadmap = read_doc("docs/ROADMAP.md")
    v1_1 = markdown_block_containing(
        roadmap,
        "v1.1",
        "SourceSpec",
        "SourceAdapter",
        "bounded or streaming",
    )
    v1_2 = markdown_block_containing(roadmap, "v1.2", "Parquet", "JSON", "Excel")
    point_and_query = markdown_block_containing(
        roadmap,
        "Point-and-Query",
        "structured HTTP APIs",
        "bounded Arrow",
    )
    v2_0 = markdown_block_containing(
        roadmap,
        "v2.0",
        "Parquet",
        "PostgreSQL",
        "HTTP JSON API",
    )
    v2_x = markdown_block_containing(
        roadmap,
        "v2.x",
        "third-party connector SDK",
        "pushdown",
    )
    v1_1_text = " ".join(v1_1.casefold().split())
    v1_2_text = " ".join(v1_2.casefold().split())
    point_and_query_text = " ".join(point_and_query.casefold().split())
    v2_0_text = " ".join(v2_0.casefold().split())
    v2_x_text = " ".join(v2_x.casefold().split())

    assert roadmap.index(v1_1) < roadmap.index(v1_2)
    assert roadmap.index(v1_2) < roadmap.index(point_and_query)
    assert roadmap.index(point_and_query) < roadmap.index(v2_0)
    assert roadmap.index(v2_0) < roadmap.index(v2_x)
    assert re.search(r"\bstatus\b.{0,20}\bplanned\b", v1_1_text)
    assert "source" in v1_1_text
    assert "bounded" in v1_1_text
    assert re.search(r"\bstatus\b.{0,20}\bplanned\b", v1_2_text)
    assert "depends on v1.1" in v1_2_text
    assert re.search(r"\bstatus\b.{0,20}\bplanned\b", point_and_query_text)
    assert "not shipped behavior" in point_and_query_text
    assert re.search(r"\bstatus\b.{0,20}\bcandidate\b", v2_0_text)
    assert "depends on v1.1 and v1.2" in v2_0_text
    assert "read-only http json api" in v2_0_text
    assert "promotion" in v2_0_text
    assert "public roadmap status change" in v2_0_text
    assert "prerequisite" in v2_0_text
    assert re.search(r"\bstatus\b.{0,20}\b(candidate|deferred)\b", v2_x_text)
    assert "not shipped" in v2_x_text


def test_roadmap_preserves_point_and_query_safety_and_compatibility() -> None:
    roadmap = read_doc("docs/ROADMAP.md")
    safeguards = markdown_block_containing(
        roadmap,
        "credential references",
        "read-only",
        "threat model",
        "v1 catalogs",
    )
    safeguard_text = " ".join(safeguards.casefold().split())

    for marker in (
        "remain readable",
        "migration must be explicit",
        "previewable",
        "reversible",
        "literal secrets",
        "redacted",
        "enforced connector property",
        "connector-specific threat model",
        "ssrf",
        "schemes",
        "redirects",
        "private-network handling",
        "dns rebinding",
        "timeouts",
        "transfer limits",
        "safe retries",
        "cancellation",
        "cleanup",
        "exact implemented and verified connectors",
    ):
        assert marker in safeguard_text


def test_roadmap_requires_explicit_direction_disposition() -> None:
    roadmap = read_doc("docs/ROADMAP.md")
    boundaries = markdown_block_containing(
        roadmap,
        "natural-language SQL",
        "distributed query planner",
        "default mutation",
        "secret vault",
        "silent dependency installation",
        "universal connector support",
    )
    change_discipline = markdown_block_containing(
        roadmap,
        "Deferred",
        "Superseded",
        "replacement",
        "public product reason",
    )

    assert boundaries != change_discipline


def test_pull_request_template_collects_roadmap_impact() -> None:
    template = read_doc(".github/pull_request_template.md")
    roadmap_impact = markdown_block_containing(
        template,
        "docs/ROADMAP.md",
        "status",
        "direction",
        "deferred",
        "superseded",
        "public product reason",
    )
    roadmap_impact_text = " ".join(roadmap_impact.casefold().split())

    assert re.search(r"\b(if|when)\b", roadmap_impact_text)


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
