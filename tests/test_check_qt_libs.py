"""0.12.4: the CI check for Qt's system libraries asks the loader (the old ``ldconfig -p`` lookup missed libraries that load)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_qt_libs", ROOT / "tools" / "check-qt-libs.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def test_only_libraries_the_loader_cannot_open_are_missing():
    def load(name):
        if name == "libxkbcommon.so.0":
            raise OSError("cannot open shared object file")
    assert check.missing(load=load) == ["libxkbcommon.so.0"]
    assert check.missing(load=lambda name: None) == []


def test_the_message_blames_ubuntus_servers_only_on_github():
    assert "Ubuntu's package servers" in check.message(["libGL.so.1"], on_github=True)
    local = check.message(["libGL.so.1"], on_github=False)
    assert "This computer cannot load libGL.so.1" in local and "package servers" not in local


def test_both_test_jobs_use_the_check():
    lines = (ROOT / ".github" / "workflows" / "ci.yml").read_text().splitlines()
    steps = [i for i, line in enumerate(lines) if line.strip() == "- name: Check that Qt's system libraries are there"]
    assert len(steps) == 2
    assert all(lines[i + 1].strip().startswith("run: python3 tools/check-qt-libs.py") for i in steps)
    assert not any("ldconfig -p" in line for line in lines)
