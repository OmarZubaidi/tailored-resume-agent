# Tailored Resume and Application Agent

Paste job URLs into a spreadsheet; the agent saves each listing, tailors your resume and cover letter,
renders ATS-safe PDFs, files them in a numbered folder, and tracks the application through each
stage. Rejections and interview invites come in through a read-only Gmail scan that asks before
changing anything.

## What you can say

Open any coding agent (Claude Code, or one that reads `AGENTS.md`) in this folder and say:

| Say | What happens |
| --- | --- |
| "add these jobs" | After you paste URLs into the Inbox sheet: fetches, triages and tailors each one |
| "review flagged jobs" | Lists jobs triage flagged (location, sponsorship, years, missing skills); you pick proceed or drop |
| "applied to Acme Health" | Records Applied and locks that application's resume and cover letter |
| "rejected by Acme Health" | Records Rejected |
| "Acme Health moved to 2nd round, technical Dec 10" | Records 2nd with the detail in the timeline |
| "status of 42" | Reads application 00042's timeline |
| "review updates" | Lists stage updates the Gmail scan found; you confirm or reject each |
| "switch home industry to finance" | Changes `home_industry` and its keywords in `config.yaml` |
| "add a new baseline" | Copies the general baseline to a new one and edits it with you |

A macOS notification such as "Acme Health rejection → #00042?" means the scan queued an update: say
"review updates".

Several open applications at one company? The agent shows a short pick list and asks.

## Setup

1. **Python env** (Python 3.12 or newer; the stock macOS `python3` is too old):

   ```sh
   python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
   .venv/bin/playwright install chromium
   .venv/bin/resume_agent dev install-hooks
   ```

2. **Config**: copy `config.example.yaml` to `config.yaml` (gitignored) and fill it in. Every key is
   required. `apply_on_my_behalf` stays `false` unless you change it by hand. `excel_template` must
   point at an existing `.xltx` file. Check the rest with `.venv/bin/resume_agent config check`.
3. **Proton Drive**: in Finder, set the data folder (`data_root`) to "Available offline". `init`
   refuses to run while it is cloud-only.
4. **Data folder and workbook**: `.venv/bin/resume_agent init`.
5. **Baseline**: put `resume.md`, `cover-letter.md` and `skills-ledger.yaml` in
   `baselines/general/` under `data_root` (`bullet-bank.md` is optional). Triage and tailoring need
   them, so the first `inbox` run fails without them.
6. **Gmail scan**: follow [docs/gmail-setup.md](docs/gmail-setup.md) (Google project, sign-in,
   launchd schedule).

The AI steps use your Claude subscription through `claude` (the one on your PATH, else the one
bundled with Claude Desktop or the VS Code extension; no API key), or a local Ollama / LM Studio
model, set by `llm.provider` in `config.yaml`.

## Developer

Agents follow [AGENTS.md](AGENTS.md); `CLAUDE.md` imports it, and `.claude/skills/resume-agent` wraps
it as a Claude skill.

| Command | Does |
| --- | --- |
| `init` | Creates the data folder layout and the workbook |
| `config check` | Validates `config.yaml` |
| `render [FOLDER] [--baseline NAME] [--draft]` | Renders resume and cover letter PDFs plus the ATS report |
| `fetch OUT_DIR --url URL \| --pdf FILE` | Saves, validates and triages one listing |
| `tailor FOLDER [--baseline] [--mode]` | Tailors to a fetched listing, then renders |
| `inbox` | Processes every new Inbox row |
| `review proceed\|drop ID...` | Decides flagged Inbox jobs |
| `update COMPANY STAGE [--date] [--note] [--id]` | Records a stage |
| `gmail login --client-file JSON` | Read-only Gmail sign-in, token in the Keychain |
| `gmail scan` | Classifies new emails and queues stage updates |
| `updates [confirm\|reject N...]` | Lists, confirms or discards queued updates |
| `dev install-schedule` | Installs the launchd scan schedule |
| `dev install-hooks` | Enables the pre-commit guard |

Run any of them as `.venv/bin/resume_agent <command> --help` for every option. Checks:
`.venv/bin/pytest` and `.venv/bin/ruff check src tests`.
