"""Tests for the review-time study.

The study's whole value rests on the reviewer not knowing which arm produced a
change. That is asserted here rather than trusted, along with the timing rules
that stop a wall clock from measuring lunch.
"""

import json

import pytest

from eval import review
from pipelines.common.telemetry import RunRecord, Usage
from pipelines.common.workspace import ARTIFACT_DIRECTORY

SOURCE = "spring-petclinic-visits-service/src/main/java/Visit.java"

PATCH = "".join(
    [
        f"diff --git a/{ARTIFACT_DIRECTORY}/intent-graph.json ",
        f"b/{ARTIFACT_DIRECTORY}/intent-graph.json\n",
        "new file mode 100644\n",
        "--- /dev/null\n",
        f"+++ b/{ARTIFACT_DIRECTORY}/intent-graph.json\n",
        "@@ -0,0 +1 @@\n",
        '+{"kind": "intent_graph"}\n',
        f"diff --git a/{SOURCE} b/{SOURCE}\n",
        f"--- a/{SOURCE}\n",
        f"+++ b/{SOURCE}\n",
        "@@ -1 +1 @@\n",
        "-old\n",
        "+new\n",
    ]
)


def a_cell(runs, change_request, arm, seed, patch=PATCH):
    record = RunRecord(
        run_id=f"{change_request}__{arm}__seed{seed}",
        change_request=change_request,
        arm=arm,
        seed=seed,
        status="completed",
        usage=Usage(),
        cost_usd=0.2,
    )
    directory = runs / record.run_id
    record.write(directory)
    (directory / "diff.patch").write_text(patch)
    return record


@pytest.fixture
def sampled(tmp_path):
    runs = tmp_path / "runs"
    out = tmp_path / "review"
    for arm in ("baseline", "lcir", "lcir_no_ast", "compressed"):
        for seed in (1, 2):
            a_cell(runs, "CR-101", arm, seed)
    review.sample(runs, out, seed=1)
    return out


def test_the_arms_own_artifacts_are_cut_out_of_the_diff(tmp_path):
    patch = tmp_path / "diff.patch"
    patch.write_text(PATCH)
    kept = review.application_diff(patch)
    assert ARTIFACT_DIRECTORY not in kept
    assert "Visit.java" in kept


def test_nothing_in_the_packet_names_an_arm(sampled):
    assert review.verify(sampled) == []


def test_a_leak_is_caught(sampled):
    item = next(iter((sampled / review.PACKET_NAME).iterdir()))
    (item / "request.md").write_text("produced by the lcir arm\n")
    assert review.verify(sampled)


def test_one_cell_per_change_request_and_arm_at_the_lowest_seed(sampled):
    key = json.loads((sampled / review.KEY_NAME).read_text())
    assert len(key["items"]) == 4
    assert {entry["arm"] for entry in key["items"]} == {
        "baseline",
        "lcir",
        "lcir_no_ast",
        "compressed",
    }
    assert {entry["seed"] for entry in key["items"]} == {1}


def test_the_key_is_not_inside_the_packet(sampled):
    assert not (sampled / review.PACKET_NAME / review.KEY_NAME).exists()


def test_only_one_item_may_be_open_at_a_time(sampled):
    items = [
        entry["item"] for entry in json.loads((sampled / review.KEY_NAME).read_text())["items"]
    ]
    review.start(sampled, items[0])
    with pytest.raises(review.ReviewError, match="still open"):
        review.start(sampled, items[1])


def test_an_item_is_not_reviewed_twice(sampled):
    items = [
        entry["item"] for entry in json.loads((sampled / review.KEY_NAME).read_text())["items"]
    ]
    review.start(sampled, items[0])
    review.finish(sampled, items[0], "stop")
    with pytest.raises(review.ReviewError, match="already been reviewed"):
        review.start(sampled, items[0])


def test_an_unknown_item_is_refused(sampled):
    with pytest.raises(review.ReviewError, match="not in the packet"):
        review.start(sampled, "not-an-item")


def test_an_item_over_the_ceiling_is_abandoned_rather_than_timed(sampled, monkeypatch):
    items = [
        entry["item"] for entry in json.loads((sampled / review.KEY_NAME).read_text())["items"]
    ]
    review.start(sampled, items[0])
    entries = review.read_timings(sampled)
    entries[-1]["at"] -= (review.CEILING_MINUTES + 1) * 60
    (sampled / review.TIMINGS_NAME).write_text(
        "\n".join(json.dumps(entry, sort_keys=True) for entry in entries) + "\n"
    )
    review.finish(sampled, items[0], "stop")
    assert review.read_timings(sampled)[-1]["event"] == "abandon"
    assert review.ingest(sampled)["abandoned"]


def test_ingest_reports_a_median_per_arm_and_no_zero_where_nothing_was_measured(sampled):
    key = json.loads((sampled / review.KEY_NAME).read_text())
    timed = next(entry for entry in key["items"] if entry["arm"] == "baseline")
    review.start(sampled, timed["item"])
    review.finish(sampled, timed["item"], "stop")

    payload = review.ingest(sampled)
    assert payload["arms"]["baseline"]["items_reviewed"] == 1
    assert payload["arms"]["baseline"]["median_minutes"] is not None
    # An arm nobody reviewed has no figure — never a zero, which would read as
    # "took no time at all".
    assert payload["arms"]["lcir"]["median_minutes"] is None


def test_only_measured_arms_reach_the_evaluation(sampled, tmp_path):
    payload = {
        "arms": {
            "baseline": {"median_minutes": 4.0, "items_reviewed": 1},
            "lcir": {"median_minutes": None, "items_reviewed": 0},
        }
    }
    path = tmp_path / "review-times.json"
    path.write_text(json.dumps(payload))
    assert review.human_minutes_by_arm(path) == {"baseline": 4.0}
    assert review.human_minutes_by_arm(tmp_path / "absent.json") == {}
