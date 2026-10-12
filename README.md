# ai-review-kit — AI development checks and independent review, as a portable kit

[繁體中文說明](README.zh-TW.md)

For people who build software with AI, can check that features work, but cannot spot security holes themselves. The development AI (Claude Code) writes a handoff, a second AI (Codex) reviews it independently, and every result is tied to an exact version of the code. Change the code and the old result is no longer valid.

The kit contains only methods, templates and tools. It contains **no project code, vulnerability details, internal paths or secrets**.

- Python 3.9+, standard library only. Works with git (and, with fewer features, without it).
- Installs per project; each project carries its own copy, so it does not depend on a central path.
- Hooks and skills for two hosts: Claude Code (`.claude/`) and Codex (`.codex/`, `.agents/skills/`).
- 169 automated checks (`tools/tests/test_kit.py`).

> **Language note:** the specs, skills, templates, docs and the tool's messages are written in **Traditional Chinese**, because that is the author's working language. Command names and options are English, and this README is in English. Translations are welcome.

Version: see `VERSION`. Changes: `CHANGELOG.md` (Traditional Chinese).

## The flow on one page

```
You                   Claude Code (development AI)          Codex (review AI, started by Claude in the background)
│ /safety-setup ───→ survey the project, write .ai-review/config.md
│ build, check features
│ /review-ready ───→ pin the version (fingerprint + git snapshot)
│                    run the checks in config.md and record the real results
│                    write handoff H-xxx.md → status "pending review"
│                    kit.py codex-review (background) ─────→ verify fingerprint, read the diff and full code
│                    ←──────── notify when done, report ─── write review R-xxx.md (needs-fix / no-blocking-found)
│ /review-fix R-xxx → fix item by item, write F-xxx.md, hand off again → "pending recheck" → Codex rechecks
│ Before merging:  py -3 .ai-review/kit/kit.py gate
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
│  ├ review-spec.md         independent review spec (Codex must read)
│  └ fix-spec.md            fix spec (review-fix)
├ templates/       config.md, handoff.md, review.md, fix.md, entry-claude.md, entry-agents.md
├ claude/skills/   safety-setup, review-ready, review-fix (Claude Code skills)
├ codex/skills/    independent-review (Codex skill, installed to the project's .agents/skills/)
├ tools/kit.py     install / update / status / restore / pack, plus snapshot / checks / state / gate / hooks inside a project
├ tools/tests/     automated tests (temporary projects, 169 checks)
└ docs/            codex-start.md (hand over to Codex), daily-usage.md, offline-setup.md (using it on a machine without GitHub access)
```

## Install (per project)

Requirements: Python 3.9+ (standard library only), git. Use `py -3` on Windows and `python3` on macOS / Linux.

```
py -3 <kit folder>/tools/kit.py install --target <project root>
```

Install will:
- copy specs, templates and tools to `<project>/.ai-review/kit/`
- put skills in `.claude/skills/` (Claude Code) and `.agents/skills/` (Codex)
- **append** a managed block (`<!-- ai-review-kit:begin … end -->`) to `CLAUDE.md` and `AGENTS.md`; text outside the block is not touched
- merge two hooks (SessionStart, Stop) into `.claude/settings.json` without touching other settings; add one SessionStart hook to `.codex/hooks.json` (Codex runs it only after you trust it in `/hooks`)
- add `.ai-review/.cache/`, `.ai-review/.backup/`, `.ai-review/local.json` and `.ai-review/state.json` to `.gitignore` (existing lines are not duplicated)
- record the version in `.ai-review/kit-version.json` (committed, no local paths); this machine's interpreter and kit source go to `.ai-review/local.json` (not committed); files are backed up to `.ai-review/.backup/<time>/` before any change

Then run `py -3 .ai-review/kit/kit.py doctor` to see what is still missing (Codex installed and signed in, gitleaks, and so on). Open Claude Code **in the project root** (hooks load on restart) and run `/safety-setup`.

Other commands:

