"""
The build pipeline (AUDIT ST-01, ST-02, ST-03).

None of this can actually be run here — PyInstaller and Inno Setup need
Windows. What these tests do is stop the build config from drifting away from
the code it packages, and keep the three antivirus triggers from AUDIT ST-03
from creeping back into the launcher.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from core.version import APP_NAME, __version__

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGING = REPO_ROOT / "packaging"

SPEC = PACKAGING / "protbot.spec"
ISS = PACKAGING / "installer.iss"
BUILD_PS1 = PACKAGING / "build.ps1"
LAUNCHER = REPO_ROOT / "ProtBot.bat"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Everything the build references must exist ────────────────────────────────

@pytest.mark.parametrize("path", [SPEC, ISS, BUILD_PS1,
                                  PACKAGING / "make_version_info.py"])
def test_build_files_exist(path):
    assert path.is_file(), f"{path.name} is missing"


def test_spec_references_files_that_exist():
    spec = read(SPEC)
    for name in re.findall(r'ROOT / "([^"]+)"', spec):
        assert (REPO_ROOT / name).exists(), f"the spec bundles {name}, which is missing"


def test_installer_license_file_exists():
    match = re.search(r"^LicenseFile=(.+)$", read(ISS), re.MULTILINE)
    assert match
    # The .iss uses Windows separators, which is correct for Inno; normalise so
    # this test also runs on the Linux CI job.
    relative = match.group(1).strip().replace("\\", "/")
    assert (PACKAGING / relative).resolve().is_file()


def test_icon_is_present():
    assert (REPO_ROOT / "ProtBot.ico").is_file()


def _icon_sizes():
    """Sizes inside ProtBot.ico, read from the header — no Pillow needed."""
    import struct

    data = (REPO_ROOT / "ProtBot.ico").read_bytes()
    _reserved, icon_type, count = struct.unpack("<HHH", data[:6])
    assert icon_type == 1, "not an .ico file"
    sizes = []
    for i in range(count):
        entry = data[6 + i * 16: 22 + i * 16]
        width, height = entry[0], entry[1]
        sizes.append((width or 256, height or 256))
    return sizes


def test_icon_covers_the_sizes_windows_asks_for():
    """
    A single 16x16 image means Windows upscales it for the taskbar, Alt-Tab,
    the desktop shortcut and the installer — blurry everywhere, and more so now
    that the app is DPI-aware and the OS is no longer scaling the whole window.
    Regenerate with: python generate_icon.py
    """
    sizes = {w for w, _h in _icon_sizes()}
    for required in (16, 32, 48, 256):
        assert required in sizes, (
            f"the icon has no {required}x{required} image (has {sorted(sizes)})"
        )


def test_icon_images_are_square():
    for width, height in _icon_sizes():
        assert width == height, f"non-square icon image: {width}x{height}"


# ── Version resource generation ───────────────────────────────────────────────

def test_version_info_generator_runs():
    result = subprocess.run(
        [sys.executable, str(PACKAGING / "make_version_info.py")],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (PACKAGING / "version_info.txt").is_file()


def test_version_resource_carries_the_real_version():
    sys.path.insert(0, str(PACKAGING))
    from make_version_info import render

    rendered = render()
    assert __version__ in rendered
    assert APP_NAME in rendered
    # Windows reads these; an executable with no product identity looks like
    # something thrown together, which is the reputation problem already at play.
    for field in ("CompanyName", "ProductName", "FileDescription",
                  "LegalCopyright", "OriginalFilename"):
        assert field in rendered


@pytest.mark.parametrize("version,expected", [
    ("1.0.0", [1, 0, 0]),
    ("2.5", [2, 5, 0]),
    ("3", [3, 0, 0]),
    ("1.2.3.4", [1, 2, 3]),
])
def test_version_parts_are_padded_to_three(version, expected):
    sys.path.insert(0, str(PACKAGING))
    from make_version_info import parts

    assert parts(version) == expected


# ── Antivirus triggers must not come back (ST-03) ─────────────────────────────

def test_launcher_does_not_install_into_global_python():
    """
    It used to run `pip install -r requirements.txt` against the user's system
    Python on every launch, silently changing libraries their other projects
    depend on.
    """
    launcher = read(LAUNCHER)
    assert ".venv" in launcher, "the launcher must use a virtual environment"
    for line in launcher.splitlines():
        stripped = line.strip()
        if stripped.startswith("::") or not stripped:
            continue
        if "pip install" in stripped:
            assert ".venv" in stripped, f"pip outside the venv: {stripped}"


def test_launcher_does_not_download_and_run_an_executable():
    """Fetching an .exe with no checksum and running it is scored heavily."""
    launcher = read(LAUNCHER).lower()
    code = "\n".join(line for line in launcher.splitlines()
                     if not line.strip().startswith("::"))
    assert "invoke-webrequest" not in code
    assert "python_installer.exe" not in code
    assert "start-process $out" not in code


def test_no_execution_policy_bypass_in_the_launcher():
    code = "\n".join(line for line in read(LAUNCHER).splitlines()
                     if not line.strip().startswith("::"))
    assert "-ExecutionPolicy Bypass" not in code
    assert "-executionpolicy bypass" not in code.lower()


def test_upx_is_disabled():
    """UPX-packed binaries are themselves a strong antivirus signal."""
    spec = read(SPEC)
    assert "upx=True" not in spec
    assert spec.count("upx=False") >= 2


def test_the_build_is_a_folder_not_one_file():
    """One-file unpacks to %TEMP% on every launch, which scores badly."""
    spec = read(SPEC)
    assert "COLLECT(" in spec
    assert "exclude_binaries=True" in spec


# ── Installer correctness ─────────────────────────────────────────────────────

def test_installer_removes_the_startup_registry_entry():
    """
    Without uninsdeletevalue the Run key survives uninstall and Windows keeps
    trying to launch a program that is gone (AUDIT ST-02).
    """
    iss = read(ISS)
    assert "CurrentVersion\\Run" in iss
    assert "uninsdeletevalue" in iss


def test_installer_offers_to_remove_user_data():
    iss = read(ISS)
    assert "{localappdata}\\{#AppName}" in iss
    assert "DelTree" in iss
    # Asked, not assumed: deleting someone's history silently is destructive.
    assert "MB_YESNO" in iss


def test_installer_stops_a_running_instance():
    """Files are locked if the app is in the tray, and the install half-fails."""
    iss = read(ISS)
    assert "taskkill" in iss.lower()
    assert "PrepareToInstall" in iss


def test_installer_does_not_require_admin():
    assert "PrivilegesRequired=lowest" in read(ISS)


def test_installer_has_a_stable_appid():
    """A changed AppId makes every update install alongside the old version."""
    match = re.search(r"^AppId=\{\{([0-9A-Fa-f-]+)\}", read(ISS), re.MULTILINE)
    assert match, "AppId must be a fixed GUID"
    assert len(match.group(1)) == 36


def test_installer_version_comes_from_the_build_not_a_literal():
    iss = read(ISS)
    assert "AppVersion={#AppVersion}" in iss
    assert f'AppVersion "{__version__}"' not in iss, \
        "the version must be passed in by build.ps1, not hardcoded here"


def test_build_script_passes_the_version_to_inno():
    assert "/DAppVersion=$Version" in read(BUILD_PS1)


# ── Build script behaviour ────────────────────────────────────────────────────

def test_build_script_refuses_a_red_tree():
    build = read(BUILD_PS1)
    assert "pytest" in build
    assert "ruff" in build
    assert "not building a release from a red tree" in build


def test_build_script_smoke_tests_the_frozen_app():
    """
    A missing hidden import kills a frozen GUI app at launch, silently. This is
    the only place that gets caught before a user finds it.
    """
    build = read(BUILD_PS1)
    assert "Start-Process" in build
    assert "HasExited" in build


def test_build_script_is_powershell_51_compatible():
    """`powershell` is always 5.1 on Windows — see AUDIT SF-03."""
    code = "\n".join(line for line in read(BUILD_PS1).splitlines()
                     if not line.strip().startswith("#"))
    assert "?." not in code
    assert "??" not in code


def test_signing_is_timestamped():
    """Without a timestamp, signatures stop validating when the cert expires."""
    build = read(BUILD_PS1)
    assert "/tr " in build
    assert "/td SHA256" in build
    assert "/fd SHA256" in build


# ── An installable package, not sys.path.insert (AUDIT ST-04) ─────────────────
#
# Text checks on pyproject.toml, not a TOML parse: tomllib is 3.11+ only and
# this project's floor is 3.10 (requires-python below), and the rest of this
# file already reads packaging config as text (see test_spec_references_
# files_that_exist above) rather than pull in a parser for one section.

def _pyproject_text() -> str:
    return read(REPO_ROOT / "pyproject.toml")


def test_there_is_a_build_backend():
    text = _pyproject_text()
    assert 'requires = ["setuptools' in text
    assert 'build-backend = "setuptools.build_meta"' in text


def test_the_entry_point_is_main():
    assert re.search(r'protbot\s*=\s*"main:main"', _pyproject_text())


def test_setuptools_packages_are_real_and_do_not_overreach():
    # Exactly core/ and ui/, plus the main module — not tests/, android/,
    # packaging/, or server/ (server/ is the separate Cloud Functions
    # deployment; see STATUS.md — nothing in core/ or ui/ imports it).
    text = _pyproject_text()

    packages_match = re.search(r'^packages\s*=\s*\[([^\]]*)\]', text, re.MULTILINE)
    assert packages_match, "no packages = [...] in pyproject.toml"
    packages = re.findall(r'"([^"]+)"', packages_match.group(1))
    assert set(packages) == {"core", "ui"}
    for package in packages:
        pkg_dir = REPO_ROOT / package
        assert pkg_dir.is_dir(), f"{package} does not exist"
        assert (pkg_dir / "__init__.py").is_file(), f"{package} has no __init__.py"

    modules_match = re.search(r'py-modules\s*=\s*\[([^\]]*)\]', text)
    assert modules_match, "no py-modules = [...] in pyproject.toml"
    py_modules = re.findall(r'"([^"]+)"', modules_match.group(1))
    assert py_modules == ["main"]
    for module in py_modules:
        assert (REPO_ROOT / f"{module}.py").is_file(), f"{module}.py does not exist"


def _uncommented(text: str) -> str:
    """Strip whole-line '#' comments, so a check for absence of some text
    is not fooled by that same text appearing in a comment explaining why
    it is absent — as this file's own comments do, deliberately."""
    return "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("#"))


def test_no_license_classifier_alongside_the_license_expression():
    # setuptools refuses to build with both present (PEP 639) — this
    # combination is what pip install -e . actually failed on before it was
    # caught, not a theoretical concern. See AUDIT ST-04, STATUS.md.
    text = _pyproject_text()
    assert 'license = "LicenseRef-Proprietary"' in text
    assert "License ::" not in _uncommented(text)


def test_main_has_no_sys_path_hack():
    main_source = read(REPO_ROOT / "main.py")
    assert "sys.path.insert" not in main_source
    assert "sys.path.append" not in main_source


def test_build_script_has_no_sys_path_hack_either():
    # It had its own copy of the same trick, for the same reason — reading
    # core/version.py before a proper install exists to rely on instead.
    assert "sys.path" not in _uncommented(read(BUILD_PS1))


# ── Documentation ─────────────────────────────────────────────────────────────

def test_build_docs_exist_and_flag_the_untested_parts():
    doc = read(REPO_ROOT / "BUILD.md")
    assert "clean Windows VM" in doc
    assert "SmartScreen" in doc
    # core/tray.py is Win32 ctypes that has genuinely never run.
    assert "never been run" in doc or "never run" in doc
