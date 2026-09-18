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

    # ---------------- 總結
    fails = [r for r in RESULTS if not r[1]]
    print(f"\n共 {len(RESULTS)} 項，通過 {len(RESULTS) - len(fails)}，失敗 {len(fails)}")
    if not a.keep and not a.dir:
        print(f"（測試資料夾保留在 {root}，依刪除先問原則不自動刪除）")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
