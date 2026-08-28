"""Tests for the headless executor wrapper.

Every test here runs a stand-in executor: a small script that emits the same
event stream the real one does. The wrapper's job — parsing what was spent,
enforcing the budgets, classifying failures, keeping the credential out of the
artifacts — is testable without spending anything, and is tested that way.
"""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from pipelines.common import executor, locks
from pipelines.common.executor import Budget, ExecutorUnavailable

SECRET = "not-a-real-key-0123456789"


@pytest.fixture
def dotenv(tmp_path) -> Path:
    variable = locks.executor()["credentials"]["variable"]
    path = tmp_path / "dotenv"
    path.write_text(f"# a comment\n\n{variable}={SECRET}\n")
    return path


@pytest.fixture
def workspace(tmp_path) -> Path:
    path = tmp_path / "workspace"
    path.mkdir()
    (path / "pom.xml").write_text("<project/>\n")
    return path


def stand_in(tmp_path: Path, body: str) -> Path:
    """A script that behaves like the executor for the length of one run."""
    path = tmp_path / "stand-in-executor.py"
    path.write_text("import json, os, sys, time\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def emit(*events: dict) -> str:
    lines = "\n".join(json.dumps(event) for event in events)
    return f"print({lines!r})\n"


def result_event(**overrides) -> dict:
    event = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 3,
        "duration_ms": 4200,
        "duration_api_ms": 3900,
        "total_cost_usd": 0.42,
        "stop_reason": "end_turn",
        "terminal_reason": "completed",
        "permission_denials": [],
        "session_id": "session-1",
        "result": "done",
        "usage": {
            "input_tokens": 1500,
            "output_tokens": 700,
            "output_tokens_details": {"thinking_tokens": 250},
            "cache_creation_input_tokens": 300,
            "cache_read_input_tokens": 900,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 200,
                "ephemeral_1h_input_tokens": 100,
            },
            "iterations": [{"type": "message"}, {"type": "message"}],
        },
    }
    event.update(overrides)
    return event


def assistant(identifier: str, *tools: str) -> dict:
    return {
        "type": "assistant",
        "session_id": "session-1",
        "message": {
            "id": identifier,
            "content": [{"type": "tool_use", "name": name} for name in tools],
        },
    }


def run(script: Path, workspace: Path, tmp_path: Path, dotenv: Path, budget=None):
    return executor.execute(
        "a prompt",
        workspace,
        tmp_path / "cell",
        budget=budget or Budget(max_turns=10, wall_clock_seconds=30, max_cost_usd=1.0),
        dotenv=dotenv,
        command=[sys.executable, str(script)],
    )


# --- the happy path --------------------------------------------------------


def test_a_completed_run_is_parsed_into_what_it_spent(tmp_path, workspace, dotenv):
    script = stand_in(
        tmp_path,
        emit(
            {"type": "system", "subtype": "init", "session_id": "session-1"},
            assistant("m1", "Read", "Bash"),
            assistant("m2", "Edit"),
            result_event(),
        ),
    )
    execution = run(script, workspace, tmp_path, dotenv)

    assert execution.status == "completed"
    assert execution.error_class is None
    assert execution.usage.input_tokens == 1500
    assert execution.usage.output_tokens == 700
    assert execution.usage.reasoning_tokens == 250
    assert execution.usage.cache_creation_5m_tokens == 200
    assert execution.usage.cache_creation_1h_tokens == 100
    assert execution.usage.api_calls == 2
    assert execution.turns == 3, "the executor's own turn count wins when it reports one"
    assert execution.tool_calls == {
        "total": 3,
        "by_name": {"Read": 1, "Bash": 1, "Edit": 1},
    }
    assert execution.api_time_seconds == 3.9
    assert execution.executor_reported_cost_usd == 0.42
    assert execution.response["session_id"] == "session-1"


