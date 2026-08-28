"""Tests for the calibration record.

Calibration is what stops a hidden check that passes before the change from
crediting every arm with a success. The record is checked here against the
change-request set and the pin it was taken on, so it cannot quietly go stale.
"""

import json
from pathlib import Path

from pipelines.common import changerequests as cr
from pipelines.common import locks

REPO = Path(__file__).resolve().parents[1]
RECORD = json.loads((REPO / "bench" / "calibration.json").read_text())


def test_every_change_request_is_calibrated():
    calibrated = {
        entry["change_request"] for entry in RECORD["change_requests"] if entry["calibrated"]
    }
    assert calibrated == {request.id for request in cr.load_all()}


def test_the_record_was_taken_on_the_current_pin():
    assert RECORD["commit"] == locks.target()["target"]["commit"]


def test_no_hidden_check_passes_before_the_change():
    """A check that is green on the unmodified pin cannot discriminate."""
    for entry in RECORD["change_requests"]:
        assert entry["acceptance"]["status"] == "fail", entry["change_request"]
        assert entry["acceptance"]["compiled"], (
            f"{entry['change_request']}: the hidden checks are red because they do not "
            f"compile, which is the wrong reason"
        )


def test_every_invariant_holds_before_the_change():
    for entry in RECORD["change_requests"]:
        for invariant in entry["invariants"]:
            assert invariant["status"] == "pass", f"{entry['change_request']} {invariant['id']}"


def test_the_module_suite_is_green_before_the_change():
    for entry in RECORD["change_requests"]:
        assert entry["module_suite"] == "pass", entry["change_request"]


def test_every_module_a_request_names_was_calibrated():
    """A cross-service change is only calibrated if both sides were."""
    from pipelines.common import locks as locks_module

    by_id = {entry["change_request"]: entry for entry in RECORD["change_requests"]}
    for request in cr.load_all():
        entry = by_id[request.id]
        assert entry["modules"] == list(request.module_paths), request.id
        for module_path in request.module_paths:
            assert entry["module_suites"][module_path] == "pass", f"{request.id} {module_path}"
        assert locks_module.module_path(request.modules[0]) == entry["modules"][0]


def test_the_record_covers_the_checks_the_change_requests_declare():
    by_id = {entry["change_request"]: entry for entry in RECORD["change_requests"]}
    for request in cr.load_all():
        entry = by_id[request.id]
        assert entry["acceptance"]["checks"] == [check.id for check in request.acceptance]
        assert {item["id"] for item in entry["invariants"]} == {
            invariant.id for invariant in request.must_invariants
        }


def test_nothing_is_verified_against_a_stack_that_boots_the_pin():
    """The stack runner starts the pinned checkout, not a run's workspace.

    A change request that declared `needs_stack: true` today would be verified
    against the unmodified application and credited with a success it did not
    earn. Until infra/stack.py can boot a workspace --- see
    bench/VERIFICATION.md --- nothing in the set may declare it, and what
    calibration recorded must agree with what the request declares.
    """
    declared = {request.id: request.needs_stack for request in cr.load_all()}
    assert not any(declared.values()), [k for k, v in declared.items() if v]
    for entry in RECORD["change_requests"]:
        assert entry["needs_stack"] == declared[entry["change_request"]]


def test_the_record_is_the_shape_the_calibrator_writes_now():
    assert RECORD["schema_version"] == 2