| Command | What it does |
|---|---|
| `install --preview` | Show every file and diff that install would write (hooks, settings, `.gitignore`, records). Writes nothing |
| `update --source <folder or zip> [--preview]` | Three-way update (as installed / current / new source). Your edits are kept; files changed on both sides are reported as conflicts and not overwritten; `--take-source <path>` takes the source version |
| `status` | Kit version, source version, which files you changed, whether hooks / skills / entry blocks are in place, and the current state (rewrites `state.json`) |
| `state --json --no-write` | Derive the state and print JSON. **Writes no files.** For outside programs such as a hook in a parent folder. Older kits without this flag exit with code 2 |
| `doctor [--json]` | Read-only list of what is missing before a review: git, Codex on PATH and signed in (checks only, never signs in, never prints the account), node_repl, gitleaks / pip-audit, which Python the review will use, and open items in `config.md` section 6. Always exit 0 |
| `restore --yes` | Undo the latest install or update (lists files first); can step back further |
| `relink [--python "py -3"]` | After moving to another machine, rewrite the hook interpreter and rebuild `local.json` |
| `codex-review [--detach] [--print]` | Start a Codex review of the latest handoff in a workspace sandbox. Log goes to `.ai-review/.cache/codex-<H>.log`, a `.done` file is written at the end. Passes `AI_REVIEW_PYTHON`, `SystemDrive` and similar variables into the sandbox with `-c` (this run only; Codex config is not changed). After the review it compares the workspace and warns about files that appeared or changed; it never deletes them |
| `ignore-check [--json]` | Read-only check that `.gitignore` excludes a standard list of 15 secret patterns (`.env`, keys and certificates, `.claude/projects/` transcripts, `*.jsonl`, `memory/`, …). Each rule is tested with several sample paths through git itself. Lists tracked files that match (paths only, never contents). A reminder, not a gate: **never edits `.gitignore`**, exit 0 on gaps |
| `pack` | Build an offline zip in `dist/` |
| `check-update --url <URL of a VERSION file>` | Compare version numbers only; never updates by itself. Without network it says "update not checked" |

## Day to day

| When | Do |
|---|---|
| Once per new project | `/safety-setup` |
| A change is complete | `/review-ready` |
| Independent review | Nothing: `/review-ready` starts Codex in the background and reports when done. To run Codex yourself, see `docs/codex-start.md` |
| The review asks for fixes | `/review-fix R-<id>` |
| Before merge or deploy | `py -3 .ai-review/kit/kit.py gate` |
| Check the state | `py -3 .ai-review/kit/kit.py status` |
| After install or a machine move | `py -3 .ai-review/kit/kit.py doctor` |

## Updating across machines

- Keep the central copy somewhere you control (this git repo, or a zip made by `pack`).
- Each project records the version it uses (`.ai-review/kit-version.json`).
- Always run `update --source … --preview` first, then `update --source …`. The kit never overwrites the whole `.claude/` or `.codex/` folder and never touches sign-in data, chat transcripts, keys or project data.
- On a machine without access to this repo, copy the zip over and run `install --source <zip>`. The tool uploads nothing. See `docs/offline-setup.md`.

## Limits (honest version)

- Hooks only make mechanical checks (version, fingerprint match, open items). They do not scan code, do not call another AI, and cannot block a push or a deploy.
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
- Fingerprints can differ between CI and a local machine when `core.autocrlf` settings differ. If that happens, trust the local result and disable gate in CI.

## Tests

```
py -3 tools/tests/test_kit.py
```

Builds several test projects in a temporary folder and covers: fresh install; keeping existing CLAUDE.md / AGENTS.md / settings.json; no duplicate blocks on reinstall; preview lists every file a real install writes; fingerprints never write to the project's git object store; `codex-review` command shape, environment, refusal cases, `-c` sandbox settings and warnings about new files (fake codex); update conflicts are not overwritten; restore; code changes make a review stale; hooks do not loop or repeat; clear check results; offline zip install; non-git projects; check-update without network; `ignore-check` (all missing / all present / partial / negation rules / local-only excludes / tracked files listed by path only / accepted entries / read-only / non-git); "initialized" requires meta plus check commands; `state --no-write` writes nothing; section 6 status column in old and new formats; `doctor` (fake codex and PATH, never triggers sign-in, read-only); `state.json` kept out of version control (reminder only, index untouched). The temporary folders are not deleted automatically.

## License

MIT. See [LICENSE](LICENSE).
