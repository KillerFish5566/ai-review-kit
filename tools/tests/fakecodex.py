#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測試用的假 codex：記下收到的參數與環境，依 FAKE_CODEX_MODE 決定要不要寫審查報告。
review（預設）＝寫一份 codex 審查 no-blocking-found；noreport＝什麼都不寫、exit 1。"""
import json
import os
import sys
from pathlib import Path

argv = sys.argv[1:]
target = Path(argv[argv.index("-C") + 1]) if "-C" in argv else Path.cwd()
cache = target / ".ai-review" / ".cache"
cache.mkdir(parents=True, exist_ok=True)
(cache / "fake-record.json").write_text(json.dumps({
    "argv": argv, "cwd": os.getcwd(),
    "env": {k: os.environ.get(k) for k in ("TMP", "TEMP", "TMPDIR", "AI_REVIEW_PYTHON")},
}, ensure_ascii=False), encoding="utf-8")
print("fake codex running")
if os.environ.get("FAKE_CODEX_MODE") == "noreport":
    sys.exit(1)
hid = argv[-1].split()[-1]
hfile = target / ".ai-review" / "handoffs" / f"{hid}.md"
tgt = next(l.split(":", 1)[1].strip() for l in hfile.read_text(encoding="utf-8").splitlines() if l.startswith("target:"))
rid = "R-20990101-0000"
(target / ".ai-review" / "reviews" / f"{rid}.md").write_text(
    f"---\nkind: review\nid: {rid}\ncreated: 2099-01-01 00:00\nhandoff: {hid}\ntarget: {tgt}\n"
    f"reviewer: codex\nverdict: no-blocking-found\nblocking: 0\n---\n\n# {rid}\n", encoding="utf-8")
sys.exit(0)
