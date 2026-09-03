"""
ProtBot - Application Usage Tracker.

A shim. The startup sequence lives in `ui/launcher.py`, which is also what the
`protbot` entry point declared in pyproject.toml calls, so an installed copy
and a copy run out of the source tree take the same path.

This file stays because three other things name it — `packaging/protbot.spec`,
`ProtBot.bat` and `BUILD.md` — and moving one function is not a reason to
break them.
"""

from ui.launcher import main

if __name__ == "__main__":
    main()
