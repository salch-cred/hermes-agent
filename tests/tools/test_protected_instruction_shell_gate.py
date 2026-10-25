"""Terminal and execute_code must not slip past the protected-instruction-file gate.

The gate only had ``write_file``/``patch`` call sites, so one shell line
(``: > AGENTS.md``, ``sed -i … SOUL.md``, ``cp notes.md AGENTS.md``) or one
``execute_code`` cell rewrote the files that steer every later turn, with no
approval at all (#143266).
"""

import json
import os

import pytest

import tools.file_tools_write_guards as guards


@pytest.fixture(autouse=True)
def _gate_on(monkeypatch):
    from tools.terminal_tool import set_approval_callback
    monkeypatch.setattr(guards, "_protected_instruction_config", lambda: (True, []))
    for name in ("HERMES_SINGLE_QUERY_SESSION", "HERMES_CRON_SESSION", "HERMES_SESSION_PLATFORM"):
        monkeypatch.delenv(name, raising=False)
    set_approval_callback(None)
    yield
    set_approval_callback(None)


READ_ONLY = [
    "cat AGENTS.md",
    "cat AGENTS.md | head -n 20",
    "grep -n TODO SOUL.md",
    "ls -la docs/ && cat docs/CLAUDE.md",
    "git diff AGENTS.md",
    "python scripts/gen.py",
]

WRITES = [
    ": > AGENTS.md",
    "echo '# rules' >> CLAUDE.md",
    "printf 'x' > .cursorrules",
    "sed -i 's/old/new/' SOUL.md",
    "sed -i.bak -e 's/a/b/' AGENTS.md",
    "cp notes.md AGENTS.md",
    "mv AGENTS.md.bak AGENTS.md",
    "cat snippet | tee -a SOUL.md",
    "truncate -s 0 AGENTS.md",
    "Set-Content -Path .cursorrules -Value '# x'",
    "Out-File AGENTS.md",
    "Copy-Item template.md -Destination CLAUDE.md",
]


@pytest.mark.parametrize("command", READ_ONLY)
def test_read_only_mentions_do_not_prompt(command, tmp_path):
    assert guards.protected_instruction_write_targets(command, cwd=str(tmp_path)) == []


@pytest.mark.parametrize("command", WRITES)
def test_shell_writes_are_detected(command, tmp_path):
    targets = guards.protected_instruction_write_targets(command, cwd=str(tmp_path))
    assert targets
    assert all(os.path.isabs(t) for t in targets)
    assert any(os.path.basename(t).lower() in guards._PROTECTED_INSTRUCTION_BASENAMES for t in targets)


@pytest.mark.parametrize("code", [
    'open("AGENTS.md", "a").write("x\\n")',
    'from pathlib import Path\nPath("SOUL.md").write_text("x")',
    'import shutil\nshutil.copy("template.md", "CLAUDE.md")',
])
def test_code_cell_writes_are_detected(code, tmp_path):
    assert guards.protected_instruction_write_targets(code, cwd=str(tmp_path))


def test_detection_off_when_gate_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(guards, "_protected_instruction_config", lambda: (False, []))
    assert guards.protected_instruction_write_targets(": > AGENTS.md", cwd=str(tmp_path)) == []


def test_extra_patterns_are_honoured(monkeypatch, tmp_path):
    monkeypatch.setattr(guards, "_protected_instruction_config", lambda: (True, ["*.rules"]))
    assert guards.protected_instruction_write_targets("echo x > repo.rules", cwd=str(tmp_path))


def test_absolute_target_is_kept(tmp_path):
    target = tmp_path / "AGENTS.md"
    assert guards.protected_instruction_write_targets(f"echo x > '{target}'") == [str(target)]


def test_terminal_block_refuses_until_approved(tmp_path):
    from tools.terminal_tool import set_approval_callback
    set_approval_callback(lambda command, description, **kw: "once")

    blocked = guards.protected_instruction_shell_block(
        ": > AGENTS.md", cwd=str(tmp_path), task_id="default")
    assert blocked is None

    set_approval_callback(lambda command, description, **kw: "deny")
    blocked = guards.protected_instruction_shell_block(
        ": > AGENTS.md", cwd=str(tmp_path), task_id="default")
    assert blocked is not None and "AGENTS.md" in blocked
    assert "denied" in blocked


def test_pre_exec_guard_raises_for_shell_write(tmp_path, monkeypatch):
    from tools import terminal_tool as T
    from tools.terminal_tool import set_approval_callback

    set_approval_callback(lambda command, description, **kw: "deny")
    monkeypatch.setattr(T, "_validate_workdir", lambda workdir: None)

    with pytest.raises(T._Rejected) as rejected:
        T._pre_exec_block(
            ": > AGENTS.md", env=object(), env_type="local", cwd=str(tmp_path),
            workdir=None, session_key="s", task_id="default")

    payload = json.loads(rejected.value.args[0])
    assert payload["status"] == "blocked"
    assert "AGENTS.md" in payload["error"]


def test_pre_exec_guard_lets_read_only_through(tmp_path, monkeypatch):
    from tools import terminal_tool as T
    from tools.terminal_tool import set_approval_callback

    asked = []
    set_approval_callback(lambda command, description, **kw: asked.append(command) or "once")
    monkeypatch.setattr(T, "_validate_workdir", lambda workdir: None)

    T._pre_exec_block(
        "cat AGENTS.md", env=object(), env_type="local", cwd=str(tmp_path),
        workdir=None, session_key="s", task_id="default")
    assert asked == []


def _stub_execute_code(monkeypatch, *, asked):
    from tools import approval, code_kernel, process_registry, terminal_tool
    from tools import code_execution_tool as C

    monkeypatch.setattr(C, "SANDBOX_AVAILABLE", True)
    monkeypatch.setattr(C, "_load_config", lambda: {"timeout": 5})
    monkeypatch.setattr(terminal_tool, "_get_env_config", lambda: {"env_type": "local"})
    monkeypatch.setattr(terminal_tool, "_docker_has_host_access", lambda cfg: False)
    monkeypatch.setattr(process_registry, "_is_supervised_gateway_process", lambda: False)
    monkeypatch.setattr(approval, "check_execute_code_guard",
                        lambda *a, **kw: {"approved": True})
    monkeypatch.setattr(code_kernel, "execute_in_session_kernel",
                        lambda *a, **kw: pytest.fail("kernel ran despite the block")
                        if asked is None else "RAN")
    from hermes_cli.observability import shared_metrics_loop
    monkeypatch.setattr(shared_metrics_loop, "record_execution_backend",
                        lambda *a, **kw: a[-1] if a else "RAN")


def test_execute_code_blocks_before_running_the_cell(monkeypatch):
    from tools.terminal_tool import set_approval_callback

    set_approval_callback(lambda command, description, **kw: "deny")
    _stub_execute_code(monkeypatch, asked=None)

    from tools import code_execution_tool as C
    res = json.loads(C.execute_code('Path("AGENTS.md").write_text("x")', task_id="t1"))
    assert "AGENTS.md" in json.dumps(res)


def test_execute_code_still_runs_on_a_read_only_cell(monkeypatch):
    from tools.terminal_tool import set_approval_callback

    asked = []
    set_approval_callback(lambda command, description, **kw: asked.append(command) or "once")
    _stub_execute_code(monkeypatch, asked=asked)

    from tools import code_execution_tool as C
    assert C.execute_code("print(1)", task_id="t1") == "RAN"
    assert asked == []
