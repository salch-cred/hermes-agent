"""#146763: Windows service discovery must resolve whoami.exe/schtasks.exe from System32 before PATH tools."""
import os
import shutil
from types import SimpleNamespace
import time

from hermes_cli import gateway_runtime_service as service


def test_run_prepends_system32_ahead_of_msys_tools_on_path(tmp_path, monkeypatch):
    system_root = tmp_path / "Windows"
    sys32 = system_root / "System32"
    sys32.mkdir(parents=True)
    for exe in ("whoami.exe", "schtasks.exe"):
        (sys32 / exe).write_text("", encoding="utf-8")

    # Simulate bundled Git/MSYS2 usr/bin earlier on PATH shadowing whoami.exe.
    msys_bin = tmp_path / "git" / "usr" / "bin"
    msys_bin.mkdir(parents=True)
    (msys_bin / "whoami.exe").write_text("", encoding="utf-8")

    monkeypatch.setenv("SystemRoot", str(system_root))
    monkeypatch.setenv("PATH", str(msys_bin) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr(service.sys, "platform", "win32")

    seen = []

    def fake_subprocess_run(argv, **kwargs):
        seen.append((argv, kwargs.get("env", {}).get("PATH", "")))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(service.subprocess, "run", fake_subprocess_run)

    service._run(["whoami.exe", "/USER", "/FO", "CSV", "/NH"], time.monotonic() + 5, encoding=None)
    service._run(["schtasks.exe", "/Query", "/FO", "CSV", "/NH"], time.monotonic() + 5, encoding=None)

    assert len(seen) == 2
    for expected_exe, (argv, child_path) in zip(("whoami.exe", "schtasks.exe"), seen):
        assert argv[0] == expected_exe
        assert child_path.startswith(str(sys32) + os.pathsep)
        assert shutil.which(expected_exe, path=child_path).lower() == str(sys32 / expected_exe).lower()
