# Third-party notices

ProtBot bundles the components below. Both licences require their copyright
notice and permission text to be reproduced in any distribution, source or
binary — so this file ships with the installer, not just with the repository.
`packaging/protbot.spec` copies it into the build and `packaging/installer.iss`
installs it; a test fails if either stops doing so.

This file lists what is **redistributed inside a ProtBot build**. Development
tools (pytest, ruff, PyInstaller, Inno Setup) are not bundled and are not
listed; `requirements.lock` is the exact record of what a release contains.

| Component | Version | Licence |
|---|---|---|
| psutil | 7.2.2 | BSD-3-Clause |
| plyer | 2.1.0 | MIT |
| openpyxl | 3.1.5 | MIT |
| et-xmlfile (openpyxl's own dependency) | 2.0.0 | MIT |
| Python standard library, incl. Tkinter | 3.10+ | PSF-2.0 |

The Android app additionally bundles AndroidX, Jetpack Compose, Room and
WorkManager, all Apache-2.0, and Kotlin, also Apache-2.0. Their notices are
generated at build time by the Android Gradle plugin — see
`android/README.md` — because the resolved dependency set is decided by the
build, and a hand-written list would drift from it the first time a version
moves.

---

## psutil

Used to enumerate running processes. This is the component that makes app
tracking possible at all.

```
BSD 3-Clause License

Copyright (c) 2009, Jay Loden, Dave Daeschler, Giampaolo Rodola
All rights reserved.

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:

 * Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

 * Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

 * Neither the name of the psutil authors nor the names of its contributors
   may be used to endorse or promote products derived from this software without
   specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

---

## plyer

Used for desktop notifications.

```
MIT License

Copyright (c) 2010-2023 Kivy Team and other contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

---

## openpyxl and et-xmlfile

Used for `.xlsx` export (ROADMAP.md item 5, `core/export_xlsx.py`). et-xmlfile
is openpyxl's own dependency — a small, fast alternative to Python's
`xml.etree.ElementTree` for the incremental XML writing an `.xlsx` file needs
— and travels with it into the build, so it is listed here too.

```
This software is under the MIT Licence

Copyright (c) 2010 openpyxl

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

et-xmlfile ships the identical text (same project, same copyright holder).

---

## Python and Tkinter

A PyInstaller build embeds the Python interpreter and the standard library,
including Tkinter and the Tcl/Tk runtime. These are distributed under the
Python Software Foundation License Version 2, which permits redistribution
provided the PSF's copyright notice is retained:

```
Copyright (c) 2001-2026 Python Software Foundation. All Rights Reserved.
```

The full PSF-2.0 text ships inside the build as `LICENSE.txt` in the
distribution folder, placed there by PyInstaller. Tcl/Tk is distributed under
the Tcl/Tk licence (a BSD-style licence), and its terms travel with it in the
same folder.

---

## What is deliberately *not* here

**pystray and Pillow.** ProtBot used to depend on pystray for the tray icon,
which pulls in Pillow. That was replaced with a direct `Shell_NotifyIcon`
implementation in `core/tray.py`. Removing them dropped the LGPL-3.0 §4
obligations that came with parts of that dependency tree, which for a
PyInstaller one-file build are genuinely awkward to satisfy — see AUDIT BL-05.
Do not reintroduce them without re-reading that finding.
