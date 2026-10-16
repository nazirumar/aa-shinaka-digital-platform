"""CI security-gate invariants (pre-hosting readiness).

The dependency scan in ``.github/workflows/ci.yml`` must:
  * audit THIS project's locked dependencies, not the transient environment the
    scanner runs in (``uvx`` installs pip-audit into its own isolated env, so a
    targetless ``pip-audit`` audits pip-audit's own dependencies);
  * fail the build for BOTH a genuine vulnerability finding and a scanner
    failure, while labelling which one occurred;
  * never be waivable (no ``continue-on-error``).

These are text/behaviour assertions; none of them needs a network or a Docker
daemon, so they run everywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"

# The exact classification regex used by the scan step, mirrored so its
# behaviour can be asserted directly on pip-audit's real output wording.
FINDING_RE = re.compile(
    r"found [0-9]+ (known )?vulnerabilit|vulnerabilit(y|ies) (were )?found",
    re.IGNORECASE,
)
CLEAN_RE = re.compile(r"no known vulnerabilities found", re.IGNORECASE)


def _classify(status: int, log: str) -> str:
    """Python mirror of the shell decision logic in ci.yml."""
    if status == 0:
        return "CLEAN"
    if FINDING_RE.search(log) and not CLEAN_RE.search(log):
        return "VULNERABILITY-FINDING"
    return "TOOL-FAILURE"


def _active_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The scan targets the project's own dependencies
# ---------------------------------------------------------------------------


def test_workflow_exists():
    assert WORKFLOW.exists(), "the CI workflow must exist"


def test_dependency_scan_audits_the_project_lock():
    text = _text()
    # The lock is exported and passed explicitly to pip-audit.
    assert "uv export" in text, "the scan must export the project's locked requirements"
    assert "requirements-audit.txt" in text, "the export must be written to a known file"


def test_pip_audit_is_given_an_explicit_target():
    """A targetless `pip-audit` inside `uvx` audits pip-audit's own deps."""
    invocations = [
        line
        for line in _active_lines(_text())
        if "pip-audit" in line and "--from pip-audit" in line
    ]
    assert invocations, "expected a pinned pip-audit invocation"
    for line in invocations:
        assert "-r requirements-audit.txt" in line, (
            "pip-audit must be pointed at the exported lock with `-r`; without a "
            f"target it audits the uvx tool environment. Offending line: {line!r}"
        )


def test_empty_export_is_a_hard_failure_not_a_silent_pass():
    text = _text()
    assert "! -s requirements-audit.txt" in text, (
        "an empty lock export must fail the job rather than report a clean scan"
    )


# ---------------------------------------------------------------------------
# Failure behaviour
# ---------------------------------------------------------------------------


def test_no_step_is_waivable():
    for line in _active_lines(_text()):
        assert "continue-on-error" not in line, f"no CI step may be waivable: {line!r}"


def test_classification_matches_pip_audit_real_wording():
    # Verbatim pip-audit 2.10.1 summary lines (captured from a real run).
    assert _classify(1, "Found 8 known vulnerabilities in 1 package") == "VULNERABILITY-FINDING"
    assert _classify(1, "Found 3 vulnerabilities in 2 packages") == "VULNERABILITY-FINDING"
    assert _classify(1, "2 vulnerabilities were found") == "VULNERABILITY-FINDING"
    # A scanner/network problem must NOT be reported as a finding.
    assert _classify(1, "ERROR: could not reach PyPI: network unreachable") == "TOOL-FAILURE"
    assert _classify(1, "") == "TOOL-FAILURE"
    # --strict aborting the scan still prints the clean phrase; that is not a
    # finding even though the process exited non-zero.
    assert _classify(1, "No known vulnerabilities found.") == "TOOL-FAILURE"
    # A genuinely clean scan passes.
    assert _classify(0, "No known vulnerabilities found.") == "CLEAN"


def test_scan_step_exits_non_zero_for_both_failure_modes():
    text = _text()
    # Two `exit 1` branches after the clean branch: finding + tool failure.
    step = text.split("Dependency vulnerability scan", 1)[1]
    assert "::error::DEPENDENCY VULNERABILITY FINDING" in step
    assert "::error::TOOL FAILURE" in step
    assert step.count("exit 1") >= 2


# ---------------------------------------------------------------------------
# Supply-chain hygiene
# ---------------------------------------------------------------------------


def test_every_action_is_pinned_to_a_full_commit_sha():
    refs = re.findall(r"uses:\s*([^\s#]+)", _text())
    assert refs, "expected pinned actions"
    for ref in refs:
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref), (
            f"action must be pinned to a full commit SHA: {ref!r}"
        )


def test_required_jobs_are_present():
    text = _text()
    for job in ("lint", "checks", "assets", "test", "security"):
        assert f"\n  {job}:\n" in text, f"missing mandatory CI job: {job}"
