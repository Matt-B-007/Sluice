"""0.12.5 (House Standard 1.2): one check script. CI and the release workflow run their checks only through scripts/check.sh,
tool versions are pinned in one place, and a failed release says whether it left a draft behind."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = [ROOT / ".github" / "workflows" / name for name in ("ci.yml", "release.yml")]
CHECK = ROOT / "scripts" / "check.sh"
# commands that are checks: they belong in scripts/check.sh, not in a workflow
CHECK_COMMANDS = ["pytest", "pyflakes ", "-m pyflakes", "shellcheck -", "bash -n", "sh -n", "cargo fmt", "cargo clippy",
                  "check-version.py --tag", "check-qt-libs.py", "install.sh --help"]


def _run_lines(path):
    """The shell lines of a workflow's run steps (comments left out)."""
    lines, inside = [], False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("run:") or stripped.startswith("- run:"):
            inside = True
            rest = stripped.split("run:", 1)[1].strip()
            if rest and rest != "|":
                lines.append(rest.split(" #")[0])
                inside = False
            continue
        if inside:
            if stripped.startswith("- ") or re.match(r"^\s{0,6}\w[\w-]*:", line):
                inside = False
            elif stripped and not stripped.startswith("#"):
                lines.append(stripped)
    return lines


def test_workflows_run_checks_only_through_the_check_script():
    for workflow in WORKFLOWS:
        for line in _run_lines(workflow):
            if "scripts/check.sh" in line or line.startswith("pip install"):  # installing a tool is setup, not a check
                continue
            found = [c for c in CHECK_COMMANDS if c in line]
            assert not found, f"{workflow.name}: '{line}' runs a check outside scripts/check.sh"


def test_every_ci_job_runs_the_check_script():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    for section in ("check.sh tests", "check.sh rust tests", "check.sh shell python"):
        assert section in ci


def test_the_check_script_covers_every_shell_script():
    script = CHECK.read_text()
    assert "install.sh uninstall.sh get.sh scripts/*.sh tools/*.sh" in script
    for path in [*ROOT.glob("*.sh"), *(ROOT / "scripts").glob("*.sh"), *(ROOT / "tools").glob("*.sh")]:
        assert path.name in ("install.sh", "uninstall.sh", "get.sh") or path.parent.name in ("scripts", "tools"), path


def test_the_check_script_is_valid_bash_and_rejects_an_unknown_section():
    assert subprocess.run(["bash", "-n", str(CHECK)]).returncode == 0
    out = subprocess.run(["bash", str(CHECK), "nonsense"], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 1 and "Unknown section" in out.stderr


def test_missing_tools_are_listed_with_the_arch_command_and_exit_3(tmp_path):
    """Exit codes: 0 pass, 1 a check failed, 3 only tools missing (nothing checked)."""
    fake = tmp_path / "python3"  # a Python that has none of the modules the tests need
    fake.write_text("#!/bin/sh\ncase \"$*\" in *check-qt-libs*) exit 0;; -c*) exit 1;; esac\nexit 0\n")
    fake.chmod(0o755)
    out = subprocess.run(["bash", str(CHECK), "tests"], capture_output=True, text=True, cwd=ROOT,
                         env={"PATH": "/usr/bin:/bin", "PYTHON": str(fake), "HOME": str(tmp_path)})
    assert out.returncode == 3, out.stdout + out.stderr
    assert "nothing was checked" in out.stdout
    assert "sudo pacman -S --needed pyside6 python-numpy python-pytest" in out.stdout
    assert "paru -S --needed python-pulsectl" in out.stdout and "== " not in out.stdout


def test_tool_versions_are_pinned_once_and_used_by_ci():
    pins = dict(re.findall(r"^([A-Z_]+)=(\S+)$", (ROOT / "scripts" / "tool-versions").read_text(), re.M))
    assert pins["SHELLCHECK_PY"].startswith(pins["SHELLCHECK_VERSION"])
    toolchain = (ROOT / "rust" / "sluice_dsp" / "rust-toolchain.toml").read_text()
    assert re.search(r'^channel = "\d+\.\d+\.\d+"$', toolchain, re.M) and "clippy" in toolchain and "rustfmt" in toolchain
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert ci.count(". scripts/tool-versions") >= 1 and "rust-toolchain.toml" in ci


def test_installing_sluice_does_not_download_the_pinned_rust():
    """The pin is for the checks; install.sh builds with the Rust the user already has."""
    install = (ROOT / "install.sh").read_text()
    assert "RUSTUP_TOOLCHAIN" in install and "rust-toolchain.toml" in install


def test_a_failed_release_says_whether_it_left_a_draft():
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "if: failure()" in release and "draft release" in release.lower() and "gh release delete" in release
    assert release.index("check.sh shell python release") < release.index("- name: Build")
