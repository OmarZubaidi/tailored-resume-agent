# Tailored Resume and Application Agent

Paste job URLs into a spreadsheet; the code saves each listing, tailors your resume and cover letter,
renders ATS-safe PDFs, files them in a numbered folder, and tracks the application through each
stage you type in.

## Working from the workbook

Edit `Job Applications.xlsx`, save, and `resume_agent sync` acts on it (automatically once
`dev install-sync` is installed):

| You type, then save | Code does |
| --- | --- |
| A date in Applied, Rejected or Skipped | Adds a timeline line and locks the resume and cover letter |
| A date in 1st, 2nd, 3rd or Offer | Adds a timeline line |
| A cleared date | Undoes it: removes the line, unlocks the files unless another of those stages still has a date |
| A URL in the Inbox (Mode and Baseline optional) | After you close Excel: fetches, triages and tailors it, then moves it to Applications |
| `proceed` or `drop` in a flagged row's Decision cell | After you close Excel: tailors it, or marks it Skipped |
| `proceed` in a failed row's Decision cell | After you close Excel: retries it |

Inbox work waits for Excel to close because writing to an open workbook makes Proton Drive create
conflicted copies. Stage dates take effect on every save. The sync log is
`~/Library/Logs/resume_agent/sync.log`.

## What you can say

The agent is for tailoring review and CV help. Open any coding agent (Claude Code, or one that reads
`AGENTS.md`) in this folder and say:

| Say | What happens |
| --- | --- |
| "add these jobs" | After you paste URLs into the Inbox sheet: fetches, triages and tailors each one |
| "review flagged jobs" | Lists jobs triage flagged (location, sponsorship, years, missing skills); you pick proceed or drop |
| "applied to Acme Health" | Records Applied and locks that application's resume and cover letter |
| "rejected by Acme Health" | Records Rejected |
| "Acme Health moved to 2nd round, technical Dec 10" | Records 2nd with the detail in the timeline |
| "status of 42" | Reads application 00042's timeline |
| "switch home industry to finance" | Changes `home_industry` and its keywords in `config.yaml` |
| "add a new baseline" | Copies the general baseline to a new one and edits it with you |

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
6. **Sync on save**: `.venv/bin/resume_agent dev install-sync` (a launchd agent watching the data
   folder; it also runs at login).

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
| `sync` | Acts on stage dates, new Inbox rows and Decision cells in the workbook |
| `inbox` | Processes every new or failed Inbox row |
| `review proceed\|drop ID...` | Decides flagged Inbox jobs |
| `update COMPANY STAGE [--date] [--note] [--id]` | Records a stage |
| `dev install-sync` | Installs the launchd agent that runs `sync` on workbook changes |
| `dev install-hooks` | Enables the pre-commit guard |

Run any of them as `.venv/bin/resume_agent <command> --help` for every option. Checks:
`.venv/bin/pytest` and `.venv/bin/ruff check src tests`.
