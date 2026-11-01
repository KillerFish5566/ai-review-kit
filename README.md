# ai-review-kit — AI development checks and independent review, as a portable kit

[繁體中文說明](README.zh-TW.md)

For people who build software with AI, can check that features work, but cannot spot security holes themselves. The development AI (Claude Code) writes a handoff, a separate reviewer reviews it independently (by default an isolated Claude subagent, marked "not a Codex review"; Codex for large changes and before a release), and every result is tied to an exact version of the code. Change the code and the old result is no longer valid.

The kit contains only methods, templates and tools. It contains **no project code, vulnerability details, internal paths or secrets**.

- Python 3.9+, standard library only. Works with git (and, with fewer features, without it).
- Installs per project; each project carries its own copy, so it does not depend on a central path.
- Hooks and skills for two hosts: Claude Code (`.claude/`) and Codex (`.codex/`, `.agents/skills/`).
- 383 automated checks (`tools/tests/test_kit.py`).

> **Language note:** the specs, skills, templates, docs and the tool's messages are written in **Traditional Chinese**, because that is the author's working language. Command names and options are English, and this README is in English. Translations are welcome.

Version: see `VERSION`. Changes: `CHANGELOG.md` (Traditional Chinese).

## The flow on one page

```
You                   Claude Code (development AI)          Reviewer (started by Claude in the background)
│ /safety-setup ───→ survey the project, write .ai-review/config.md
│ build, check features
│ /review-ready ───→ pin the version (fingerprint + git snapshot)
│                    run the checks in config.md and record the real results
│                    write handoff H-xxx.md → status "pending review"
│                    pick a reviewer:
│                      default: kit.py claude-review --begin,
│                               then the independent-reviewer subagent ─→ verify fingerprint, read the diff and full code
│                      large change (> big_change_files) or --codex:
│                               kit.py codex-review (background) ──────→ same, in the Codex sandbox
│                    ←──────── notify when done, report ─── write review R-xxx.md (needs-fix / no-blocking-found)
│                    (Claude route: kit.py claude-review --end records and derives the state)
│ /review-fix R-xxx → fix item by item, write F-xxx.md, hand off again → "pending recheck" → reviewer rechecks
│ Before merging:  py -3 .ai-review/kit/kit.py gate
│ Before a release (if required): py -3 .ai-review/kit/kit.py gate --require-reviewer codex
```

Five states: not ready → pending review → needs fix → pending recheck → no blocking issues found (within this scope). The state is **derived** from report headers and the current code fingerprint. Nobody declares it by hand. Details: `core/workflow.md`.

## What is in the kit

```
ai-review-kit/
├ README.md, README.zh-TW.md, LICENSE, VERSION, CHANGELOG.md
├ core/            tool-neutral specs (Markdown)
│  ├ workflow.md            overview, state derivation, version binding, hard rules
│  ├ security-checklist.md  checklist mapped to OWASP ASVS 5.0.0, plus six design questions
│  ├ handoff-spec.md        handoff spec (review-ready)
│  ├ review-spec.md         independent review spec (the reviewer must read it)
│  └ fix-spec.md            fix spec (review-fix)
├ templates/       config.md, handoff.md, review.md, fix.md, entry-claude.md, entry-agents.md
├ claude/skills/   safety-setup, review-ready, review-fix (Claude Code skills)
├ claude/agents/   independent-reviewer (isolated Claude reviewer subagent, installed to the project's .claude/agents/)
├ codex/skills/    independent-review (Codex skill, installed to the project's .agents/skills/)
├ tools/kit.py     install / update / status / restore / pack, plus snapshot / checks / state / gate / hooks inside a project
├ tools/tests/     automated tests (temporary projects, 383 checks)
└ docs/            codex-start.md (hand over to Codex), daily-usage.md, offline-setup.md (using it on a machine without GitHub access)
```

## Install (per project)

Requirements: Python 3.9+ (standard library only), git. Use `py -3` on Windows and `python3` on macOS / Linux.

```
py -3 <kit folder>/tools/kit.py install --target <project root>
```