def test_the_transcript_is_written_as_it_arrives(tmp_path, workspace, dotenv):
    script = stand_in(tmp_path, emit(assistant("m1"), result_event()))
    run(script, workspace, tmp_path, dotenv)
    transcript = (tmp_path / "cell" / "transcript.jsonl").read_text().splitlines()
    assert len(transcript) == 2
    assert json.loads(transcript[-1])["type"] == "result"


# --- budgets ---------------------------------------------------------------


def test_the_turn_cap_stops_the_run(tmp_path, workspace, dotenv):
    script = stand_in(
        tmp_path,
        "for i in range(50):\n"
        "    print(json.dumps({'type': 'assistant', 'message': {'id': f'm{i}', 'content': []}}))\n"
        "    sys.stdout.flush()\n"
        "    time.sleep(0.02)\n"
        "print(json.dumps({'type': 'result', 'subtype': 'success'}))\n",
    )
    execution = run(
        script,
        workspace,
        tmp_path,
        dotenv,
        budget=Budget(max_turns=3, wall_clock_seconds=30, max_cost_usd=1.0),
    )
    assert execution.status == "budget_exhausted"
    assert execution.error_class == "turn_budget"
    assert "3 turns" in execution.error_detail


def test_the_wall_clock_stops_the_run(tmp_path, workspace, dotenv):
    script = stand_in(tmp_path, "time.sleep(30)\n")
    execution = run(
        script,
        workspace,
        tmp_path,
        dotenv,
        budget=Budget(max_turns=10, wall_clock_seconds=1, max_cost_usd=1.0),
    )
    assert execution.status == "aborted"
    assert execution.error_class == "timeout"
    assert execution.wall_time_seconds < 20


def test_the_cost_ceiling_is_handed_to_the_executor():
    budget = Budget(max_turns=5, wall_clock_seconds=60, max_cost_usd=1.5)
    command = executor.build_command("prompt", "a-model", budget, locks.executor()["invocation"])
    assert command[command.index("--max-budget-usd") + 1] == "1.5"
    assert command[command.index("--model") + 1] == "a-model"
    assert command[command.index("--permission-mode") + 1] == "bypassPermissions"


def test_the_command_carries_the_pinned_tool_set():
    command = executor.build_command(
        "prompt", "a-model", Budget(1, 1, 1), locks.executor()["invocation"]
    )
    tools = command[command.index("--tools") + 1].split(",")
    assert tools == locks.executor()["invocation"]["tools"]
    assert command[command.index("--setting-sources") + 1] == ""


# --- failure classes -------------------------------------------------------


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ("API Error: 429 rate_limit_error", "rate_limit"),
        ("Your credit balance is too low", "credit_exhausted"),
        ("API Error: 529 overloaded_error", "overloaded"),
        ("401 invalid x-api-key", "auth"),
        ("fetch failed ECONNRESET", "network"),
    ],
)
def test_an_api_failure_aborts_the_cell_with_its_class(
    tmp_path, workspace, dotenv, reported, expected
):
    script = stand_in(
        tmp_path,
        emit(result_event(is_error=True, subtype="error_during_execution", result=reported)),
    )
    execution = run(script, workspace, tmp_path, dotenv)
    assert execution.status == "aborted"
    assert execution.error_class == expected
    assert execution.error_class not in {None, "unknown"}


def test_an_api_failure_reported_only_on_standard_error_is_still_classified(
    tmp_path, workspace, dotenv
):
    script = stand_in(
        tmp_path,
        emit(result_event()) + "print('Error: your credit balance is too low', file=sys.stderr)\n",
    )
    execution = run(script, workspace, tmp_path, dotenv)
    assert (execution.status, execution.error_class) == ("aborted", "credit_exhausted")


def test_an_agent_failure_is_not_an_abort(tmp_path, workspace, dotenv):
    script = stand_in(
        tmp_path,
        emit(result_event(is_error=True, result="the agent could not complete the task")),
    )
    execution = run(script, workspace, tmp_path, dotenv)
    assert execution.status == "agent_failed"
    assert execution.error_class is None


