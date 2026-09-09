from __future__ import annotations

from pathlib import Path


def _section(document: str, start: str, end: str) -> str:
    section_start = document.index(start)
    section_end = document.index(end, section_start + len(start))
    return document[section_start:section_end]


def _table_after_heading(document: str, heading: str) -> str:
    heading_start = document.index(heading)
    table_start = document.index("\n|", heading_start)
    rows: list[str] = []
    for line in document[table_start:].splitlines():
        if line.startswith("|"):
            rows.append(line)
        elif rows:
            break
    return "\n".join(rows)


def test_future_requirement_baseline_is_characterized_in_individual_sections() -> None:
    # Given: the pre-MVP future SaaS requirements in the checked-in specification.
    specification = Path("system_spec.md").read_text(encoding="utf-8")

    # When: their current authorities are characterized before an MVP amendment.
    future_contracts = (
        (
            "## FR-016: Embeddable Shadow-DOM Chat Widget",
            "## FR-017: Stripe Test-Mode Billing and Account Entitlements",
            "workspace owner or admin",
        ),
        (
            "## FR-017: Stripe Test-Mode Billing and Account Entitlements",
            "## FR-018: RAG-Studio Landing Page, Pricing, and Conversion Flow",
            "Account Owner",
        ),
        (
            "## FR-023: Personal Lab Parity and Explicit Promotion to Shared Work",
            "## FR-024: Workspace Lifecycle, Membership Roles, and Account-Level Limits",
            "signed-in individual user",
        ),
        (
            "## FR-029: Account Billing Placeholder and Local Entitlement Foundation",
            "## FR-030: Usage, Audit Events, and Operational Observability Foundation",
            "Account Owner",
        ),
    )

    # Then: each authority exists only within its corresponding future requirement section.
    for start, end, authority in future_contracts:
        assert authority in _section(specification, start, end)


def test_mvp_requirement_has_gherkin_controls_in_each_acceptance_criterion_section() -> (
    None
):
    # Given: FR-MVP-001 is the dedicated requirement authority.
    specification = Path("system_spec.md").read_text(encoding="utf-8")
    mvp_requirement = _section(
        specification,
        "## FR-MVP-001: Personal Lab Billing and Single Public Widget",
        "## FR-016: Embeddable Shadow-DOM Chat Widget",
    )
    acceptance_criteria = (
        (
            "#### AC-MVP-001.1: Preserve React Personal Lab and forbid Legacy authority",
            "#### AC-MVP-001.2: One Stripe test-mode entitlement is webhook-authoritative",
            "Legacy import, mutation, migration, exposure, or retrieval is forbidden",
        ),
        (
            "#### AC-MVP-001.2: One Stripe test-mode entitlement is webhook-authoritative",
            "#### AC-MVP-001.3: One published Personal Lab widget is fail-closed",
            "only after signature verification and idempotent",
        ),
        (
            "#### AC-MVP-001.3: One published Personal Lab widget is fail-closed",
            "### Future-contract deferment and relationship matrix",
            "before graph or retrieval execution",
        ),
    )

    # When: each named acceptance criterion section is inspected independently.
    scoped_acceptance_criteria = [
        _section(mvp_requirement, start, end) for start, end, _ in acceptance_criteria
    ]

    # Then: every criterion has its own Given/When/Then and declared authority boundary.
    for section, (_, _, required_control) in zip(
        scoped_acceptance_criteria,
        acceptance_criteria,
        strict=True,
    ):
        assert "**Given**" in section
        assert "**When**" in section
        assert "**Then**" in section
        assert required_control in section


def test_every_owned_document_has_a_deferment_matrix_with_explicit_semantics() -> None:
    # Given: every owned document must preserve the future-contract boundary locally.
    project_root = Path(__file__).parents[1]
    document_matrices = (
        (
            project_root / "system_spec.md",
            "### Future-contract deferment and relationship matrix",
        ),
        (project_root / "CONTEXT.md", "### Future-contract deferment matrix"),
        (
            project_root
            / "docs"
            / "adr"
            / "0005-mvp-v1-personal-lab-billing-widget.md",
            "## Future-contract relationship matrix",
        ),
        (
            project_root
            / "docs"
            / "features"
            / "mvp-v1-personal-lab-billing-widget.md",
            "### Future-contract deferment matrix",
        ),
    )
    deferred_semantics = {
        "FR-016": "Workspace owner/admin authority",
        "FR-017": "three-plan catalogue",
        "FR-023": "AC-023.2 Agent promotion",
        "FR-029": "Account billing placeholder",
    }

    # When: the explicitly named deferment table is extracted from each document.
    matrices = [
        _table_after_heading(path.read_text(encoding="utf-8"), heading)
        for path, heading in document_matrices
    ]

    # Then: every matrix has all four rows and a concrete deferred behavior for each one.
    for matrix in matrices:
        assert "deferred" in matrix.lower()
        for requirement_id, deferred_behavior in deferred_semantics.items():
            row = next(
                line
                for line in matrix.splitlines()
                if line.startswith(f"| {requirement_id} |")
            )
            assert deferred_behavior in row


def test_stage3_compose_forwards_publication_rollback_flag() -> None:
    # Given: publication is independently feature-gated in the FastAPI runtime.
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    # When: the Stage3 app service is configured by Compose.
    # Then: the explicit flag reaches the container and still defaults fail-closed.
    assert (
        "RAG_STUDIO_PUBLICATION_ENABLED: "
        "${RAG_STUDIO_PUBLICATION_ENABLED:-false}" in compose
    )