Install will:
- copy specs, templates and tools to `<project>/.ai-review/kit/`
- put skills in `.claude/skills/` (Claude Code) and `.agents/skills/` (Codex), and the reviewer subagent definition in `.claude/agents/independent-reviewer.md`
- **append** a managed block (`<!-- ai-review-kit:begin … end -->`) to `CLAUDE.md` and `AGENTS.md`; text outside the block is not touched
- merge two hooks (SessionStart, Stop) into `.claude/settings.json` without touching other settings; add one SessionStart hook to `.codex/hooks.json` (Codex runs it only after you trust it in `/hooks`)
- add `.ai-review/.cache/`, `.ai-review/.backup/`, `.ai-review/local.json` and `.ai-review/state.json` to `.gitignore` (existing lines are not duplicated)
- record the version in `.ai-review/kit-version.json` (committed, no local paths); this machine's interpreter and kit source go to `.ai-review/local.json` (not committed); files are backed up to `.ai-review/.backup/<time>/` before any change

Then run `py -3 .ai-review/kit/kit.py doctor` to see what is still missing (reviewer definition, Codex installed and signed in, gitleaks, and so on). **Restart Claude Code** and open it **in the project root** (hooks and subagent definitions load only at start), then run `/safety-setup`.

Other commands:

| Command | What it does |
|---|---|
| `install --preview` | Show every file and diff that install would write (hooks, settings, `.gitignore`, records). Writes nothing |
| `update --source <folder or zip> [--preview]` | Three-way update (as installed / current / new source). Your edits are kept; files changed on both sides are reported as conflicts and not overwritten; `--take-source <path>` takes the source version |
| `status` | Kit version, source version, which files you changed, whether hooks / skills / entry blocks are in place, and the current state (rewrites `state.json`) |
| `state --json --no-write` | Derive the state and print JSON. **Writes no files.** For outside programs such as a hook in a parent folder. Older kits without this flag exit with code 2 |
| `doctor [--json]` | Read-only list of what is missing before a review: git, Codex on PATH and signed in (checks only, never signs in, never prints the account), node_repl, gitleaks / pip-audit, which Python the review will use, the reviewer subagent (definition file, whether the guard hook's `py` can be found, `claude --version` ≥ 2.1.271, and a reviewer definition outside the repository in a parent folder: if its hook points at this project it must match the project's version, otherwise ✗ with the `reviewer-agent … --force` command to regenerate it; if it belongs to another project, or the hook path cannot be read, only a note, never ✗ or `--force`; the same rule applies to `~/.claude/agents`), and open items in `config.md` section 6. Always exit 0 |
| `restore --yes` | Undo the latest install or update (lists files first); can step back further |
| `relink [--python "py -3"]` | After moving to another machine, rewrite the hook interpreter and rebuild `local.json` |
| `codex-review [--detach] [--print] [--permissions <name>]` | Start a Codex review of the latest handoff in a sandbox: if your Codex config sets `default_permissions` (a permission profile, which can deny reads), it is passed with `-c` and `-s` is left out so the profile's deny list takes effect; otherwise `-s workspace-write`. Log goes to `.ai-review/.cache/codex-<H>.log`, a `.done` file is written at the end. Passes `AI_REVIEW_PYTHON`, `SystemDrive` and similar variables into the sandbox with `-c` (this run only; Codex config is not changed). After the review it compares the workspace and warns about files that appeared or changed; it never deletes them |
| `claude-review --begin <H> [--again]` / `claude-review --end <H> --model <alias>` | The isolated-Claude route, used by `/review-ready`. `--begin` checks the handoff can be reviewed, records the workspace and the existing review reports before the review (`.ai-review/.cache/claude-<H>.running`), renames a non-empty guard heartbeat log to `claude-<H>.prev-<time>.guard.jsonl` (kept as evidence, never cleared) and starts an empty one, prints a ⚠️ and records `agent_stale: true` when this project's out-of-repository definition is out of sync (a note only when it belongs to another project), and prints the four-line prompt (paths with forward slashes); `--end` accepts only a `reviewer: claude-isolated` report written during this review (none → exit 1), warns and exits 1 if an earlier report was changed or deleted or a new report has another reviewer, warns loudly when the guard left no heartbeat (the state then says the guard was not active), compares the workspace, writes `.ai-review/.cache/claude-<H>.done` (with `reviewer_model`, `guard_calls`, and `nested` / `claude_md_exposure` when CLAUDE.md files may have been attached to the reviewer), appends a line keyed by the R id to `claude-<H>.history.jsonl` (not cleared by a later `--begin`) and derives the state. `--print` shows what it would do without writing |
| `gate [--allow-no-guard]` | Before merge or deploy: needs a valid handoff, an independent review with no blocking issues, and a matching fingerprint. For an isolated-Claude review it also checks local records (`.ai-review/.cache/`, not in version control): exit 1 when the closing record (`.done` or `claude-<H>.history.jsonl`) shows 0 guard heartbeats, or when this machine has records of the handoff (`claude-<H>.*`) but no closing record for that report (not yet `--end`, or re-sent with `--begin --again` and not closed); `--allow-no-guard` lets these two through with a reminder. No records of the handoff at all (another machine, CI): a note only. A report whose file — or any file with the same `id` — appears in the guard's write log (rotated logs included) but whose header names another reviewer (posing) is always blocked, `--allow-no-guard` or not |
| `gate --require-reviewer codex` | Like `gate`, but also requires the latest valid review to be a Codex review (exit 1 for an isolated-Claude review) and checks the report header against local records: if a `codex-review` run record (`.ai-review/.cache/codex-<H>.done`) exists it must point at that report; if there is none (Codex opened by hand), the report is blocked when the guard's write log shows the isolated Claude reviewer wrote it (posing as Codex), otherwise it is accepted on its header with a note (this cannot be told apart when the guard was not active). `.cache` is not in version control, so this is a local gate: do not use it in CI. For projects that want Codex before a release |
| `checks [--run]` | Lists (or with `--run`, runs and records) the check commands in `config.md` section 4. With `--run`, sets `PYTHONIOENCODING=utf-8` for the child process only when it is not already set (an existing value is kept; `PYTHONUTF8` is not set) and prints a line when it did, so Python checks that print non-ASCII characters do not crash on a cp1252 / cp950 console. Running the commands directly, not through the kit, gets no such help |
| `reviewer-agent --session-root <folder> [--python python3] [--out <file>]` | For nested projects: prints a reviewer definition whose hook path points from the folder where Claude Code is opened to this project. On machines without `py`, `--python python3` swaps the guard hook's interpreter. Writes only with `--out` |
| `hook review-guard` | The reviewer's guard hook (run automatically before every tool call of the reviewer subagent; not for manual use) |
| `ignore-check [--json]` | Read-only check that `.gitignore` excludes a standard list of 15 secret patterns (`.env`, keys and certificates, `.claude/projects/` transcripts, `*.jsonl`, `memory/`, …). Each rule is tested with several sample paths through git itself. Lists tracked files that match (paths only, never contents). A reminder, not a gate: **never edits `.gitignore`**, exit 0 on gaps |
| `pack` | Build an offline zip in `dist/` |
| `check-update --url <URL of a VERSION file>` | Compare version numbers only; never updates by itself. Without network it says "update not checked" |

