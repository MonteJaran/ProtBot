# Working on ProtBot

## Push to ProtBot. Never to FocusGuard.

The canonical repository is **`https://github.com/MonteJaran/ProtBot.git`**.

`MonteJaran/FocusGuard` is the abandoned predecessor from before the rename.
It still exists, its `main` is frozen at an old commit, and **nothing may be
pushed to it**. This is the owner's standing instruction, not a preference.

The catch: in a fresh container the `origin` remote is provisioned pointing at
FocusGuard, so `git push origin` sends work to the wrong repository. Fix it at
the start of any session that will push:

```bash
git remote set-url origin https://github.com/MonteJaran/ProtBot.git
git remote -v          # confirm before pushing
```

`git remote -v` printing FocusGuard means the reset has happened again. Re-run
the command above rather than pushing.

Work lands on `main`. Do not open a pull request unless asked — the owner
merges directly.

## Always update the todo

`STATUS.md` is the working todo, and **updating it is part of finishing a
change, not an optional extra.** The owner reads that file to decide what to do
next; a stale one sends them at work that is already done, or hides work that
is not. Treat it the way you would treat a failing test.

Every change that lands updates it in the same commit:

- move what you finished into the **Finished** section, saying what it means
  rather than naming the commit;
- add anything the work turned up — a new blocker, a follow-up, a thing you
  deliberately left out;
- correct the test counts in the header if they moved;
- update *Last updated*.

`CHANGELOG.md` is the user-facing record and moves on the same schedule.
`AUDIT.md` is history and does not get rewritten.

## Where things are written down

| File | What it holds |
|---|---|
| `STATUS.md` | **The todo.** What is left, split into blocked-on-the-owner and codeable, plus what is finished. Keep it current — see above. |
| `AUDIT.md` | Historical record of the readiness audit and what each finding became. Do not rewrite history here. |
| `CHANGELOG.md` | Keep a Changelog format. Nothing has shipped, so entries sit under Unreleased. |
| `ROADMAP.md` | Features, none of them blocking. |
| `PRIVACY.md` | The privacy policy. Every claim in it is checked by a test. |
| `BUILD.md` | The first-real-build checklist. |
| `PLATFORMS.md`, `android/README.md` | The Windows/Android split and what is shared. |

## Two constraints that are enforced by tests

**The app must not overstate itself.** Tests fail the build if a third-party
brand appears in a promotional string, if the plan comparison lists a feature
that does not exist, if `PRIVACY.md` promises a control the UI lacks, or if
`CHANGELOG.md` claims a release that has not happened. When you add a claim,
add the test that keeps it true.

**`LEGACY_APP_NAME` in `core/paths.py` must stay `"FocusGuard"`.** It is the
only thing that finds an existing install's data directory during the rename
migration. A blanket find-and-replace over the app name silently turns the
whole migration into a no-op and loses every existing user's history. There is
a test guarding it; do not "fix" that test.

## Verifying a change

```bash
python -m pytest -q                     # 504 tests
ruff check .
python -m compileall -q core ui server main.py   # the Tk modules the suite cannot import
cd android && gradle :core:test          # 93 Kotlin tests, no Android SDK needed
```

`android/app/` cannot be compiled without an Android SDK. If one is not
present, say so rather than implying the Android app builds.

## Things that have never run

Everything Windows-specific was written against documentation: `core/tray.py`,
everything in `packaging/`, the two OS probes in `core/activity.py`,
`create_shortcut.ps1`, and the whole `android/app/` module. Do not describe any
of it as working. `STATUS.md` keeps the list.
