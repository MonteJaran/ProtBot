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


# ── Documentation ─────────────────────────────────────────────────────────────

def test_build_docs_exist_and_flag_the_untested_parts():
    doc = read(REPO_ROOT / "BUILD.md")
    assert "clean Windows VM" in doc
    assert "SmartScreen" in doc
    # core/tray.py is Win32 ctypes that has genuinely never run.
    assert "never been run" in doc or "never run" in doc


# ── The bill of materials ships with the product ──────────────────────────────
# Regulation (EU) 2024/2847 is about the product, not the repository. A
# document that exists only as a CI artifact does not accompany anything a
# user installs, so the build has to produce it and the build has to bundle it.

def test_the_build_generates_the_bill_of_materials():
    build = read(BUILD_PS1)
    assert "sbom.py" in build, (
        "packaging/build.ps1 no longer generates the SBOM. The Cyber "
        "Resilience Act wants one covering the product's dependencies."
    )


def test_the_bill_of_materials_is_generated_before_pyinstaller_runs():
    # Order matters: the spec bundles the file, so a build that writes it
    # afterwards ships without it and nothing fails.
    #
    # Anchored to the invocation, not the word: "PyInstaller" appears in the
    # script's opening comment, which is before everything.
    build = read(BUILD_PS1)
    assert build.index("sbom.py") < build.index("python -m PyInstaller")


def test_a_failed_sbom_stops_the_build():
    build = read(BUILD_PS1)
    after = build[build.index("sbom.py"):]
    assert "throw 'SBOM generation failed.'" in after[:400]


def test_the_spec_bundles_the_bill_of_materials():
    assert "protbot.cdx.json" in read(SPEC)


def test_the_generated_document_is_not_committed():
    # It is derived from requirements.lock. A generated file in the tree is
    # wrong between the moment a dependency changes and the moment someone
    # remembers to regenerate it.
    assert not (PACKAGING / "protbot.cdx.json").is_file(), (
        "packaging/protbot.cdx.json is generated; it should not be committed."
    )
    assert "protbot.cdx.json" in read(REPO_ROOT / ".gitignore")


# ── The project is installable (AUDIT ST-04) ──────────────────────────────────
# It used to be importable only because main.py put its own directory on
# sys.path. That hid the real gap, which was that pyproject.toml declared no
# build backend at all — so the project could not be installed, and nobody
# found out because nobody tried.

def _pyproject() -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:            # Python 3.10
        pytest.importorskip("tomli")
        import tomli as tomllib
    with open(REPO_ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)


def test_the_project_declares_a_build_backend():
    build_system = _pyproject().get("build-system", {})
    assert build_system.get("build-backend"), (
        "pyproject.toml has no [build-system]. Without one the project cannot "
        "be installed at all — see AUDIT ST-04."
    )
    assert build_system.get("requires")


def test_there_is_an_entry_point_and_it_resolves():
    scripts = {**_pyproject()["project"].get("scripts", {}),
               **_pyproject()["project"].get("gui-scripts", {})}
    assert "protbot" in scripts

    module, _, attribute = scripts["protbot"].partition(":")
    # Resolved from the source, not imported: ui/ pulls in tkinter, which the
    # test suite cannot import on a headless runner.
    source = read(REPO_ROOT.joinpath(*module.split(".")).with_suffix(".py"))
    assert f"def {attribute}(" in source


def test_the_entry_point_is_a_gui_script():
    # On Windows a console script opens a console window that stays for the
    # life of the app. gui-scripts builds the launcher on pythonw.exe instead.
    assert "protbot" in _pyproject()["project"].get("gui-scripts", {})


def test_the_install_carries_the_app_and_not_the_scaffolding():
    packages = _pyproject()["tool"]["setuptools"]["packages"]
    assert set(packages) == {"core", "ui"}, (
        "server/ is a wire contract for a service and tests/ and packaging/ "
        "are scaffolding; none of them belong in an install."
    )


def test_no_module_edits_sys_path_to_import_the_app():
    # The hack ST-04 named. Test helpers and build scripts legitimately still
    # do this — they run as scripts from outside the package — so this covers
    # the application itself.
    for directory in ("core", "ui"):
        base = REPO_ROOT / directory
        for path in sorted(base.glob("*.py")):
            assert "sys.path.insert" not in read(path), (
                f"{directory}/{path.name} edits sys.path. The project is "
                "installable now; import it instead."
            )
    assert "sys.path.insert" not in read(REPO_ROOT / "main.py")


def test_the_licence_is_declared_once_and_not_twice():
    # PEP 639 replaced the "License :: ..." classifier with the `license`
    # expression, and setuptools refuses to build a project carrying both.
    # This is what stopped the project packaging before ST-04 was finished.
    project = _pyproject()["project"]
    assert project.get("license")
    assert not [c for c in project.get("classifiers", [])
                if c.startswith("License ::")], (
        "A 'License ::' classifier alongside the PEP 639 license expression "
        "makes the project unbuildable."
    )


# ── The Android build (AUDIT: :app has never been compiled) ───────────────────
# Source checks, because there is no Android SDK here and there was none when
# any of android/app/ was written. That is exactly why these are worth having:
# a build file that has never run is a build file whose mistakes are invisible,
# and both of the ones below stop the very first compile.