## Day to day

| When | Do |
|---|---|
| Once per new project | `/safety-setup` |
| A change is complete | `/review-ready` |
| Independent review | Nothing: `/review-ready` picks a reviewer, starts it in the background and reports when done |
| Send this one to Codex (e.g. before a release) | `/review-ready --codex`. To run Codex yourself, see `docs/codex-start.md` |
| The review asks for fixes | `/review-fix R-<id>` |
| Before merge or deploy | `py -3 .ai-review/kit/kit.py gate` (before a release, if required: `gate --require-reviewer codex`) |
| Check the state | `py -3 .ai-review/kit/kit.py status` |
| After install or a machine move | `py -3 .ai-review/kit/kit.py doctor` |

## Two reviewers

| Reviewer | When | `reviewer` in the report | How it starts |
|---|---|---|---|
| Isolated Claude (`independent-reviewer` subagent) | Default | `claude-isolated`; status adds "(not a Codex review)" | `/review-ready` runs `claude-review --begin`, sends the subagent with a different model from the development AI (opus → fable, anything else → opus), then `claude-review --end` |
| Codex | Large changes (more changed files than `big_change_files` in `config.md` section 5, default 10), before a release, or `--codex` | `codex` | `/review-ready` runs `kit.py codex-review` in the background; or you open Codex yourself |