def test_an_executor_that_produces_no_result_is_an_abort(tmp_path, workspace, dotenv):
    script = stand_in(tmp_path, emit(assistant("m1")) + "sys.exit(3)\n")
    execution = run(script, workspace, tmp_path, dotenv)
    assert execution.status == "aborted"
    assert execution.error_class == "executor_crash"
    assert execution.exit_code == 3


def test_unparsable_output_does_not_crash_the_wrapper(tmp_path, workspace, dotenv):
    script = stand_in(tmp_path, "print('not json at all')\n" + emit(result_event()))
    execution = run(script, workspace, tmp_path, dotenv)
    assert execution.status == "completed"


# --- the credential --------------------------------------------------------


def test_the_credential_reaches_the_executor_and_nothing_else(tmp_path, workspace, dotenv):
    variable = locks.executor()["credentials"]["variable"]
    script = stand_in(
        tmp_path,
        f"print(json.dumps({{'type': 'system', 'subtype': 'init',"
        f" 'key_seen': os.environ.get({variable!r}, 'absent')}}))\n" + emit(result_event()),
    )
    run(script, workspace, tmp_path, dotenv)
    first = json.loads((tmp_path / "cell" / "transcript.jsonl").read_text().splitlines()[0])
    assert first["key_seen"] == executor.REDACTION, "the executor got the key; the log did not"


def test_a_credential_echoed_by_the_agent_is_scrubbed_from_the_artifacts(
    tmp_path, workspace, dotenv
):
    """The agent has a shell, so the guarantee has to hold over what it prints."""
    script = stand_in(
        tmp_path,
        f"print(json.dumps({{'type': 'assistant', 'message': {{'id': 'm1',"
        f" 'content': [{{'type': 'text', 'text': 'the key is ' + {SECRET!r}}}]}}}}))\n"
        + emit(result_event())
        + f"print('and on standard error: ' + {SECRET!r}, file=sys.stderr)\n",
    )
    run(script, workspace, tmp_path, dotenv)
    transcript = (tmp_path / "cell" / "transcript.jsonl").read_text()
    stderr = (tmp_path / "cell" / "stderr.txt").read_text()
    assert SECRET not in transcript and SECRET not in stderr
    assert executor.REDACTION in transcript and executor.REDACTION in stderr


def test_the_dotenv_is_never_placed_in_the_workspace(tmp_path, workspace, dotenv):
    script = stand_in(tmp_path, emit(result_event()))
    run(script, workspace, tmp_path, dotenv)
    assert sorted(path.name for path in workspace.iterdir()) == ["pom.xml"]


def test_the_run_gets_a_home_of_its_own(tmp_path, workspace, dotenv):
    script = stand_in(
        tmp_path,
        "print(json.dumps({'type': 'system', 'subtype': 'init', 'home': os.environ['HOME']}))\n"
        + emit(result_event()),
    )
    run(script, workspace, tmp_path, dotenv)
    first = json.loads((tmp_path / "cell" / "transcript.jsonl").read_text().splitlines()[0])
    assert first["home"] == str(tmp_path / "cell" / "home")
    assert first["home"] != os.environ.get("HOME")


def test_a_missing_credential_is_reported_before_anything_runs(tmp_path, monkeypatch):
    variable = locks.executor()["credentials"]["variable"]
    monkeypatch.delenv(variable, raising=False)
    with pytest.raises(ExecutorUnavailable, match="no credential"):
        executor.credential(tmp_path / "absent-dotenv")


def test_dotenv_parsing_handles_comments_blanks_and_quotes(tmp_path):
    path = tmp_path / "dotenv"
    path.write_text("# comment\n\nA=1\nB=\"two\"\nC='three'\nD = spaced \nnot-a-pair\n")
    assert executor.read_dotenv(path) == {"A": "1", "B": "two", "C": "three", "D": "spaced"}


def test_the_pinned_command_names_the_executor_from_the_lock():
    command = executor.build_command(
        "prompt", "a-model", Budget(1, 1, 1), locks.executor()["invocation"]
    )
    assert command[0] == locks.executor()["cli"]["binary"]
