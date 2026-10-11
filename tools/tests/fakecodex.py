#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測試用的假 codex：記下收到的參數與環境，依 FAKE_CODEX_MODE 決定要不要寫審查報告。
review（預設）＝寫一份 codex 審查 no-blocking-found；noreport＝什麼都不寫、exit 1；
dirty＝照常寫報告，另外在專案根目錄留一個字面名稱的 %SystemDrive% 資料夾（模擬 2026-10-11 沙箱弄髒工作區；
FAKE_CODEX_JUNK 可換資料夾名）。
`mcp get <名稱> --json`：FAKE_CODEX_MCP=none 時回「沒有這個伺服器」（exit 1），否則回一份假的 node_repl 設定。"""
import json
import os
import sys
from pathlib import Path

argv = sys.argv[1:]
if argv[:2] == ["mcp", "get"]:
    if os.environ.get("FAKE_CODEX_MCP") == "none" or argv[2] != "node_repl":
        print(f"Error: No MCP server named '{argv[2]}' found.", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"name": "node_repl", "enabled": True, "transport": {
        "type": "stdio", "command": "node_repl.exe", "args": [], "cwd": None,
        "env": {"NODE_REPL_UNTRUSTED_ENV_ALLOWLIST": "CODEX_WINDOWS_REGISTERED_CORE", "OTHER": "1"},
        "env_vars": ["CODEX_WINDOWS_REGISTERED_CORE"]}}))
    sys.exit(0)

target = Path(argv[argv.index("-C") + 1]) if "-C" in argv else Path.cwd()
cache = target / ".ai-review" / ".cache"
cache.mkdir(parents=True, exist_ok=True)
(cache / "fake-record.json").write_text(json.dumps({
    "argv": argv, "cwd": os.getcwd(),
    "env": {k: os.environ.get(k) for k in ("TMP", "TEMP", "TMPDIR", "AI_REVIEW_PYTHON")},
}, ensure_ascii=False), encoding="utf-8")
print("fake codex running")
mode = os.environ.get("FAKE_CODEX_MODE")
if mode == "noreport":
    sys.exit(1)
if mode == "dirty":
    junk = target / os.environ.get("FAKE_CODEX_JUNK", "%SystemDrive%") / "ProgramData" / "Microsoft" / "Windows" / "Caches"
    junk.mkdir(parents=True, exist_ok=True)
    (junk / "cversions.2.db").write_bytes(b"\0" * 64)
hid = argv[-1].split()[-1]
hfile = target / ".ai-review" / "handoffs" / f"{hid}.md"
tgt = next(l.split(":", 1)[1].strip() for l in hfile.read_text(encoding="utf-8").splitlines() if l.startswith("target:"))
rid = "R-20990101-0000" if mode != "dirty" else ("R-20990101-0002" if os.environ.get("FAKE_CODEX_JUNK") else "R-20990101-0001")
(target / ".ai-review" / "reviews" / f"{rid}.md").write_text(
    f"---\nkind: review\nid: {rid}\ncreated: 2099-01-01 00:00\nhandoff: {hid}\ntarget: {tgt}\n"
    f"reviewer: codex\nverdict: no-blocking-found\nblocking: 0\n---\n\n# {rid}\n", encoding="utf-8")
sys.exit(0)
