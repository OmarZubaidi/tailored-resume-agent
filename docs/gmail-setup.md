# Gmail scan setup

The scan reads the job-application Gmail account every `email_scan_hours`, proposes stage updates,
and notifies you when one needs confirming. Access is read-only (`gmail.readonly`): the agent never
sends, replies, labels or deletes.

## 1. Create the Gmail account

1. Create a free account at <https://accounts.google.com/signup>.
2. Set `email` in `config.yaml` to the new address. It also prints on the resume and cover letter,
   and the scan refuses any other signed-in account.

## 2. Create the Google Cloud app

Sign in to <https://console.cloud.google.com> as the new account.

1. Create a project (any name, e.g. `resume-agent`).
2. APIs & Services > Library: search for **Gmail API** and click **Enable**.
3. Google Auth Platform > **Branding** (Google may ask you to click Get started first):
   - App name: `Resume Agent`
   - User support email and developer contact: the new address
4. **Audience**: User type **External**. Then click **Publish app** so the status reads
   **In production**. In Testing, Google expires the sign-in every 7 days.
5. **Data Access** > Add or remove scopes: tick `.../auth/gmail.readonly` and save.
6. **Clients** > Create client: Application type **Desktop app**, any name. Download the JSON.
   Keep it outside the repo, e.g. in `~/Downloads`.

The app stays unverified. That is fine for personal use; Google shows a warning once at sign-in.

## 3. Sign in

```sh
.venv/bin/resume_agent gmail login --client-file ~/Downloads/client_secret_<...>.json
```

A browser opens. Pick the new account. On "Google hasn't verified this app", click **Advanced**,
then **Go to Resume Agent (unsafe)**, then **Continue**. The token goes in the macOS Keychain under
`resume_agent`. You can delete the downloaded JSON afterwards; signing in again needs a new one from
Clients.

Run one scan by hand to check it works and to answer any macOS prompts (Keychain, Proton Drive
access) up front. The first scan reads the last 30 days; later scans read mail since the previous
one.

```sh
.venv/bin/resume_agent gmail scan
```

## 4. Schedule it

```sh
.venv/bin/resume_agent dev install-schedule
```

This installs a launchd agent that runs the scan at login and every `email_scan_hours`. A run missed
while the Mac slept happens on wake. Rerun the command after changing `email_scan_hours`. Output goes
to `~/Library/Logs/resume_agent/gmail-scan.log`.

## Reviewing updates

A notification such as "Acme Health rejection → #00042?" means the scan queued an update. Tell the
agent "review updates", or run:

```sh
.venv/bin/resume_agent updates                    # list them
.venv/bin/resume_agent updates confirm 1 2        # record them in the tracker
.venv/bin/resume_agent updates confirm 3 --id 42  # pick the application yourself
.venv/bin/resume_agent updates reject 4           # discard
```

Nothing changes in the tracker until you confirm. A failed scan (expired sign-in, usage limit) also
sends a notification; the log has the details.

## Revoking access

Remove the app at <https://myaccount.google.com/connections> and delete the `resume_agent` item in
Keychain Access. Remove the schedule with:

```sh
launchctl bootout gui/$(id -u)/com.resume-agent.gmail-scan
rm ~/Library/LaunchAgents/com.resume-agent.gmail-scan.plist
```
