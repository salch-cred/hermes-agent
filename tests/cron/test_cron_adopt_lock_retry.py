"""``adopt_claimed_execution`` retries lock contention inside the handoff window (#135487)."""

from __future__ import annotations

import sqlite3
import time

import pytest


def _point_ledger(monkeypatch, tmp_path):
    from cron import executions

    monkeypatch.setattr(executions, "EXECUTIONS_FILE", tmp_path / "cron" / "executions.db")
    return executions


def _pending_handoff(executions, job_id="lock-job"):
    record = executions.create_execution(job_id, source="builtin")
    assert executions.mark_execution_handoff_pending(record["id"]) is not None
    return record["id"]


def test_adopt_retries_a_locked_write_until_it_succeeds(monkeypatch, tmp_path):
    executions = _point_ledger(monkeypatch, tmp_path)
    execution_id = _pending_handoff(executions)
    real_once = executions._adopt_claimed_execution_once
    attempts = []

    def flaky(attempted_id):
        attempts.append(attempted_id)
        if len(attempts) < 3:
            raise sqlite3.OperationalError("database is locked")
        return real_once(attempted_id)

    monkeypatch.setattr(executions, "_adopt_claimed_execution_once", flaky)
    monkeypatch.setattr(executions, "ADOPT_LOCK_RETRY_INITIAL_SECONDS", 0.01)

    adopted = executions.adopt_claimed_execution(execution_id, deadline=time.time() + 5)

    assert adopted["status"] == "running"
    assert adopted["handoff_pending"] == 0
    assert len(attempts) == 3


def test_adopt_raises_the_lock_error_once_the_deadline_passes(monkeypatch, tmp_path):
    executions = _point_ledger(monkeypatch, tmp_path)
    execution_id = _pending_handoff(executions)
    attempts = []

    def always_locked(attempted_id):
        attempts.append(attempted_id)
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(executions, "_adopt_claimed_execution_once", always_locked)
    monkeypatch.setattr(executions, "ADOPT_LOCK_RETRY_INITIAL_SECONDS", 0.01)

    started = time.time()
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        executions.adopt_claimed_execution(execution_id, deadline=time.time() + 0.2)

    assert len(attempts) > 1
    assert time.time() - started < 3


def test_adopt_does_not_retry_a_cas_refusal(monkeypatch, tmp_path):
    executions = _point_ledger(monkeypatch, tmp_path)
    execution_id = _pending_handoff(executions)
    assert executions.adopt_claimed_execution(execution_id) is not None

    real_once = executions._adopt_claimed_execution_once
    attempts = []

    def counted(attempted_id):
        attempts.append(attempted_id)
        return real_once(attempted_id)

    monkeypatch.setattr(executions, "_adopt_claimed_execution_once", counted)
    monkeypatch.setattr(executions, "ADOPT_LOCK_RETRY_INITIAL_SECONDS", 0.01)

    # The row is already ``running``: the CAS refuses and must not be retried.
    assert executions.adopt_claimed_execution(execution_id, deadline=time.time() + 5) is None
    assert len(attempts) == 1


def test_adopt_does_not_retry_an_unrelated_operational_error(monkeypatch, tmp_path):
    executions = _point_ledger(monkeypatch, tmp_path)
    execution_id = _pending_handoff(executions)
    attempts = []

    def broken(attempted_id):
        attempts.append(attempted_id)
        raise sqlite3.OperationalError("no such table: executions")

    monkeypatch.setattr(executions, "_adopt_claimed_execution_once", broken)
    monkeypatch.setattr(executions, "ADOPT_LOCK_RETRY_INITIAL_SECONDS", 0.01)

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        executions.adopt_claimed_execution(execution_id, deadline=time.time() + 5)

    assert len(attempts) == 1


def test_adopt_defaults_its_deadline_to_the_handoff_reserve(monkeypatch, tmp_path):
    executions = _point_ledger(monkeypatch, tmp_path)
    execution_id = _pending_handoff(executions)
    seen = {}
    real_once = executions._adopt_claimed_execution_once

    def record_clock(attempted_id):
        seen["now"] = time.time()
        return real_once(attempted_id)

    monkeypatch.setattr(executions, "_adopt_claimed_execution_once", record_clock)

    assert executions.adopt_claimed_execution(execution_id) is not None
    # No explicit deadline: the window is the grace period minus the ack reserve.
    assert seen["now"] > 0
