#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai-review-kit 自動化驗證（在暫存資料夾建立測試專案，不碰真實專案）。

執行：py -3 tools/tests/test_kit.py [--keep] [--dir <暫存根目錄>]
每個情境印 PASS / FAIL；任一 FAIL 則 exit 1。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
KIT_ROOT = HERE.parent.parent
KIT_PY = KIT_ROOT / "tools" / "kit.py"
PY = sys.executable
ENV = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
RESULTS = []


def sh(cmd, cwd=None, input_text=None, env=None):
    cp = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, input=input_text,
                        env=env or ENV, timeout=300)
    return cp.returncode, cp.stdout.decode("utf-8", "replace"), cp.stderr.decode("utf-8", "replace")


def kit(*args, cwd=None, input_text=None, script=None):
    return sh([PY, str(script or KIT_PY), *args], cwd=cwd, input_text=input_text)


def git(*args, cwd):
    return sh(["git", *args], cwd=cwd, env=dict(ENV, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
                                             GIT_COMMITTER_EMAIL="t@x"))


def read(p):
    return Path(p).read_text(encoding="utf-8-sig")


def write(p, s):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:   # 照字面寫，不做平台換行轉換
        f.write(s)


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (("  — " + detail) if (detail and not cond) else ""))


def new_git_project(root, name):
    p = root / name
    p.mkdir(parents=True)
    git("init", "-q", cwd=p)
    git("config", "user.email", "t@x", cwd=p)
    git("config", "user.name", "t", cwd=p)
    write(p / "app.py", "def add(a, b):\n    return a + b\n")
    write(p / "README.md", "# demo\n")
    git("add", "-A", cwd=p)
    git("commit", "-q", "-m", "init", cwd=p)
    return p