ANDROID = REPO_ROOT / "android"
ANDROID_APP_GRADLE = ANDROID / "app" / "build.gradle.kts"


def _gradle_code(path) -> str:
    """A Kotlin build script with its comment lines removed.

    The comments here explain which mechanism replaced which, so they name the
    obsolete settings on purpose. A check that searched the whole file would
    match the explanation and not the setting.
    """
    return "\n".join(line for line in read(path).splitlines()
                     if not line.lstrip().startswith("//"))




def test_the_compose_compiler_plugin_is_applied():
    # From Kotlin 2.0 the Compose compiler moved into the Kotlin project and
    # became a Gradle plugin. AGP fails outright when buildFeatures.compose is
    # on without it:
    #   "Starting in Kotlin 2.0, the Compose Compiler Gradle plugin is
    #    required when compose is enabled."
    gradle = _gradle_code(ANDROID_APP_GRADLE)
    if "compose = true" not in gradle:
        pytest.skip("the app module no longer enables Compose")
    assert "org.jetbrains.kotlin.plugin.compose" in gradle, (
        "android/app/build.gradle.kts turns Compose on without the Compose "
        "compiler plugin. The build fails before it compiles anything."
    )


def test_the_compose_compiler_plugin_matches_the_kotlin_version():
    # Its version is not a choice — it tracks the Kotlin plugin. A mismatch is
    # a build error, not a warning.
    gradle = _gradle_code(ANDROID_APP_GRADLE)
    kotlin = re.search(r'kotlin\("android"\) version "([^"]+)"', gradle)
    compose = re.search(
        r'id\("org\.jetbrains\.kotlin\.plugin\.compose"\) version "([^"]+)"', gradle)
    assert kotlin and compose
    assert kotlin.group(1) == compose.group(1), (
        f"Kotlin is {kotlin.group(1)} and the Compose plugin is "
        f"{compose.group(1)}; they have to match."
    )


def test_the_obsolete_compose_extension_version_is_gone():
    # kotlinCompilerExtensionVersion inside a composeOptions block is the
    # pre-2.0 mechanism. Leaving it set reads as though the Compose compiler
    # version is pinned, when in fact it is ignored.
    assert "kotlinCompilerExtensionVersion" not in _gradle_code(ANDROID_APP_GRADLE)


def test_every_proguard_file_the_release_build_names_exists():
    # Gradle does not treat a missing rules file as an empty one: it fails the
    # release build with "file not found". proguard-rules.pro was referenced
    # here without ever being written.
    gradle = _gradle_code(ANDROID_APP_GRADLE)
    for name in re.findall(r'"([^"]+\.pro)"', gradle):
        assert (ANDROID / "app" / name).is_file(), (
            f"the release build references android/app/{name}, which is missing"
        )


@pytest.mark.parametrize("klass", [
    "app.protbot.ProtBotApplication",
    "app.protbot.ui.MainActivity",
    "app.protbot.block.BlockerAccessibilityService",
    "app.protbot.usage.BootReceiver",
])
def test_manifest_classes_are_kept_from_the_optimiser(klass):
    # R8 constructs nothing here — the system does, by name, from the
    # manifest — so every one of these is unreferenced code it may rename or
    # remove. The symptom is not a build failure: it is an app that installs,
    # launches, and quietly enforces nothing.
    rules = read(ANDROID / "app" / "proguard-rules.pro")
    assert klass in rules, f"{klass} is instantiated by name and is not kept"


def test_workers_survive_minification():
    # WorkManager stores a worker's class name in its own database and
    # reflects it back. A renamed worker is a job that never runs again after
    # an update, and nothing reports it.
    rules = read(ANDROID / "app" / "proguard-rules.pro")
    assert "androidx.work.ListenableWorker" in rules
    assert "androidx.work.WorkerParameters" in rules


def test_a_debug_build_installs_beside_a_release_one():
    # So a tester can hold both, and can tell which one they are looking at.
    gradle = _gradle_code(ANDROID_APP_GRADLE)
    assert "applicationIdSuffix" in gradle


# ── There is a way to get an installable build ────────────────────────────────

BUILD_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build.yml"


def test_a_workflow_produces_both_installable_artifacts():
    assert BUILD_WORKFLOW.is_file(), (
        "nothing in the repository produces something a person can install"
    )
    workflow = read(BUILD_WORKFLOW)
    assert "windows-latest" in workflow, (
        "PyInstaller does not cross-compile; a Windows runner is the only way "
        "to produce a Windows executable"
    )
    assert "assembleDebug" in workflow, (
        "a release APK is unsigned and Android will not install it; debug is "
        "what a tester can actually put on a phone"
    )


def test_the_windows_build_runs_the_real_build_script():
    # Rather than reimplementing its steps, which would drift from it and
    # would skip the smoke test that catches a missing hidden import.
    assert "build.ps1" in read(BUILD_WORKFLOW)


def test_the_build_can_be_started_by_hand():
    # It is the answer to "give me something to test", which is a question
    # asked on a day, not on a commit.
    assert "workflow_dispatch" in read(BUILD_WORKFLOW)