- The isolated reviewer starts fresh: no development context, no CLAUDE.md, no memory, a different model, and it runs on your Claude subscription. A general-purpose subagent does not count as a reviewer, and the skills tell Claude never to use one as a stand-in.
- **Guard hook (`review-guard`)**: the reviewer's definition runs `kit.py hook review-guard` before every tool call (with `onFailure: block`). It allows writing only new `.ai-review/reviews/R-*.md` files (only after `claude-review --begin`; Write only creates new files, and reports that existed before the review cannot be edited), and allows only read-only git commands (`diff`, `show`, `log`, `status`, `ls-files`, `rev-parse`, `cat-file`; `--show-signature` is blocked because it runs the signing program), `kit.py verify` / `new-id R` / `state --no-write` (only `state` takes `--json`) / `checks --run` (run with `py -3` on Windows or `python3`), and the check commands in `config.md` section 4 word for word. Chaining and redirection (`&&`, `;`, `|`, `>`, `<`, backticks, `$(`, new lines) are blocked; write paths in double quotes or with forward slashes. `SubagentHandback` (the subagent's final report) is allowed. The reviewer writes anything it could not do into the report's limits.
- **The guard only works when**: (1) the project folder has been opened in Claude Code once and **trusted** — in an untrusted folder Claude Code silently skips the hooks in the subagent definition (observed 2026-11-01); (2) Claude Code is **2.1.271 or later** (older versions ignore `omitClaudeMd`); (3) the hook's interpreter `py` can be found (otherwise use `reviewer-agent --python python3`); (4) Claude Code is **opened in the project root** (opened in a subfolder, the hook cannot find kit.py and blocks every tool). `doctor` checks (2) and (3) and reminds you of (1) and (4).
- **How you know it worked**: the reviewer first runs `echo guard-canary`, which must be blocked; if it is not, the reviewer stops and reports "guard not active". The guard writes one heartbeat line per call to `.ai-review/.cache/claude-<H>.guard.jsonl` (time, tool name, allowed or blocked, and the R file name for allowed writes); `claude-review --end` warns loudly when there are none, and the state then says "(not a Codex review; guard not active)".
- **What the guard cannot do**: it only controls Claude's tool calls. A program it allowed (for example a check command that starts Python) can still write files on its own. Those are caught after the fact: `claude-review --end` compares the workspace before and after the review, warns, and records the changes. It never deletes them. Git settings such as `core.fsmonitor` can also make read-only git commands start other programs; the reviewer cannot change those settings.
- Requiring Codex before a release: set `發版前 gate 需 Codex 審查：是` ("release gate requires Codex review: yes") in `config.md` section 5 and run `gate --require-reviewer codex` before releasing (a local gate; a review through `codex-review` or from Codex opened by hand both count, and a report the isolated Claude reviewer wrote while posing as Codex is caught by the guard's write log).
- Once Codex has said "needs fix" for a handoff, a later isolated-Claude "no blocking issues found" does not replace it (a weaker reviewer cannot overrule a stronger one); review again with Codex or fix and hand off again. `gate` prints the review history.
- `/review-ready --claude` forces the isolated-Claude route; `--codex` forces Codex.

### Nested projects

Claude Code looks for subagent definitions only in `.claude/agents/` from the folder where the conversation was opened upward, and `${CLAUDE_PROJECT_DIR}` in the hook is that folder. If you open Claude Code in a parent folder that contains the project, the project's reviewer definition is **not loaded** and `/review-ready` offers the fallbacks (use Codex, or open Claude Code in the project folder). To use the isolated reviewer from the parent folder, run `kit.py reviewer-agent --session-root <parent folder>`, put its output in `<parent folder>/.claude/agents/independent-reviewer.md`, and restart Claude Code. Only one such definition fits in one folder, so only one nested project per parent folder can use it.

## Updating across machines

- Keep the central copy somewhere you control (this git repo, or a zip made by `pack`).
- Each project records the version it uses (`.ai-review/kit-version.json`).
- Always run `update --source … --preview` first, then `update --source …`. The kit never overwrites the whole `.claude/` or `.codex/` folder and never touches sign-in data, chat transcripts, keys or project data.
- On a machine without access to this repo, copy the zip over and run `install --source <zip>`. The tool uploads nothing. See `docs/offline-setup.md`.

## Limits (honest version)

- Hooks only make mechanical checks (version, fingerprint match, open items, the reviewer's allow-list). They do not scan code, do not call another AI, and cannot block a push or a deploy.
- The isolated Claude reviewer is a different model with a clean context, but it is still Claude, and its guard only covers Claude's own tool calls (see "Two reviewers"). Reports say "not a Codex review" so you can tell the two apart; use Codex for large changes and releases.
- The reviewer subagent definition is loaded when Claude Code starts. After the first install, or an update that adds it, restart Claude Code. In a nested project it is not found at all unless you use `reviewer-agent`.
- `omitClaudeMd` only skips the CLAUDE.md loaded at startup. When the reviewer reads files in a subfolder (in a nested project, the project itself counts), Claude Code still attaches that folder's CLAUDE.md to the reviewer's conversation; the kit records which files in `.done` (`claude_md_exposure`).
- The session-start status and stop reminder only run when Claude Code is opened **directly in the project folder** (the hooks live in the project's own `.claude/settings.json`). Run `kit.py state` or `/review-ready` yourself otherwise.
- Review records (`.ai-review/handoffs`, `reviews`, `fixes`) follow git branches. After switching branches you see that branch's state; the reviews are not lost.
- `gate` is a local check and can be skipped. To enforce it, protect the branch on GitHub and run gate in CI (`templates/ci/github-actions-gate.yml` is an example that has **not** been tested on a real repository).
- A "passed" line in a state file or report is not proof of security. Proof is: which fingerprint, who reviewed, what they looked at, and how.
- Projects without git have no snapshot ref; the fingerprint falls back to file hashes.
- The Codex `$independent-review` skill has run many times in the background with `codex exec` on a real project (since 2026-09-25). The Codex-side SessionStart hook is still unverified. Automated tests use a fake codex to check command shape and records; they never call the real Codex.
- Open Codex by hand only in the project root. On Windows, opening it in your user folder or a parent folder can leave "modify" permissions for the sandbox group on the whole folder tree and add it to the trust list, which stays after Codex closes (observed 2026-10-11; details and how to undo in `docs/codex-start.md`). `codex-review` always uses `-C <project>` and is not affected.
- `codex-review` needs a local Codex sign-in and quota. Without quota there is no review report; record which handoff is still unreviewed in `config.md` section 6.
- On Windows, when Codex's shell tool fails to start (sandbox "setup refresh had errors"), Codex falls back to its node_repl tool. The allow-list the kit adds for node_repl (`NODE_REPL_UNTRUSTED_ENV_ALLOWLIST`) was taken from the local node_repl executable, not from official docs, and may break when Codex changes. The post-review comparison warns if it does; `--no-sandbox-env` turns it off.
- On Windows, gitleaks may fail to start inside the Codex sandbox (spawn EPERM; observed 2026-10-12, also with the full path). The reviewer then has no secret scan of its own, only the one the development side ran at handoff, and the review report says so.
- With a Codex permission profile on Windows (mxc sandbox, Codex 0.162.1, tested 2026-10-18), the deny list blocks reading file contents but not listing folders: the reviewer can still see file and folder names inside a denied folder.
- Fingerprints can differ between CI and a local machine when `core.autocrlf` settings differ. If that happens, trust the local result and disable gate in CI.

## Tests

```
py -3 tools/tests/test_kit.py
```

Builds several test projects in a temporary folder and covers: fresh install; keeping existing CLAUDE.md / AGENTS.md / settings.json; no duplicate blocks on reinstall; preview lists every file a real install writes; fingerprints never write to the project's git object store; `codex-review` command shape, environment, refusal cases, `-c` sandbox settings, permission profiles (no `-s` when `default_permissions` is set, danger names refused) and warnings about new files (fake codex); update conflicts are not overwritten; restore; code changes make a review stale; hooks do not loop or repeat; clear check results; offline zip install; non-git projects; check-update without network; `ignore-check` (all missing / all present / partial / negation rules / local-only excludes / tracked files listed by path only / accepted entries / read-only / non-git); "initialized" requires meta plus check commands; `state --no-write` writes nothing; section 6 status column in old and new formats; `doctor` (fake codex and PATH, never triggers sign-in, read-only); `state.json` kept out of version control (reminder only, index untouched). The temporary folders are not deleted automatically.

## License

MIT. See [LICENSE](LICENSE).
