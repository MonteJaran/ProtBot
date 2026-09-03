# Security policy

## Reporting a vulnerability

> **Add a real address below before this repository is public or a build is
> released.** It is deliberately not filled in: a security contact goes on a
> public page and gets scraped, so whether to publish a personal address or set
> up something like `security@` on your own domain is your decision, not a
> default someone else should pick for you. The same open question applies to
> the Contact section of `PRIVACY.md`, which GDPR Article 13 actually requires
> you to answer.

Email **&lt;security contact — see the note above&gt;** with "ProtBot security" in
the subject.

Please include what you did, what happened, and the version from
Settings → About. A rough severity guess is welcome but not required.

Expect an acknowledgement within **7 days**. If you have not heard anything in
14 days, assume the mail was lost and send it again — silence here is a
failure on this end, not a decision.

Please do not open a public GitHub issue for a vulnerability. That publishes
it to everyone, including people who will use it, before there is a fix to
update to.

If you would like credit in the release notes, say so and you will get it.

## Scope

ProtBot is a desktop application. The interesting parts are:

| Area | Why it matters |
|---|---|
| Process termination | ProtBot can close other programs. `core/protected.py` is the denylist that stops it closing the shell, Task Manager, security software or itself. A way past that list is a serious finding. |
| The licence gate | `core/licensing.py` is HMAC-signed and machine-bound. **Client-side licensing is deterrence, not security** — see below — but a way to forge a signature is still worth reporting. |
| Device sync | `core/syncclient.py` uploads usage totals. It refuses plain http, refuses to send anything without a device token, and clamps everything it reads back. Anything that gets undisclosed data onto the wire, or onto it unauthenticated, is in scope. |
| The update check | `core/updates.py` fetches a manifest and will only hand an `https://` link to the browser. It never downloads or executes anything. |
| Stored data | The SQLite database and the log hold a record of every app opened. Neither is encrypted; see "Known and accepted" below. |

## Known and accepted

These are deliberate, documented, and not vulnerabilities. Reporting them is
fine — you will just get this section back.

- **The licence cache is tamper-evident, not tamper-proof.** The machine
  belongs to the user, and any client-side check can be patched out by
  someone with a debugger. The server is the authority for anything that costs
  money to provide. See `AUDIT.md` SF-08.
- **Local data is not encrypted at rest.** Anyone with access to the Windows
  user account can read the database and the log. Encrypting against an
  attacker who already has the account gains nothing real, because the key
  would have to live in the same place. `PRIVACY.md` states this plainly
  rather than implying protection that is not there.
- **The sync server does not exist yet, so its half of authentication is
  unproven.** The client now issues no request without a device token in an
  `Authorization` header, keeps the device id out of URL paths, and treats a
  401 or 403 as permanent rather than retrying a rejected credential
  (AUDIT SF-09). What that buys depends entirely on the server checking the
  token *before* the device id in the payload, and there is no server to
  check. `server/models.py` states the obligation; until something implements
  it, treat the sync API as unaudited.

## Supported versions

Only the latest release. There is one released version, so this is a promise
about the future rather than a policy with any history behind it yet.

## What this project does to find problems itself

- Every push runs the test suite on Python 3.10 and 3.12, on Linux and
  Windows, plus lint and the shared Android rule tests.
- `pip-audit` runs in CI against `requirements.lock`, so a published advisory
  against a pinned dependency fails the build rather than waiting to be
  noticed.
- Dependencies are pinned by exact version and SHA-256 hash in
  `requirements.lock`. Release builds install with `--require-hashes`.
- Dependabot opens pull requests for dependency and GitHub Action updates.