def front(id_, kind, **kv):
    lines = ["---", f"kind: {kind}", f"id: {id_}", "created: 2026-09-18 12:00"]
    for k, v in kv.items():
        lines.append(f"{k}: {v}")
    lines += ["---", "", f"# {id_}", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--dir")
    a = ap.parse_args()
    root = Path(a.dir) if a.dir else Path(tempfile.mkdtemp(prefix="ai-review-kit-test-"))
    root.mkdir(parents=True, exist_ok=True)
    print(f"測試根目錄：{root}")

    # ---------------- T1 新專案安裝
    p1 = new_git_project(root, "p1-new")
    rc, out, err = kit("install", "--target", str(p1))
    check("T1 install exit 0", rc == 0, err[-500:])
    must = [".ai-review/kit/workflow.md", ".ai-review/kit/kit.py", ".ai-review/kit/VERSION",
            ".ai-review/kit/templates/config.md", ".ai-review/kit/docs/codex-start.md",
            ".claude/skills/safety-setup/SKILL.md", ".claude/skills/review-ready/SKILL.md",
            ".claude/skills/review-fix/SKILL.md", ".agents/skills/independent-review/SKILL.md",
            "CLAUDE.md", "AGENTS.md", ".claude/settings.json", ".codex/hooks.json", ".gitignore",
            ".ai-review/kit-version.json", ".ai-review/state.json", ".ai-review/handoffs/.gitkeep"]
    missing = [m for m in must if not (p1 / m).exists()]
    check("T1 所有檔案存在", not missing, str(missing))
    s = json.loads(read(p1 / ".claude/settings.json"))
    ours = lambda ev: [g for g in s.get("hooks", {}).get(ev, []) if ".ai-review/kit/kit.py" in json.dumps(g).replace("\\\\", "/")]
    check("T1 settings.json 有 SessionStart 與 Stop 各一條", len(ours("SessionStart")) == 1 and len(ours("Stop")) == 1)
    check("T1 hook 用 exec 形式（command+args）", "args" in s["hooks"]["SessionStart"][0]["hooks"][0])
    c = read(p1 / "CLAUDE.md")
    check("T1 CLAUDE.md 有管理區塊", c.count("ai-review-kit:begin") == 1 and c.count("ai-review-kit:end") == 1)
    gi = read(p1 / ".gitignore")
    check("T1 .gitignore 加了 .cache 與 .backup", ".ai-review/.cache/" in gi and ".ai-review/.backup/" in gi)
    st = json.loads(read(p1 / ".ai-review/state.json"))
    check("T1 初始狀態 not-ready 且未初始化", st["status"] == "not-ready" and st["initialized"] is False)

    # ---------------- T2 既有檔案保留
    p2 = new_git_project(root, "p2-existing")
    write(p2 / "CLAUDE.md", "# my rules\r\n- keep me\r\n")
    write(p2 / "AGENTS.md", "custom agents text\n")
    write(p2 / ".claude/settings.json", json.dumps({
        "permissions": {"allow": ["Bash(ls)"]},
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}],
                  "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": "echo start"}]}]}}, indent=2))
    write(p2 / ".gitignore", "node_modules/\n")
    write(p2 / ".codex/hooks.json", json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "echo u"}]}]}}))
    rc, out, err = kit("install", "--target", str(p2))
    check("T2 install exit 0", rc == 0, err[-500:])
    c = read(p2 / "CLAUDE.md")
    check("T2 CLAUDE.md 原內容保留＋區塊附加", c.startswith("# my rules") and "keep me" in c and "ai-review-kit:begin" in c)
    raw = (p2 / "CLAUDE.md").read_bytes()
    check("T2 CLAUDE.md 保留 CRLF", b"\r\n" in raw and b"ai-review-kit:end -->\r\n" in raw)
    ag = read(p2 / "AGENTS.md")
    check("T2 AGENTS.md 原內容保留", ag.startswith("custom agents text") and "ai-review-kit:begin" in ag)
    s = json.loads(read(p2 / ".claude/settings.json"))
    check("T2 settings.json 保留 permissions 與既有 hooks",
          s.get("permissions", {}).get("allow") == ["Bash(ls)"]
          and any("echo hi" in json.dumps(g) for g in s["hooks"]["PreToolUse"])
          and any("echo start" in json.dumps(g) for g in s["hooks"]["SessionStart"])
          and sum(1 for g in s["hooks"]["SessionStart"] if "kit.py" in json.dumps(g)) == 1)
    cx = json.loads(read(p2 / ".codex/hooks.json"))
    check("T2 codex hooks.json 保留既有條目", "UserPromptSubmit" in cx["hooks"] and "SessionStart" in cx["hooks"])
    gi = read(p2 / ".gitignore")
    check("T2 .gitignore 保留 node_modules", gi.startswith("node_modules/") and ".ai-review/.cache/" in gi)
    check("T2 備份存在", any((p2 / ".ai-review/.backup").glob("*/CLAUDE.md")))

    # ---------------- T3 重複安裝不重複插入
    before = {p: Path(p1 / p).read_bytes() for p in must if (p1 / p).is_file() and "state.json" not in p and "kit-version" not in p}
    rc, out, err = kit("install", "--target", str(p1))
    check("T3 第二次 install exit 0", rc == 0, err[-300:])
    after = {p: Path(p1 / p).read_bytes() for p in before}
    check("T3 檔案內容完全相同", before == after, str([p for p in before if before[p] != after[p]]))
    c = read(p1 / "CLAUDE.md")
    check("T3 區塊只有一個", c.count("ai-review-kit:begin") == 1)
    s = json.loads(read(p1 / ".claude/settings.json"))
    check("T3 hook 條目沒有重複", len(ours("SessionStart")) == 1 and len(ours("Stop")) == 1)
    m = json.loads(read(p1 / ".ai-review/kit-version.json"))
    check("T3 manifest runs 記了兩次", len(m["runs"]) == 2)

    # ---------------- T4 更新：三方比對
    src2 = root / "kit-src-v2"
    shutil.copytree(KIT_ROOT, src2, ignore=shutil.ignore_patterns(".git", "__pycache__", "dist", "tests"))
    write(src2 / "VERSION", "0.1.1\n")
    write(src2 / "core/workflow.md", read(src2 / "core/workflow.md") + "\n<!-- 來源新增的一行 -->\n")
    write(src2 / "core/review-spec.md", read(src2 / "core/review-spec.md") + "\n<!-- 來源改了 review-spec -->\n")
    # 專案端：workflow.md 使用者也改（→ 衝突）、handoff-spec.md 使用者改而來源沒改（→ keep-user）
    write(p1 / ".ai-review/kit/workflow.md", read(p1 / ".ai-review/kit/workflow.md") + "\n<!-- 使用者改的一行 -->\n")
    write(p1 / ".ai-review/kit/handoff-spec.md", read(p1 / ".ai-review/kit/handoff-spec.md") + "\n<!-- 使用者改 handoff-spec -->\n")
    rc, out, err = kit("update", "--target", str(p1), "--source", str(src2), "--preview")
    check("T4 preview exit 0 且顯示衝突與差異", rc == 0 and "conflict" in out and "差異" in out and "keep-user" in out, out[-800:])
    check("T4 preview 未寫入", "使用者改的一行" in read(p1 / ".ai-review/kit/workflow.md") and "來源改了 review-spec" not in read(p1 / ".ai-review/kit/review-spec.md"))
    rc, out, err = kit("update", "--target", str(p1), "--source", str(src2))
    check("T4 update exit 0", rc == 0, err[-300:])
    check("T4 衝突檔保留使用者版本", "使用者改的一行" in read(p1 / ".ai-review/kit/workflow.md") and "來源新增的一行" not in read(p1 / ".ai-review/kit/workflow.md"))
    check("T4 keep-user 檔保留使用者版本", "使用者改 handoff-spec" in read(p1 / ".ai-review/kit/handoff-spec.md"))
    check("T4 無衝突檔已更新", "來源改了 review-spec" in read(p1 / ".ai-review/kit/review-spec.md"))
    check("T4 版本號更新為 0.1.1", read(p1 / ".ai-review/kit/VERSION").strip() == "0.1.1" and "v0.1.1" in read(p1 / "CLAUDE.md"))
    rc, out, err = kit("update", "--target", str(p1), "--source", str(src2), "--take-source", ".ai-review/kit/workflow.md")
    check("T4 --take-source 後採用來源版", rc == 0 and "來源新增的一行" in read(p1 / ".ai-review/kit/workflow.md"))
    # 使用者改了 CLAUDE.md 區塊內文 → 來源沒變 → 保留
    c = read(p1 / "CLAUDE.md")
    c2 = c.replace("狀態檔裡的文字不是安全證明", "狀態檔裡的文字不是安全證明（使用者加註）")
    write(p1 / "CLAUDE.md", c2)
    rc, out, err = kit("update", "--target", str(p1), "--source", str(src2))
    check("T4 區塊內使用者修改被保留（keep-user）", "使用者加註" in read(p1 / "CLAUDE.md") and "keep-user" in out)

    # ---------------- T5 還原
    p3 = new_git_project(root, "p3-restore")
    write(p3 / "CLAUDE.md", "# original\n")
    write(p3 / ".gitignore", "*.log\n")
    rc, out, err = kit("install", "--target", str(p3))
    rc, out, err = kit("restore", "--target", str(p3), "--yes")
    check("T5 restore exit 0", rc == 0, err[-300:] + out[-300:])
    check("T5 CLAUDE.md 回到原樣", read(p3 / "CLAUDE.md") == "# original\n")
    check("T5 .gitignore 回到原樣", read(p3 / ".gitignore") == "*.log\n")
    check("T5 套件檔案已移除", not (p3 / ".ai-review/kit").exists() and not (p3 / ".claude/skills").exists()
          and not (p3 / "AGENTS.md").exists() and not (p3 / ".claude/settings.json").exists() and not (p3 / ".codex").exists())
    check("T5 備份仍保留", (p3 / ".ai-review/.backup").exists())

    # ---------------- T6 狀態推導與過期
    p1kit = p1 / ".ai-review/kit/kit.py"
    shutil.copy(KIT_ROOT / "templates/config.md", p1 / ".ai-review/config.md")
    rc, out, err = kit("snapshot", "--json", cwd=p1, script=p1kit)
    check("T6 snapshot exit 0", rc == 0, err[-300:])
    snap = json.loads(out)
    check("T6 snapshot 有 id/target/snapshot_ref", snap["id"].startswith("H-") and len(snap["target"]) == 40 and snap["snapshot_ref"].startswith("refs/ai-review/"))
    rc, out, err = git("rev-parse", "--verify", snap["snapshot_ref"], cwd=p1)
    check("T6 快照參照真的存在於 git", rc == 0)
    rc, out, err = git("diff", "--stat", "HEAD", snap["snapshot_ref"], cwd=p1)
    check("T6 快照可 diff（含 .ai-review 以外的未提交檔）", rc == 0)
    H = snap["id"]
    write(p1 / f".ai-review/handoffs/{H}.md", front(H, "handoff", target=snap["target"], snapshot_ref=snap["snapshot_ref"], head=snap["head"], base=snap["base"], recheck_of="", scope="test"))
    rc, out, err = kit("state", "--json", cwd=p1, script=p1kit)
    st = json.loads(out)
    check("T6 有交接無審查 → pending-review", st["status"] == "pending-review" and st["fresh"] is True, out[-300:])
    # 自查不算
    write(p1 / ".ai-review/reviews/R-20260918-0001.md", front("R-20260918-0001", "review", handoff=H, target=snap["target"], reviewer="claude", verdict="no-blocking-found", blocking=0))
    rc, out, err = kit("state", "--json", cwd=p1, script=p1kit)
    st = json.loads(out)
    check("T6 開發 AI 自查不算獨立審查", st["status"] == "pending-review" and any("不算獨立審查" in n for n in st["notes"]))
    # 真正的審查
    write(p1 / ".ai-review/reviews/R-20260918-0002.md", front("R-20260918-0002", "review", handoff=H, target=snap["target"], reviewer="codex", verdict="no-blocking-found", blocking=0))
    rc, out, err = kit("state", "--json", cwd=p1, script=p1kit)
    st = json.loads(out)
    check("T6 獨立審查 no-blocking-found → 狀態 no-blocking-found（寫報告不會讓指紋過期）", st["status"] == "no-blocking-found" and st["fresh"] is True, out[-400:])
    rc, out, err = kit("gate", cwd=p1, script=p1kit)
    check("T6 gate 通過 exit 0", rc == 0, out[-300:])
    rc, out, err = kit("verify", cwd=p1, script=p1kit)
    check("T6 verify 相符 exit 0", rc == 0)
    # 程式碼變更 → 過期
    write(p1 / "app.py", read(p1 / "app.py") + "\ndef sub(a, b):\n    return a - b\n")
    rc, out, err = kit("state", "--json", cwd=p1, script=p1kit)
    st = json.loads(out)
    check("T6 程式碼變更後 → not-ready 且註明過期", st["status"] == "not-ready" and st["fresh"] is False and any("不再適用" in n for n in st["notes"]), out[-400:])
    rc, out, err = kit("gate", cwd=p1, script=p1kit)
    check("T6 過期後 gate exit 1", rc == 1)
    rc, out, err = kit("verify", cwd=p1, script=p1kit)
    check("T6 過期後 verify exit 1", rc == 1)
    # needs-fix 與複查
    rc, out, err = kit("snapshot", "--json", cwd=p1, script=p1kit)
    snap2 = json.loads(out)
    H2 = snap2["id"]
    write(p1 / f".ai-review/handoffs/{H2}.md", front(H2, "handoff", target=snap2["target"], snapshot_ref=snap2["snapshot_ref"], head=snap2["head"], base=snap2["base"], recheck_of="", scope="t2"))
    write(p1 / ".ai-review/reviews/R-20260918-0003.md", front("R-20260918-0003", "review", handoff=H2, target=snap2["target"], reviewer="codex", verdict="needs-fix", blocking=2))
    rc, out, err = kit("state", "--json", cwd=p1, script=p1kit)
    st = json.loads(out)
    check("T6 needs-fix 推導正確且列未結案", st["status"] == "needs-fix" and any("review-fix" in o for o in st["open_items"]))
    time.sleep(1)
    write(p1 / "app.py", read(p1 / "app.py") + "# fixed\n")
    rc, out, err = kit("snapshot", "--json", cwd=p1, script=p1kit)
    snap3 = json.loads(out)
    H3 = snap3["id"]
    write(p1 / f".ai-review/handoffs/{H3}.md", front(H3, "handoff", target=snap3["target"], snapshot_ref=snap3["snapshot_ref"], head=snap3["head"], base=snap3["base"], recheck_of="R-20260918-0003", scope="fix"))
    write(p1 / ".ai-review/fixes/F-20260918-0001.md", front("F-20260918-0001", "fix", review="R-20260918-0003", handoff=H3))
    rc, out, err = kit("state", "--json", cwd=p1, script=p1kit)
    st = json.loads(out)
    check("T6 修正後重交 → pending-recheck", st["status"] == "pending-recheck" and st["fix"]["id"] == "F-20260918-0001", out[-400:])
    check("T6 交接編號同一分鐘不撞號", H2 != H3 and H != H2)
    check("T6 .ai-review 不計入指紋（未追蹤報告檔不改變指紋）", snap3["target"] == kit("fingerprint", cwd=p1, script=p1kit)[1].split()[0])

    # ---------------- T7 hooks
    t0 = time.time()
    rc, out, err = kit("hook", "session-start", cwd=p1, script=p1kit, input_text=json.dumps({"session_id": "x", "hook_event_name": "SessionStart", "cwd": str(p1)}).encode())
    dt = time.time() - t0
    check("T7 session-start 有輸出且 <5 秒", rc == 0 and "[ai-review-kit v" in out and "待複查" in out and dt < 5, f"{dt:.1f}s {out[-300:]} {err[-200:]}")
    # 目前 p1 狀態新鮮 → stop 不輸出
    rc, out, err = kit("hook", "stop", cwd=p1, script=p1kit, input_text=b'{"stop_hook_active": false}')
    check("T7 stop 在狀態新鮮時不輸出", rc == 0 and out.strip() == "", out)
    write(p1 / "app.py", read(p1 / "app.py") + "# change again\n")
    rc, out, err = kit("hook", "stop", cwd=p1, script=p1kit, input_text=b'{"stop_hook_active": false}')
    check("T7 stop 在過期時輸出 systemMessage", rc == 0 and out.strip().startswith("{") and "systemMessage" in out and "已過期" in out, out[-300:])
    rc, out2, err = kit("hook", "stop", cwd=p1, script=p1kit, input_text=b'{"stop_hook_active": false}')
    check("T7 stop 同一指紋第二次不再輸出（防重複）", rc == 0 and out2.strip() == "", out2)
    (p1 / ".ai-review/.cache/stop-warned.txt").unlink()
    rc, out3, err = kit("hook", "stop", cwd=p1, script=p1kit, input_text=b'{"stop_hook_active": true}')
    check("T7 stop_hook_active=true 時不輸出（防迴圈）", rc == 0 and out3.strip() == "", out3)
    rc, out4, err = kit("hook", "stop", cwd=p1, script=p1kit, input_text=b'not json')
    check("T7 壞的 stdin 不會讓 hook 崩潰", rc == 0)
    check("T7 hook 從不回傳 decision:block", "block" not in out and "block" not in out2)

    # ---------------- T8 checks --run
    cfg = read(p1 / ".ai-review/config.md").replace("```checks\nname | command | required\n```",
                                                    "```checks\nname | command | required\nok | echo ok | yes\nmissing | definitely-not-a-command-xyz123 | no\nbad | exit 3 | yes\n```")
    write(p1 / ".ai-review/config.md", cfg)
    rc, out, err = kit("checks", "--run", "--handoff", "T8", cwd=p1, script=p1kit)
    res = json.loads(read(p1 / ".ai-review/.cache/checks-T8.json"))["results"]
    by = {r["name"]: r["result"] for r in res}
    check("T8 checks 結果 pass/skipped/fail 分明", by == {"ok": "pass", "missing": "skipped", "bad": "fail"}, str(by) + err[-200:])
    check("T8 必要檢查未通過有計數", "必要檢查未通過：1" in out, out[-200:])

    # ---------------- T9 pack 與 zip 安裝
    rc, out, err = kit("pack", "--out", str(root / "dist"))
    zips = list((root / "dist").glob("ai-review-kit-*.zip"))
    check("T9 pack 產生 zip", rc == 0 and len(zips) == 1, err[-300:])
    p4 = new_git_project(root, "p4-zip")
    rc, out, err = kit("install", "--target", str(p4), "--source", str(zips[0]))
    check("T9 從 zip 安裝成功", rc == 0 and (p4 / ".ai-review/kit/workflow.md").exists(), err[-300:])

    # ---------------- T10 非 git 專案
    p5 = root / "p5-nogit"
    p5.mkdir()
    write(p5 / "main.py", "print(1)\n")
    rc, out, err = kit("install", "--target", str(p5))
    rc, out, err = kit("fingerprint", "--target", str(p5))
    check("T10 非 git 專案指紋為 sha256: 前綴", rc == 0 and out.startswith("sha256:"), out)
    rc, out, err = kit("snapshot", "--json", "--target", str(p5))
    check("T10 非 git snapshot 可用（無 snapshot_ref）", rc == 0 and json.loads(out)["snapshot_ref"] is None, err[-200:])

    # ---------------- T11 check-update
    rc, out, err = kit("check-update", "--target", str(p1))
    check("T11 沒有 URL → 如實顯示未檢查更新", rc == 0 and "未檢查更新" in out)
    rc, out, err = kit("check-update", "--target", str(p1), "--url", "http://127.0.0.1:9/VERSION")
    check("T11 連不上 → 如實顯示且不阻止使用", rc == 0 and "無法連線" in out)

    # ---------------- T12 relink 與 status
    rc, out, err = kit("relink", "--target", str(p1), "--python", "py -3")
    s = json.loads(read(p1 / ".claude/settings.json"))
    h = s["hooks"]["SessionStart"][-1]["hooks"][0]
    check("T12 relink 改寫直譯器（py -3）", rc == 0 and h["command"] == "py" and h["args"][0] == "-3", json.dumps(h))
    rc, out, err = kit("status", "--target", str(p1))
    check("T12 status 可讀且列出 hooks/skills", rc == 0 and "Skills" in out and "狀態：" in out, out[-400:])

    loc = json.loads(read(p1 / ".ai-review/local.json"))
    check("T12 relink 把直譯器記在 local.json、manifest 不再有", loc["python"] == "py" and loc["python_args"] == ["-3"]
          and "python" not in json.loads(read(p1 / ".ai-review/kit-version.json")), json.dumps(loc))

    # ---------------- T13 進版控的檔不含本機路徑（0.1.1）
    home = str(Path.home())
    p6 = new_git_project(root, "p6-portable")
    rc, out, err = kit("install", "--target", str(p6))
    tracked = [".ai-review/kit-version.json", ".claude/settings.json", ".codex/hooks.json"]
    leaks = [t for t in tracked
             if home.lower() in read(p6 / t).lower().replace("\\\\", "\\") or str(p6).lower() in read(p6 / t).lower().replace("\\\\", "\\")]
    check("T13 manifest／settings／codex hooks 不含家目錄或專案絕對路徑", rc == 0 and not leaks, str(leaks))
    s = json.loads(read(p6 / ".claude/settings.json"))
    args0 = s["hooks"]["SessionStart"][0]["hooks"][0]["args"]
    check("T13 hook 用 ${CLAUDE_PROJECT_DIR} 指 kit.py", "${CLAUDE_PROJECT_DIR}/.ai-review/kit/kit.py" in args0, json.dumps(args0))
    m = json.loads(read(p6 / ".ai-review/kit-version.json"))
    check("T13 manifest 不含 python／source", not ({"python", "python_args", "source"} & set(m)), str(list(m)))
    check("T13 local.json 存在且被 .gitignore 排除",
          (p6 / ".ai-review/local.json").exists() and ".ai-review/local.json" in read(p6 / ".gitignore"))
    rc, out, err = git("check-ignore", ".ai-review/local.json", cwd=p6)
    check("T13 git 確認 local.json 被忽略", rc == 0, out + err)
    rc, out, err = kit("status", "--target", str(p6))
    check("T13 status 讀 local.json 的直譯器", rc == 0 and "直譯器：" in out and "找不到" not in out, out[-300:])

    # ---------------- T14 從 0.1.0 的安裝紀錄升級（舊欄位搬走、不沿用自動記下的絕對路徑）
    p7 = new_git_project(root, "p7-migrate")
    rc, out, err = kit("install", "--target", str(p7))
    mp = p7 / ".ai-review/kit-version.json"
    m = json.loads(read(mp))
    m.update({"python": sys.executable, "python_args": [], "source": str(KIT_ROOT)})
    write(mp, json.dumps(m, ensure_ascii=False, indent=2))
    (p7 / ".ai-review/local.json").unlink()
    write(p7 / ".gitignore", read(p7 / ".gitignore").replace(".ai-review/local.json\n", ""))   # 模擬 0.1.0 的 .gitignore
    rc, out, err = kit("update", "--target", str(p7))
    m = json.loads(read(mp))
    loc = json.loads(read(p7 / ".ai-review/local.json"))
    h = json.loads(read(p7 / ".claude/settings.json"))["hooks"]["SessionStart"][0]["hooks"][0]
    check("T14 升級後舊欄位搬到 local.json", rc == 0 and not ({"python", "source"} & set(m)) and loc.get("source"), err[-300:])
    gi = read(p7 / ".gitignore")
    check("T14 .gitignore 補新行時不重複標題", gi.count("# ai-review-kit") == 1 and ".ai-review/local.json" in gi, gi)
    check("T14 不沿用 0.1.0 自動記下的絕對路徑", h["command"] != sys.executable or not Path(sys.executable).is_relative_to(Path.home()),
          json.dumps(h))

    # ---------------- T15 restore 會一併移除本次新建的 local.json
    p8 = new_git_project(root, "p8-restore-local")
    kit("install", "--target", str(p8))
    rc, out, err = kit("restore", "--target", str(p8), "--yes")
    check("T15 restore 安裝後 local.json 也移除", rc == 0 and not (p8 / ".ai-review/local.json").exists(), out[-300:])

    # ---------------- T16 install --preview 要列出實裝會寫的每一個檔（含 hook、設定、佔位、紀錄檔）
    p9 = new_git_project(root, "p9-preview-complete")
    write(p9 / ".gitignore", "node_modules/\n")

    def snapshot(d):
        return {f.relative_to(d).as_posix(): f.read_bytes() for f in d.rglob("*")
                if f.is_file() and ".git" not in f.relative_to(d).parts[:1]}

    before = snapshot(p9)
    rc, out, err = kit("install", "--target", str(p9), "--preview")
    check("T16 preview 未寫入任何檔", rc == 0 and snapshot(p9) == before, err[-300:])
    listed = set(re.findall(r"^\| (\S+) \| [^|]+\|\s*$", out, re.M)) - {"項目"}
    kit("install", "--target", str(p9))
    after = snapshot(p9)
    touched = {p for p in after if p not in before or after[p] != before[p]}
    touched = {p for p in touched if not p.startswith(".ai-review/.backup/")}   # 備份是安裝的副產品，不是變更對象
    check("T16 實裝寫入的檔全部出現在預覽", touched <= listed, str(sorted(touched - listed)))
    for key in (".claude/settings.json", ".codex/hooks.json", ".gitignore", ".ai-review/local.json",
                ".ai-review/kit-version.json", ".ai-review/state.json", ".ai-review/reviews/.gitkeep"):
        if key not in listed:
            check(f"T16 預覽列出 {key}", False, out[-600:])
    check("T16 預覽附 hook 內容差異", "差異：.claude/settings.json" in out, out[-600:])

    # ---------------- T17 指紋不寫進專案的 git 物件庫（Codex 沙箱不准寫 .git 也能算）（0.2.0）
    p10 = new_git_project(root, "p10-codex-review")
    kit("install", "--target", str(p10))
    p10kit = p10 / ".ai-review/kit/kit.py"
    write(p10 / "new_untracked.py", "print('not yet in any object store')\n")

    def loose_objects(d):
        return sorted(str(f) for f in (d / ".git/objects").rglob("*") if f.is_file() and len(f.parent.name) == 2)

    before = loose_objects(p10)
    rc, fp1, err = kit("fingerprint", cwd=p10, script=p10kit)
    check("T17 fingerprint 不新增 .git/objects 裡的物件", rc == 0 and loose_objects(p10) == before, err[-300:])
    rc, out, err = kit("snapshot", "--json", cwd=p10, script=p10kit)
    snap = json.loads(out) if rc == 0 else {}
    check("T17 snapshot 指紋與 fingerprint 相同、快照參照照建",
          snap.get("target") == fp1.strip() and (snap.get("snapshot_ref") or "").startswith("refs/ai-review/"), out[-300:] + err[-300:])

    # ---------------- T18 codex-review：命令形狀、環境、紀錄、拒絕條件（用假 codex）（0.2.0）
    shutil.copy(KIT_ROOT / "templates/config.md", p10 / ".ai-review/config.md")
    H = snap["id"]
    write(p10 / f".ai-review/handoffs/{H}.md", front(H, "handoff", target=snap["target"], snapshot_ref=snap["snapshot_ref"],
                                                       head=snap["head"], base=snap["base"], recheck_of="", scope="t18"))
    fake_py = HERE / "fakecodex.py"
    if os.name == "nt":
        fake = root / "fakecodex.cmd"
        write(fake, f'@"{PY}" "{fake_py}" %*\r\n')
    else:
        fake = root / "fakecodex"
        write(fake, f'#!/bin/sh\nexec "{PY}" "{fake_py}" "$@"\n')
        fake.chmod(0o755)
    rc, out, err = kit("codex-review", "--print", "--codex", str(fake), cwd=p10, script=p10kit)
    check("T18 --print 列出工作區沙箱命令、不含繞過旗標與 -m",
          rc == 0 and "-s workspace-write" in out and "bypass" not in out and " -m " not in out
          and f"$independent-review {H}" in out, out[-500:] + err[-300:])
    rc, out, err = kit("codex-review", "--codex", str(root / "no-such-codex.exe"), cwd=p10, script=p10kit)
    check("T18 找不到 codex → exit 3 並給手動退路", rc == 3 and "codex-start.md" in out, out[-300:])
    rc, out, err = kit("codex-review", "--codex", str(fake), cwd=p10, script=p10kit)
    rec = json.loads(read(p10 / ".ai-review/.cache/fake-record.json")) if (p10 / ".ai-review/.cache/fake-record.json").exists() else {}
    done = json.loads(read(p10 / f".ai-review/.cache/codex-{H}.done")) if (p10 / f".ai-review/.cache/codex-{H}.done").exists() else {}
    check("T18 跑完 exit 0、.done 記下審查編號與結論",
          rc == 0 and done.get("review") == "R-20990101-0000" and done.get("verdict") == "no-blocking-found" and done.get("exit") == 0,
          out[-400:] + err[-300:] + json.dumps(done))
    argv = rec.get("argv", [])
    check("T18 假 codex 收到 exec -C <專案> -s workspace-write 與交接編號",
          argv[:1] == ["exec"] and "-C" in argv and Path(argv[argv.index("-C") + 1]).resolve() == p10.resolve()
          and argv[argv.index("-s") + 1] == "workspace-write" and argv[-1] == f"$independent-review {H}", json.dumps(argv))
    tmpdir = (p10 / ".ai-review/.cache/tmp").resolve()
    envr = rec.get("env", {})
    check("T18 TMP／TEMP 指到 .ai-review/.cache/tmp、AI_REVIEW_PYTHON 是實體檔",
          all(envr.get(k) and Path(envr[k]).resolve() == tmpdir for k in ("TMP", "TEMP"))
          and envr.get("AI_REVIEW_PYTHON") and Path(envr["AI_REVIEW_PYTHON"]).is_file(), json.dumps(envr))
    check("T18 紀錄檔存在、執行中標記已清", (p10 / f".ai-review/.cache/codex-{H}.log").exists()
          and not (p10 / f".ai-review/.cache/codex-{H}.running").exists())
    st = json.loads(read(p10 / ".ai-review/state.json"))
    check("T18 跑完狀態已推導為 no-blocking-found", st["status"] == "no-blocking-found", json.dumps(st)[-300:])
    rc, out, err = kit("codex-review", "--codex", str(fake), cwd=p10, script=p10kit)
    check("T18 已有獨立審查 → 不重跑（exit 1）", rc == 1 and "--again" in out, out[-300:])
    write(p10 / "app.py", read(p10 / "app.py") + "\n# changed after handoff\n")
    rc, out, err = kit("codex-review", "--codex", str(fake), "--again", cwd=p10, script=p10kit)
    check("T18 交接後又改過 → 不啟動（exit 1）", rc == 1 and "不符" in out, out[-300:])

    # ---------------- 總結
    fails = [r for r in RESULTS if not r[1]]
    print(f"\n共 {len(RESULTS)} 項，通過 {len(RESULTS) - len(fails)}，失敗 {len(fails)}")
    if not a.keep and not a.dir:
        print(f"（測試資料夾保留在 {root}，依刪除先問原則不自動刪除）")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
