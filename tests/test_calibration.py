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


def test_the_record_covers_the_checks_the_change_requests_declare():
    by_id = {entry["change_request"]: entry for entry in RECORD["change_requests"]}
    for request in cr.load_all():
        entry = by_id[request.id]
        assert entry["acceptance"]["checks"] == [check.id for check in request.acceptance]
        assert {item["id"] for item in entry["invariants"]} == {
            invariant.id for invariant in request.must_invariants
        }


def test_no_pilot_change_request_needs_the_running_stack():
    """Module tests must verify without one; a stack requirement has to be declared."""
    for request in cr.load_all():
        assert request.needs_stack is False
    for entry in RECORD["change_requests"]:
        assert entry["needs_stack"] is False
