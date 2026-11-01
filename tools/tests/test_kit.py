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
ENV.pop("CLAUDE_PROJECT_DIR", None)     # 守門 hook 用它判斷巢狀（T-0204）：測試者自己的 Claude Code 環境不能影響結果
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
    # 不讀測試者自己的 Codex 設定檔（codex-review 會看它有沒有 default_permissions）：一律指到測試用的空資料夾
    ENV["CODEX_HOME"] = str(root / "codex-home-empty")

    # ---------------- T1 新專案安裝
    p1 = new_git_project(root, "p1-new")
    rc, out, err = kit("install", "--target", str(p1))
    check("T1 install exit 0", rc == 0, err[-500:])
    must = [".ai-review/kit/workflow.md", ".ai-review/kit/kit.py", ".ai-review/kit/VERSION",
            ".ai-review/kit/templates/config.md", ".ai-review/kit/docs/codex-start.md",
            ".claude/skills/safety-setup/SKILL.md", ".claude/skills/review-ready/SKILL.md",
            ".claude/skills/review-fix/SKILL.md", ".agents/skills/independent-review/SKILL.md",
            "CLAUDE.md", "AGENTS.md", ".claude/settings.json", ".codex/hooks.json", ".gitignore",
            ".ai-review/kit-version.json", ".ai-review/state.json", ".ai-review/handoffs/.gitkeep",
            ".claude/agents/independent-reviewer.md"]
    missing = [m for m in must if not (p1 / m).exists()]
    check("T1 所有檔案存在", not missing, str(missing))
    check("T1 安裝完成訊息提醒第一次裝 agent 檔要重開 Claude Code", "第一次裝 agent 檔要重開 Claude Code" in out, out[-500:])
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
    import zipfile
    znames = set(zipfile.ZipFile(zips[0]).namelist()) if zips else set()
    check("T9 zip 收了 LICENSE、README.zh-TW.md 與審查員子代理定義（0.5.0）",
          {"ai-review-kit/LICENSE", "ai-review-kit/README.zh-TW.md", "ai-review-kit/claude/agents/independent-reviewer.md"} <= znames,
          str(sorted(znames))[:400])
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
                ".ai-review/kit-version.json", ".ai-review/state.json", ".ai-review/reviews/.gitkeep",
                ".claude/agents/independent-reviewer.md"):
        if key not in listed:
            check(f"T16 預覽列出 {key}", False, out[-600:])
    check("T16 預覽附 hook 內容差異", "差異：.claude/settings.json" in out, out[-600:])
    check("T16 預覽列出審查員子代理定義並說明含守門 hook", ".claude/agents/independent-reviewer.md" in listed
          and "子代理定義含守門 hook" in out, out[-600:])

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
    check("T18 --print 列出工作區沙箱命令、不含繞過旗標與 -m（測試的 CODEX_HOME 是空的 → 舊式 -s）",
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

    # ---------------- T19 沙箱環境變數：-c 設定帶進 codex 命令（2026-10-11 新增）
    def overrides_of(av):
        res = {}
        for i, x in enumerate(av[:-1]):
            if x == "-c" and "=" in av[i + 1]:
                k, v = av[i + 1].split("=", 1)
                res[k] = v
        return res

    def toml_value(v):
        try:
            import tomllib
        except ImportError:          # Python 3.10 以下沒有 tomllib：只比字面
            return json.loads(v)
        return tomllib.loads("v = " + v)["v"]

    ov = overrides_of(argv)
    want_py = envr.get("AI_REVIEW_PYTHON")
    shell_py = ov.get("shell_environment_policy.set.AI_REVIEW_PYTHON")
    check("T19 codex 命令帶 -c shell_environment_policy.set.AI_REVIEW_PYTHON（合法 TOML、值＝實體直譯器）",
          shell_py is not None and toml_value(shell_py) == want_py, json.dumps(ov, ensure_ascii=False)[:600])
    if os.name == "nt":
        sd = ov.get("shell_environment_policy.set.SYSTEMDRIVE")
        check("T19 Windows：shell 層帶 SYSTEMDRIVE、SYSTEMROOT",
              sd is not None and toml_value(sd).endswith(":") and "shell_environment_policy.set.SYSTEMROOT" in ov,
              json.dumps(ov, ensure_ascii=False)[:600])
    allow = ov.get("mcp_servers.node_repl.env.NODE_REPL_UNTRUSTED_ENV_ALLOWLIST")
    names = toml_value(allow).split(",") if allow else []
    check("T19 node_repl 已設定 → 補 env.AI_REVIEW_PYTHON、放行清單保留原值在前並加上 AI_REVIEW_PYTHON",
          names[:1] == ["CODEX_WINDOWS_REGISTERED_CORE"] and "AI_REVIEW_PYTHON" in names
          and ("SYSTEMDRIVE" in names if os.name == "nt" else True)
          and toml_value(ov.get("mcp_servers.node_repl.env.AI_REVIEW_PYTHON", '""')) == want_py,
          json.dumps(ov, ensure_ascii=False)[:600])
    check("T19 -c 設定都放在 exec 之後、-C 之前，交接編號仍是最後一個參數",
          argv[0] == "exec" and argv.index("-c") < argv.index("-C") and argv[-1] == f"$independent-review {H}", json.dumps(argv)[:600])
    check("T19 乾淨的審查 .done 不帶工作區變動警告",
          "workspace_changes" not in done and "warnings" not in done and "fingerprint_drift" not in done, json.dumps(done))
    rc, out, err = kit("codex-review", "--print", "--again", "--codex", str(fake), cwd=p10, script=p10kit)
    check("T19 --print 顯示帶進沙箱的 -c 設定與 node_repl 狀態",
          rc == 0 and "shell_environment_policy.set.AI_REVIEW_PYTHON=" in out and "node_repl：已設定" in out, out[-800:])
    rc, out, err = sh([PY, str(p10kit), "codex-review", "--print", "--again", "--codex", str(fake)], cwd=p10,
                      env=dict(ENV, FAKE_CODEX_MCP="none"))
    check("T19 沒設定 node_repl → 不補 mcp_servers 設定（避免 Codex 報 invalid transport）",
          rc == 0 and "mcp_servers." not in out and "node_repl：沒有設定" in out
          and "shell_environment_policy.set.AI_REVIEW_PYTHON=" in out, out[-800:])
    rc, out, err = kit("codex-review", "--print", "--again", "--no-sandbox-env", "--codex", str(fake), cwd=p10, script=p10kit)
    check("T19 --no-sandbox-env → 命令不帶任何 -c", rc == 0 and " -c " not in out.split("\n", 1)[0], out[-500:])

    # ---------------- T29 送審權限：Codex 設定檔有 default_permissions → 不帶 -s、改帶 -c default_permissions（T-0081，未發版）
    check("T29 Codex 設定檔沒有 default_permissions → 照舊 -s workspace-write，.done 記 legacy",
          "-s" in argv and "default_permissions" not in json.dumps(argv)
          and (done.get("permissions") or {}).get("mode") == "legacy", json.dumps(done, ensure_ascii=False)[:400])
    ch_profile = root / "codex-home-profile"
    write(ch_profile / "config.toml", 'model = "x"\ndefault_permissions = "review-safe"\n\n[windows]\nsandbox = "mxc"\n\n'
          '[permissions.review-safe]\nextends = ":workspace"\n\n[permissions.review-safe.filesystem]\n"~/.ssh" = "deny"\n')
    env_profile = dict(ENV, CODEX_HOME=str(ch_profile))
    rc, out, err = sh([PY, str(p10kit), "codex-review", "--again", "--codex", str(fake)], cwd=p10, env=env_profile)
    rec = json.loads(read(p10 / ".ai-review/.cache/fake-record.json"))
    argv_p = rec.get("argv", [])
    ov_p = overrides_of(argv_p)
    done_p = json.loads(read(p10 / f".ai-review/.cache/codex-{H}.done"))
    check("T29 有 default_permissions → 命令不帶 -s／--sandbox，改帶 -c default_permissions=\"review-safe\"",
          rc == 0 and "-s" not in argv_p and "--sandbox" not in argv_p and "workspace-write" not in argv_p
          and toml_value(ov_p.get("default_permissions", '""')) == "review-safe", json.dumps(argv_p)[:600])
    check("T29 權限的 -c 也在 -C 之前、沙箱環境變數設定照帶、交接編號仍是最後一個參數",
          argv_p.index("-C") > max(i for i, x in enumerate(argv_p) if x == "-c")
          and "shell_environment_policy.set.AI_REVIEW_PYTHON" in ov_p and argv_p[-1] == f"$independent-review {H}",
          json.dumps(argv_p)[:600])
    check("T29 .done 記下權限設定檔名稱與來源、執行時印出沙箱權限",
          (done_p.get("permissions") or {}).get("mode") == "profile" and done_p["permissions"].get("profile") == "review-safe"
          and str(ch_profile) in done_p["permissions"].get("source", "") and "沙箱權限：權限設定檔 review-safe" in out,
          json.dumps(done_p, ensure_ascii=False)[:500] + out[-300:])
    rc, out, err = sh([PY, str(p10kit), "codex-review", "--print", "--again", "--no-sandbox-env", "--codex", str(fake)],
                      cwd=p10, env=env_profile)
    first = out.split("\n", 1)[0]
    check("T29 --no-sandbox-env 仍帶權限設定檔（只關環境變數那層）",
          rc == 0 and first.count(" -c ") == 1 and "default_permissions=" in first and "workspace-write" not in first, out[-500:])
    rc, out, err = kit("codex-review", "--print", "--again", "--permissions", "my-profile", "--codex", str(fake), cwd=p10, script=p10kit)
    first = out.split("\n", 1)[0]
    check("T29 --permissions 指定 → 用指定名稱、不帶 -s（設定檔沒有 default_permissions 也一樣）",
          rc == 0 and "my-profile" in first and "default_permissions=" in first and "workspace-write" not in first
          and "--permissions 指定" in out, out[-500:])
    for bad in (":danger-no-sandbox", "x\"y", "a b"):
        rc, out, err = kit("codex-review", "--print", "--again", "--permissions", bad, "--codex", str(fake), cwd=p10, script=p10kit)
        check(f"T29 不接受的權限名稱 {bad!r} → exit 2、不啟動", rc == 2 and "不接受" in out and "將執行" not in out, out[-300:])
    ch_nested = root / "codex-home-nested"
    write(ch_nested / "config.toml", '[profiles.x]\ndefault_permissions = "review-safe"\n')
    rc, out, err = sh([PY, str(p10kit), "codex-review", "--print", "--again", "--codex", str(fake)], cwd=p10,
                      env=dict(ENV, CODEX_HOME=str(ch_nested)))
    check("T29 default_permissions 只在 [表格] 裡、不在最上層 → 不算，照舊 -s workspace-write",
          rc == 0 and "-s workspace-write" in out and "default_permissions=" not in out.split("\n", 1)[0], out[-400:])
    ch_bad = root / "codex-home-badtoml"
    write(ch_bad / "config.toml", 'default_permissions = "review-safe"\n[[[broken\n')
    rc, out, err = sh([PY, str(p10kit), "codex-review", "--print", "--again", "--codex", str(fake)], cwd=p10,
                      env=dict(ENV, CODEX_HOME=str(ch_bad)))
    check("T29 Codex 設定檔壞掉 → 照舊 -s workspace-write 並說明原因（不猜）",
          (rc == 0 and "-s workspace-write" in out and "不是合法 TOML" in out) or sys.version_info < (3, 11), out[-400:])
    rc, out, err = sh([PY, str(p10kit), "doctor", "--json", "--codex", str(fake)], cwd=p10, env=env_profile)
    dj = json.loads(out) if rc == 0 else {}
    dperm = next((i for i in dj.get("items", []) if i["key"] == "codex_permissions"), {})
    rc2, out2, err2 = kit("doctor", "--json", "--codex", str(fake), cwd=p10, script=p10kit)
    dperm2 = next((i for i in (json.loads(out2) if rc2 == 0 else {}).get("items", []) if i["key"] == "codex_permissions"), {})
    check("T29 doctor 列出送審沙箱權限：有設定檔 ✓、沒有 ？並提示怎麼擋讀取",
          dperm.get("ok") is True and "review-safe" in dperm.get("detail", "")
          and dperm2.get("ok") is None and "workspace-write" in dperm2.get("detail", ""), out[-400:] + out2[-400:])

    # T18 最後一項（放在 T19 之後：T19 的 --print 需要交接仍相符）
    write(p10 / "app.py", read(p10 / "app.py") + "\n# changed after handoff\n")
    rc, out, err = kit("codex-review", "--codex", str(fake), "--again", cwd=p10, script=p10kit)
    check("T18 交接後又改過 → 不啟動（exit 1）", rc == 1 and "不符" in out, out[-300:])

    # ---------------- T20 審後比對：審查期間工作區多出檔案 → 警告、寫進 .done 與紀錄、不刪（2026-10-11 新增）
    rc, out, err = kit("snapshot", "--json", cwd=p10, script=p10kit)
    snap2 = json.loads(out) if rc == 0 else {}
    H2 = snap2.get("id", "H-missing")
    write(p10 / f".ai-review/handoffs/{H2}.md", front(H2, "handoff", target=snap2.get("target"), snapshot_ref=snap2.get("snapshot_ref"),
                                                        head=snap2.get("head"), base=snap2.get("base"), recheck_of="", scope="t20"))
    rc, out, err = sh([PY, str(p10kit), "codex-review", "--codex", str(fake)], cwd=p10, env=dict(ENV, FAKE_CODEX_MODE="dirty"))
    junk_rel = "%SystemDrive%/ProgramData/Microsoft/Windows/Caches/cversions.2.db"
    done2p = p10 / f".ai-review/.cache/codex-{H2}.done"
    done2 = json.loads(read(done2p)) if done2p.exists() else {}
    log2 = read(p10 / f".ai-review/.cache/codex-{H2}.log") if (p10 / f".ai-review/.cache/codex-{H2}.log").exists() else ""
    check("T20 審查期間多出檔案 → 印出警告並列出路徑", "⚠️" in out and junk_rel in out and "不會自動刪" in out, out[-800:] + err[-300:])
    check("T20 .done 記下 workspace_changes、指紋漂移與警告",
          junk_rel in (done2.get("workspace_changes") or {}).get("added", []) and done2.get("fingerprint_drift") is True
          and done2.get("warnings"), json.dumps(done2, ensure_ascii=False)[:800])
    check("T20 紀錄檔附上審後檢查段", "[ai-review-kit 審後檢查]" in log2 and junk_rel in log2, log2[-600:])
    check("T20 多出來的檔沒有被刪", (p10 / junk_rel).is_file())
    check("T20 .done 記下字面環境變數名資料夾", done2.get("literal_env_dirs") == ["%SystemDrive%"], json.dumps(done2, ensure_ascii=False)[:400])

    # T20b 字面資料夾被 .gitignore 排除：指紋不受影響，但仍提醒「環境變數沒帶進去」
    write(p10 / ".gitignore", read(p10 / ".gitignore") + "/%Windir%/\n/%SystemDrive%/\n")
    rc, out, err = kit("snapshot", "--json", cwd=p10, script=p10kit)
    snap3 = json.loads(out) if rc == 0 else {}
    H3 = snap3.get("id", "H-missing")
    write(p10 / f".ai-review/handoffs/{H3}.md", front(H3, "handoff", target=snap3.get("target"), snapshot_ref=snap3.get("snapshot_ref"),
                                                        head=snap3.get("head"), base=snap3.get("base"), recheck_of="", scope="t20b"))
    rc, out, err = sh([PY, str(p10kit), "codex-review", "--codex", str(fake)], cwd=p10,
                      env=dict(ENV, FAKE_CODEX_MODE="dirty", FAKE_CODEX_JUNK="%Windir%"))
    done3p = p10 / f".ai-review/.cache/codex-{H3}.done"
    done3 = json.loads(read(done3p)) if done3p.exists() else {}
    check("T20b 被忽略的字面資料夾：不算工作區變動、指紋不漂移，但 .done 與輸出仍提醒",
          rc == 0 and done3.get("literal_env_dirs") == ["%Windir%"] and "workspace_changes" not in done3
          and "fingerprint_drift" not in done3 and "%Windir%" in out and done3.get("verdict") == "no-blocking-found",
          out[-600:] + json.dumps(done3, ensure_ascii=False)[:600])

    # ---------------- T21 ignore-check：.gitignore 機密清單檢查（唯讀、只提醒）（未發版新增）
    # 隔離本機的全域 git 排除設定（~/.config/git/ignore、core.excludesFile），結果才不受跑測試的電腦影響
    xdg = root / "t21-xdg"
    xdg.mkdir()
    gcfg = root / "t21-gitconfig"
    write(gcfg, "")
    ienv = dict(ENV, XDG_CONFIG_HOME=str(xdg), GIT_CONFIG_GLOBAL=str(gcfg))
    std = [".env", ".env.*", "*.local.*", "credentials*", "secrets.*", ".claude/settings.local.json", "*.pem", "*.key",
           "*.pfx", "*.p12", "id_rsa*", "id_ed25519*", ".claude/projects/", "*.jsonl", "memory/"]

    def ic(target, *extra):
        return sh([PY, str(KIT_PY), "ignore-check", "--target", str(target), *extra], env=ienv)

    def icj(target):
        rc, out, err = ic(target, "--json")
        try:
            return rc, json.loads(out), err
        except Exception:
            return rc, {}, out[-400:] + err[-400:]

    def status_of(info):
        return {r["line"]: r["status"] for r in info.get("rules", [])}

    def tree_bytes(d):
        return {f.relative_to(d).as_posix(): f.read_bytes() for f in d.rglob("*") if f.is_file()}

    # 全缺
    p11 = new_git_project(root, "p11-ignore-none")
    rc, info, err = icj(p11)
    check("T21 全缺：exit 0、15 條都列為缺、建議行＝標準清單",
          rc == 0 and info.get("git") is True and info.get("missing") == std and info.get("suggested_lines") == std
          and set(status_of(info).values()) == {"missing"}, err + json.dumps(info, ensure_ascii=False)[:400])
    rc, out, err = ic(p11)
    check("T21 全缺：預設白話輸出、缺漏不算錯誤（exit 0）",
          rc == 0 and "缺 15 條" in out and "要不要補由你決定" in out and "唯讀" in out, out[-400:] + err[-200:])
    # 全有
    p12 = new_git_project(root, "p12-ignore-all")
    write(p12 / ".gitignore", "\n".join(std) + "\n")
    rc, info, err = icj(p12)
    check("T21 全有：沒有缺漏、15 條都是已排除",
          rc == 0 and info.get("missing") == [] and set(status_of(info).values()) == {"covered"}
          and info.get("tracked") == [], err + json.dumps(info, ensure_ascii=False)[:400])
    rc, out, err = ic(p12)
    check("T21 全有：白話輸出說都已排除", rc == 0 and "都已排除" in out and "缺 " not in out, out[-300:])
    # 部分缺：含否定規則與只在本機排除（.git/info/exclude）
    p13 = new_git_project(root, "p13-ignore-partial")
    write(p13 / ".gitignore", ".env\n*.pem\n*.jsonl\n!session.jsonl\n")
    write(p13 / ".git/info/exclude", "*.key\n")
    rc, info, err = icj(p13)
    st13 = status_of(info)
    check("T21 部分缺：已寫的算已排除、其餘列缺",
          rc == 0 and st13.get(".env") == "covered" and st13.get("*.pem") == "covered"
          and st13.get(".env.*") == "missing" and st13.get("memory/") == "missing", json.dumps(st13, ensure_ascii=False))
    # T-0054 起每條有多個代表路徑：!session.jsonl 讓 session.jsonl、logs/session.jsonl 沒被排除，但 a/b/history.jsonl 仍被排除 → partial（原本只有一個探針，判 missing）
    jl = next((r for r in info.get("rules", []) if r["line"] == "*.jsonl"), {})
    check("T21 否定規則（!session.jsonl）讓 *.jsonl 只排除一部分（判斷交給 git）",
          st13.get("*.jsonl") == "partial" and set(jl.get("uncovered_probes", [])) == {"session.jsonl", "logs/session.jsonl"}
          and "*.jsonl" in info.get("missing", []), json.dumps(jl, ensure_ascii=False)[:400])
    check("T21 只在 .git/info/exclude 排除 → 只在本機排除，也列進要補的行",
          st13.get("*.key") == "local-only" and "*.key" in info.get("missing", []) and "*.key" in info.get("suggested_lines", []),
          json.dumps(st13, ensure_ascii=False))
    # 已追蹤的符合檔：只列路徑、不印內容；標記「已決定不排除」後不再列
    p14 = new_git_project(root, "p14-ignore-tracked")
    write(p14 / ".env", "SECRET_TOKEN=should-not-print-xyz\n")
    write(p14 / "data/words.jsonl", '{"w": "apple"}\n')
    git("add", "-A", cwd=p14)
    git("commit", "-q", "-m", "oops", cwd=p14)
    write(p14 / ".gitignore", "\n".join(x for x in std if x != "*.jsonl") + "\n")
    (p14 / ".ai-review").mkdir()
    shutil.copy(KIT_ROOT / "templates/config.md", p14 / ".ai-review/config.md")
    rc, info, err = icj(p14)
    tracked = {t["line"]: t["paths"] for t in info.get("tracked", [])}
    check("T21 已追蹤的符合檔被列出（.env、data/words.jsonl）",
          rc == 0 and tracked.get(".env") == [".env"] and tracked.get("*.jsonl") == ["data/words.jsonl"],
          json.dumps(info.get("tracked"), ensure_ascii=False))
    check("T21 範本的 ignore-ok 區塊只有註解範例，不算標記（*.jsonl 仍缺）",
          info.get("missing") == ["*.jsonl"] and info.get("accepted") == [], json.dumps(info.get("missing"), ensure_ascii=False))
    rc, out, err = ic(p14)
    check("T21 白話輸出列已追蹤檔路徑、絕不印檔案內容",
          rc == 0 and "data/words.jsonl" in out and "已經被 git 追蹤" in out and "should-not-print-xyz" not in out,
          out[-500:])
    rc, outj, err = ic(p14, "--json")
    check("T21 --json 也不含檔案內容", "should-not-print-xyz" not in outj)
    cfg = read(p14 / ".ai-review/config.md")
    write(p14 / ".ai-review/config.md", cfg.replace("```ignore-ok\n", "```ignore-ok\n*.jsonl | 2026-10-11 | 題庫資料\n", 1))
    before = tree_bytes(p14)
    rc, info, err = icj(p14)
    tracked = {t["line"]: t["paths"] for t in info.get("tracked", [])}
    acc = [r for r in info.get("rules", []) if r["line"] == "*.jsonl"]
    check("T21 標記「已決定不排除」後：不算缺、已追蹤清單也不再列，其他條照列",
          rc == 0 and info.get("missing") == [] and info.get("accepted") == ["*.jsonl"] and "*.jsonl" not in tracked
          and tracked.get(".env") == [".env"] and acc and acc[0]["status"] == "accepted"
          and acc[0].get("accepted", {}).get("reason") == "題庫資料", json.dumps(info, ensure_ascii=False)[:600])
    rc, out, err = ic(p14)
    check("T21 白話輸出顯示已決定不排除與理由", "已決定不排除" in out and "題庫資料" in out, out[-500:])
    check("T21 唯讀：跑完專案（含 .git）每個檔位元組都沒變", tree_bytes(p14) == before)
    # 非 git、--json 格式、失敗才非 0
    p15 = root / "p15-ignore-nogit"
    p15.mkdir()
    write(p15 / "main.py", "print(1)\n")
    rc, out, err = ic(p15)
    check("T21 非 git 目錄：印說明、exit 0", rc == 0 and "不是 git 專案" in out, out + err)
    rc, info, err = icj(p15)
    check("T21 非 git 的 --json：git=false、沒有規則", rc == 0 and info.get("git") is False and info.get("rules") == [], err)
    rc, info, err = icj(p12)
    keys_ok = all(k in info for k in ("target", "git", "rules", "missing", "accepted", "tracked", "suggested_lines", "note"))
    rule_ok = all(set(r) >= {"line", "probe", "why", "status", "matched_by"} and r["why"] for r in info.get("rules", []))
    check("T21 --json 欄位齊全、每條都有白話說明", keys_ok and rule_ok and len(info.get("rules", [])) == 15, json.dumps(info, ensure_ascii=False)[:400])
    rc, out, err = ic(root / "no-such-dir-t21")
    check("T21 指令本身失敗（資料夾不存在）才非 0", rc != 0 and "找不到資料夾" in err, out + err)

    # ---------------- T28 單一探針漏判的回歸（T-0054，Codex 審查 R-20261011-1654-1）
    def rule_of(info, line):
        return next((r for r in info.get("rules", []) if r["line"] == line), {})

    def std_with(*repl, extra=""):
        lines = list(std)
        for old, new in repl:
            lines[lines.index(old)] = new
        return "\n".join(lines) + "\n" + extra

    p22 = new_git_project(root, "p22-probe-credentials-dot")
    write(p22 / ".gitignore", std_with(("credentials*", "credentials.*")))
    rc, info, err = icj(p22)
    cr = rule_of(info, "credentials*")
    check("T28 只寫 credentials.* → credentials* 判 partial，列進 missing 與 suggested_lines",
          rc == 0 and cr.get("status") == "partial" and "credentials*" in info.get("missing", [])
          and "credentials*" in info.get("suggested_lines", []), json.dumps(cr, ensure_ascii=False)[:500])
    check("T28 partial 的 uncovered_probes 含 credentials-prod.json 與無副檔名的 credentials，已排除的 credentials.json 不在內",
          {"credentials-prod.json", "credentials"} <= set(cr.get("uncovered_probes", []))
          and "credentials.json" not in cr.get("uncovered_probes", []), json.dumps(cr.get("uncovered_probes"), ensure_ascii=False))
    check("T28 --json 每條有 probes（ignored／matched_by）、保留舊欄位 probe＝第一個代表路徑",
          all(set(x) >= {"path", "ignored", "matched_by"} for x in cr.get("probes", [])) and len(cr.get("probes", [])) >= 3
          and cr.get("probe") == cr["probes"][0]["path"], json.dumps(cr, ensure_ascii=False)[:500])
    check("T28 其他 14 條仍判已排除（只動了一行）", sum(1 for r in info.get("rules", []) if r["status"] == "covered") == 14,
          json.dumps(status_of(info), ensure_ascii=False))
    rc, out, err = ic(p22)
    check("T28 白話輸出寫「只排除了一部分」並舉出沒排除的例子", rc == 0 and "只排除了一部分" in out and "credentials-prod.json" in out,
          out[-600:])
    p23 = new_git_project(root, "p23-probe-credentials-star")
    write(p23 / ".gitignore", std_with())
    rc, info, err = icj(p23)
    check("T28 寫 credentials* → covered、沒有未排除的代表路徑",
          rule_of(info, "credentials*").get("status") == "covered" and rule_of(info, "credentials*").get("uncovered_probes") == [],
          json.dumps(rule_of(info, "credentials*"), ensure_ascii=False)[:400])
    p24 = new_git_project(root, "p24-probe-anchored")
    write(p24 / ".gitignore", std_with(("memory/", "/memory/")))
    rc, info, err = icj(p24)
    mr = rule_of(info, "memory/")
    check("T28 錨定寫法 /memory/ → partial，沒排除的是子資料夾那個",
          mr.get("status") == "partial" and mr.get("uncovered_probes") == ["sub/memory/notes.md"] and "memory/" in info.get("missing", []),
          json.dumps(mr, ensure_ascii=False)[:400])
    p25 = new_git_project(root, "p25-probe-negation")
    write(p25 / ".gitignore", std_with(extra="!credentials-prod.json\n"))
    rc, info, err = icj(p25)
    nr = rule_of(info, "credentials*")
    check("T28 credentials* 加否定規則 !credentials-prod.json → partial，只有那一個沒排除",
          nr.get("status") == "partial" and nr.get("uncovered_probes") == ["credentials-prod.json"],
          json.dumps(nr, ensure_ascii=False)[:400])

    # ---------------- T22 「已初始化」要 meta 有填＋第 4 節至少一條命令（G7，未發版）
    p16 = new_git_project(root, "p16-init")
    kit("install", "--target", str(p16))
    p16kit = p16 / ".ai-review/kit/kit.py"

    def st_nowrite(proj, script):
        rc, out, err = kit("state", "--json", "--no-write", cwd=proj, script=script)
        try:
            return json.loads(out)
        except Exception:
            return {"_raw": out[-300:] + err[-300:]}

    s = st_nowrite(p16, p16kit)
    check("T22 沒有 config.md → 未初始化、原因說沒有 config", s.get("initialized") is False and "沒有 .ai-review/config.md" in (s.get("init_reason") or ""), json.dumps(s, ensure_ascii=False)[:300])
    tmpl = read(KIT_ROOT / "templates/config.md")
    write(p16 / ".ai-review/config.md", tmpl)
    s = st_nowrite(p16, p16kit)
    check("T22 只有範本（meta 是 {{…}}、checks 空）→ 未初始化、白話說只有部分內容",
          s.get("initialized") is False and "只有部分內容" in (s.get("init_reason") or ""), json.dumps(s, ensure_ascii=False)[:300])
    meta_filled = tmpl.replace("{{KIT_VERSION}}", "0.3.0").replace("{{DATE}}", "2026-10-11")
    write(p16 / ".ai-review/config.md", meta_filled)
    s = st_nowrite(p16, p16kit)
    check("T22 meta 有填但第 4 節沒命令 → 未初始化、原因點名第 4 節",
          s.get("initialized") is False and "第 4 節" in (s.get("init_reason") or ""), json.dumps(s, ensure_ascii=False)[:300])
    write(p16 / ".ai-review/config.md", tmpl.replace("```checks\nname | command | required\n```",
                                                     "```checks\nname | command | required\nok | echo ok | yes\n```"))
    s = st_nowrite(p16, p16kit)
    check("T22 有命令但 meta 還是範本 → 未初始化、原因點名 meta",
          s.get("initialized") is False and "meta" in (s.get("init_reason") or ""), json.dumps(s, ensure_ascii=False)[:300])
    write(p16 / ".ai-review/config.md", meta_filled.replace("```checks\nname | command | required\n```",
                                                            "```checks\nname | command | required\nok | echo ok | yes\n```"))
    s = st_nowrite(p16, p16kit)
    check("T22 meta 有填＋至少一條命令 → 已初始化", s.get("initialized") is True and s.get("init_reason") == "已完成",
          json.dumps(s, ensure_ascii=False)[:300])
    write(p16 / ".ai-review/config.md", tmpl)
    rc, out, err = kit("hook", "session-start", cwd=p16, script=p16kit, input_text=b"{}")
    check("T22 開場 hook 顯示白話原因", rc == 0 and "初始化：未完成 → config.md 只有部分內容" in out, out[-400:])

    # ---------------- T23 審後比對看得到 .gitignore 排除位置多出的東西（G5，未發版）
    write(p10 / ".gitignore", read(p10 / ".gitignore") + "data/\n")
    (p10 / "data").mkdir(exist_ok=True)
    write(p10 / "data/user.db", "x")
    rc, out, err = kit("snapshot", "--json", cwd=p10, script=p10kit)
    snap4 = json.loads(out) if rc == 0 else {}
    H4 = snap4.get("id", "H-missing")
    write(p10 / f".ai-review/handoffs/{H4}.md", front(H4, "handoff", target=snap4.get("target"), snapshot_ref=snap4.get("snapshot_ref"),
                                                        head=snap4.get("head"), base=snap4.get("base"), recheck_of="", scope="t23"))
    rc, out, err = sh([PY, str(p10kit), "codex-review", "--codex", str(fake)], cwd=p10,
                      env=dict(ENV, FAKE_CODEX_MODE="ignored", FAKE_CODEX_IGNORED="data/review-H1141-c4YHfC"))
    done4p = p10 / f".ai-review/.cache/codex-{H4}.done"
    done4 = json.loads(read(done4p)) if done4p.exists() else {}
    check("T23 審查寫進被排除的 data/ → .done 的 new_ignored_entries 列出、輸出有警告",
          done4.get("new_ignored_entries") == ["data/review-H1141-c4YHfC/"] and "data/review-H1141-c4YHfC/" in out and "不會自動刪" in out,
          out[-600:] + json.dumps(done4, ensure_ascii=False)[:500])
    check("T23 只警告：不算指紋漂移、不算工作區變動、結論照常、檔案沒被刪",
          "fingerprint_drift" not in done4 and "workspace_changes" not in done4 and done4.get("verdict") == "no-blocking-found"
          and (p10 / "data/review-H1141-c4YHfC/t.txt").is_file(), json.dumps(done4, ensure_ascii=False)[:500])
    check("T23 .ai-review/.cache 底下的預期變動（紀錄、tmp、fake-record）不警告",
          not any(e.startswith(".ai-review/") for e in done4.get("new_ignored_entries", [])), json.dumps(done4, ensure_ascii=False)[:500])
    rc, out, err = kit("snapshot", "--json", cwd=p10, script=p10kit)
    snap5 = json.loads(out) if rc == 0 else {}
    H5 = snap5.get("id", "H-missing")
    write(p10 / f".ai-review/handoffs/{H5}.md", front(H5, "handoff", target=snap5.get("target"), snapshot_ref=snap5.get("snapshot_ref"),
                                                        head=snap5.get("head"), base=snap5.get("base"), recheck_of="", scope="t23b"))
    rc, out, err = kit("codex-review", "--codex", str(fake), "--again", cwd=p10, script=p10kit)
    done5p = p10 / f".ai-review/.cache/codex-{H5}.done"
    done5 = json.loads(read(done5p)) if done5p.exists() else {}
    check("T23 乾淨的審查（沒多東西）→ 沒有 new_ignored_entries 與警告",
          rc == 0 and "new_ignored_entries" not in done5 and "warnings" not in done5, out[-400:] + json.dumps(done5, ensure_ascii=False)[:400])

    # ---------------- T24 state --no-write：只推導、不寫任何檔（給工作根目錄的轉接 hook 用，未發版）
    write(p10 / "app.py", read(p10 / "app.py") + "# t24 change\n")       # 讓「會寫」的 state 結果一定和現存 state.json 不同
    ai_before = tree_bytes(p10 / ".ai-review")
    rc, out, err = kit("state", "--json", "--no-write", cwd=p10, script=p10kit)
    sj = json.loads(out) if rc == 0 else {}
    check("T24 --no-write --json：.ai-review 底下每個檔位元組都沒變（含 state.json、.cache）",
          rc == 0 and tree_bytes(p10 / ".ai-review") == ai_before, err[-300:])
    check("T24 --no-write 的 JSON 欄位齊全（status、白話標籤、initialized、init_reason、fresh、handoff、review、open_items）",
          all(k in sj for k in ("status", "status_label", "initialized", "init_reason", "fresh", "handoff", "review", "open_items"))
          and sj.get("status") == "not-ready" and sj.get("fresh") is False and (sj.get("handoff") or {}).get("id") == H5
          and sj.get("status_label") == "尚未準備", json.dumps(sj, ensure_ascii=False)[:500])
    rc, out, err = kit("state", "--no-write", cwd=p10, script=p10kit)
    check("T24 --no-write 不加 --json 印白話狀態、也不寫檔", rc == 0 and "狀態：尚未準備" in out and tree_bytes(p10 / ".ai-review") == ai_before, out[-300:])
    rc, out, err = kit("state", "--json", cwd=p10, script=p10kit)
    check("T24 對照：不加 --no-write 會寫 state.json", rc == 0 and read(p10 / ".ai-review/state.json") != ai_before[
        "state.json"].decode("utf-8-sig") and json.loads(read(p10 / ".ai-review/state.json"))["status"] == "not-ready")
    rc, out, err = kit("state", "--json", "--definitely-unknown-flag", cwd=p10, script=p10kit)
    check("T24 不認得的旗標 → argparse exit 2（舊版 kit 遇到 --no-write 就是這樣，轉接 hook 拿來判斷舊版）", rc == 2, out + err)

    # ---------------- T25 config.md 第 6 節狀態欄解析（新舊格式相容）（G11，未發版）
    p17 = new_git_project(root, "p17-unverified")
    kit("install", "--target", str(p17))
    p17kit = p17 / ".ai-review/kit/kit.py"

    def unverified(proj, script):
        rc, out, err = kit("doctor", "--json", "--codex", str(root / "no-such-codex.exe"), cwd=proj, script=script)
        try:
            return rc, (json.loads(out).get("project") or {}).get("unverified"), out
        except Exception:
            return rc, None, out[-300:] + err[-300:]

    write(p17 / ".ai-review/config.md", tmpl)
    rc, u, raw = unverified(p17, p17kit)
    check("T25 範本：有狀態欄、0 列（ignore-ok 區塊不被當成表格列）", rc == 0 and u == {"total": 0, "open": 0, "resolved": 0, "no_status": 0, "has_status_column": True}, str(u) + raw[-200:])
    new_fmt = tmpl.replace("| 日期 | 事項 | 為什麼還沒驗證 | 誰決定可接受 | 狀態 |\n|---|---|---|---|---|\n",
                           "| 日期 | 事項 | 為什麼還沒驗證 | 誰決定可接受 | 狀態 |\n|---|---|---|---|---|\n"
                           "| 2026-10-01 | 未裝 gitleaks | 沒裝 | 使用者 | 已解 2026-10-05 |\n"
                           "| 2026-10-02 | 沒有 CI | 沒設 | 使用者 | 未解 |\n"
                           "| 2026-10-03 | 依賴掃描 | 沒網路 | 使用者 | |\n")
    write(p17 / ".ai-review/config.md", new_fmt)
    rc, u, raw = unverified(p17, p17kit)
    check("T25 新格式：已解 1、未解 2（空白狀態算未解）", u and u["has_status_column"] and u["total"] == 3 and u["resolved"] == 1 and u["open"] == 2,
          str(u) + raw[-200:])
    old_fmt = tmpl.replace("| 日期 | 事項 | 為什麼還沒驗證 | 誰決定可接受 | 狀態 |\n|---|---|---|---|---|\n",
                           "| 日期 | 事項 | 為什麼還沒驗證 | 誰決定可接受 |\n|---|---|---|---|\n"
                           "| 2026-09-18 | 未裝 gitleaks（已解） | 沒裝 | 使用者 |\n| 2026-09-19 | 沒有 CI | 沒設 | 使用者 |\n")
    write(p17 / ".ai-review/config.md", old_fmt)
    rc, u, raw = unverified(p17, p17kit)
    check("T25 舊格式（沒有狀態欄）：相容、全部算未標狀態，不猜已解", u and not u["has_status_column"] and u["total"] == 2
          and u["no_status"] == 2 and u["resolved"] == 0, str(u) + raw[-200:])
    rc, out, err = kit("doctor", "--codex", str(root / "no-such-codex.exe"), cwd=p17, script=p17kit)
    check("T25 doctor 白話輸出提示舊格式沒有狀態欄", rc == 0 and "舊格式沒有「狀態」欄" in out, out[-400:])

    # ---------------- T26 doctor：裝完還缺什麼（唯讀、只提醒、不觸發登入）（G10，未發版）
    rc, out, err = kit("install", "--target", str(new_git_project(root, "p18-install-msg")))
    check("T26 install 結尾提示先跑 doctor 再 /safety-setup", rc == 0 and "doctor" in out and "/safety-setup" in out, out[-300:])
    write(p17 / ".ai-review/config.md", new_fmt.replace("```checks\nname | command | required\n```",
                                                        "```checks\nname | command | required\nok | echo ok | yes\n```")
          .replace("{{KIT_VERSION}}", "0.3.0").replace("{{DATE}}", "2026-10-11"))
    p17_before = tree_bytes(p17)

    def doc_json(*extra, env=None):
        rc, out, err = sh([PY, str(p17kit), "doctor", "--json", *extra], cwd=p17, env=env or ENV)
        try:
            return rc, json.loads(out), out + err
        except Exception:
            return rc, {}, out[-400:] + err[-400:]

    def item(info, key):
        return next((i for i in info.get("items", []) if i["key"] == key), {})

    rc, d, raw = doc_json("--codex", str(fake))
    check("T26 假 codex：在 PATH、已登入、node_repl 已設定、exit 0",
          rc == 0 and item(d, "codex")["ok"] is True and item(d, "codex_login")["ok"] is True and item(d, "node_repl")["ok"] is True,
          json.dumps(d, ensure_ascii=False)[:600])
    check("T26 不印 login status 的原文（可能含帳號）、從不走到登入流程",
          "fake-user@example.com" not in raw and "FAKE-LOGIN-FLOW" not in raw, raw[-400:])
    check("T26 專案段：已初始化、第 6 節未解 2 已解 1", (d.get("project") or {}).get("initialized") is True
          and ((d.get("project") or {}).get("unverified") or {}).get("open") == 2, json.dumps(d.get("project"), ensure_ascii=False))
    rc, d, raw = doc_json("--codex", str(fake), env=dict(ENV, FAKE_CODEX_LOGIN="out"))
    check("T26 未登入 → 列 ✗ 並提示 codex login，仍 exit 0", rc == 0 and item(d, "codex_login")["ok"] is False and "codex login" in item(d, "codex_login")["detail"], raw[-400:])
    rc, d, raw = doc_json("--codex", str(fake), env=dict(ENV, FAKE_CODEX_LOGIN="nostatus"))
    check("T26 codex 沒有 login status 子指令 → 不猜指令、請自己確認", rc == 0 and item(d, "codex_login")["ok"] is None
          and "請自己確認已登入" in item(d, "codex_login")["detail"] and "FAKE-LOGIN-FLOW" not in raw, raw[-400:])
    rc, d, raw = doc_json("--codex", str(fake), env=dict(ENV, FAKE_CODEX_MCP="none"))
    check("T26 沒設定 node_repl → 標 ？（正常，不算缺）", rc == 0 and item(d, "node_repl")["ok"] is None, raw[-400:])
    # 假 PATH：只有一支假 gitleaks；pip-audit 放在專案 .venv
    fakebin = root / "t26-bin"
    fakebin.mkdir()
    if os.name == "nt":
        write(fakebin / "gitleaks.cmd", "@echo off\r\n")
        write(p17 / ".venv/Scripts/pip-audit.cmd", "@echo off\r\n")
    else:
        for f in (fakebin / "gitleaks", p17 / ".venv/bin/pip-audit"):
            write(f, "#!/bin/sh\n")
            f.chmod(0o755)
    p17_before = tree_bytes(p17)
    rc, d, raw = doc_json(env=dict(ENV, PATH=str(fakebin)))
    check("T26 假 PATH：找不到 codex 列 ✗、gitleaks 找到、pip-audit 從專案 .venv 找到，exit 0",
          rc == 0 and item(d, "codex")["ok"] is False and item(d, "codex_login")["ok"] is None
          and item(d, "gitleaks")["ok"] is True and item(d, "pip_audit")["ok"] is True, json.dumps(d, ensure_ascii=False)[:700])
    rc, d, raw = doc_json(env=dict(ENV, PATH=str(root / "t26-empty")))
    check("T26 什麼都沒有：gitleaks ✗、pip-audit 不在 PATH 時仍從 .venv 找到、送審 Python 有實體路徑",
          rc == 0 and item(d, "gitleaks")["ok"] is False and item(d, "python")["detail"], json.dumps(d, ensure_ascii=False)[:500])
    rc, out, err = sh([PY, str(p17kit), "doctor", "--codex", str(fake)], cwd=p17)
    check("T26 白話輸出有表格與「只提醒」說明", rc == 0 and "| Codex 登入 | ✓ |" in out and "只提醒" in out and "唯讀" in out, out[-500:])
    check("T26 唯讀：doctor 跑完專案每個檔位元組都沒變", tree_bytes(p17) == p17_before)
    check("T26 --json 欄位齊全", all(k in d for k in ("target", "items", "project", "note"))
          and {i["key"] for i in d["items"]} == {"git", "codex", "codex_login", "node_repl", "codex_permissions", "gitleaks", "pip_audit",
                                                    "python", "claude_agent"}, str(d)[:300])
    # 守門 hook 的 py 與 claude 版本也要查（RV-8，T-0199 W4）：用只放假 py、假 claude 的 PATH，結果不受跑測試的電腦影響
    def fake_bin(dirname, claude_ver=None, with_py=True):
        b = root / dirname
        b.mkdir(exist_ok=True)
        if os.name == "nt":
            if with_py:
                write(b / "py.cmd", "@echo off\r\n")
            if claude_ver:
                write(b / "claude.cmd", f"@echo {claude_ver} (Claude Code)\r\n")
        else:
            for name, body in (("py", "#!/bin/sh\n") if with_py else (None, None),
                               ("claude", f"#!/bin/sh\necho '{claude_ver} (Claude Code)'\n") if claude_ver else (None, None)):
                if name:
                    write(b / name, body)
                    (b / name).chmod(0o755)
        return str(b)

    rc, d, raw = doc_json(env=dict(ENV, PATH=fake_bin("t26-agentbin", claude_ver="2.1.300")))
    check("T26 doctor 的 claude_agent：已安裝的子代理定義含 omitClaudeMd 與 review-guard → ✓",
          item(d, "claude_agent").get("ok") is True, json.dumps(item(d, "claude_agent"), ensure_ascii=False))
    check("T26 doctor 的 claude_agent：py 找得到、列出 Claude Code 版本與信任／開在專案根的提醒",
          "py 找得到" in item(d, "claude_agent").get("detail", "") and "2.1.300" in item(d, "claude_agent").get("detail", "")
          and "信任" in item(d, "claude_agent").get("detail", ""), json.dumps(item(d, "claude_agent"), ensure_ascii=False))
    rc, d, raw = doc_json(env=dict(ENV, PATH=fake_bin("t26-nopy", claude_ver="2.1.300", with_py=False)))
    ca = item(d, "claude_agent")
    check("T26 doctor：agent 檔 command 是 py 但找不到 py → claude_agent ✗，說明用 reviewer-agent --python 或手改 python3（RV-8）",
          rc == 0 and ca.get("ok") is False and "找不到 py" in ca.get("detail", "") and "reviewer-agent" in ca.get("detail", "")
          and "python3" in ca.get("detail", ""), json.dumps(ca, ensure_ascii=False))
    rc, d, raw = doc_json(env=dict(ENV, PATH=fake_bin("t26-oldclaude", claude_ver="2.1.200")))
    ca = item(d, "claude_agent")
    check("T26 doctor：claude --version 低於 2.1.271 → claude_agent ✗「太舊」（RV-8）",
          rc == 0 and ca.get("ok") is False and "太舊" in ca.get("detail", "") and "2.1.271" in ca.get("detail", ""),
          json.dumps(ca, ensure_ascii=False))
    rc, d, raw = doc_json(env=dict(ENV, PATH=fake_bin("t26-noclaude")))
    ca = item(d, "claude_agent")
    check("T26 doctor：找不到 claude → 版本寫「未知」、不算失敗（RV-8）",
          rc == 0 and ca.get("ok") is True and "未知" in ca.get("detail", ""), json.dumps(ca, ensure_ascii=False))

    # ---------------- T27 state.json 不進版控：.gitignore 補一行、仍被追蹤只提醒不動 index（未發版）
    p19 = new_git_project(root, "p19-state-ignore")
    rc, out, err = kit("install", "--target", str(p19))
    gi = read(p19 / ".gitignore")
    check("T27 新裝專案 .gitignore 含 .ai-review/state.json、git 也認定忽略",
          rc == 0 and ".ai-review/state.json" in gi.splitlines() and git("check-ignore", "-q", ".ai-review/state.json", cwd=p19)[0] == 0, gi)
    check("T27 新裝專案（state.json 沒被追蹤）不出現版控提醒", "還在版控" not in out, out[-300:])
    p20 = new_git_project(root, "p20-state-manual")
    write(p20 / ".gitignore", "node_modules/\n.ai-review/state.json\n")
    kit("install", "--target", str(p20))
    kit("update", "--target", str(p20))
    gi = read(p20 / ".gitignore")
    check("T27 已經手動加過同一行 → install／update 都不重複（其他三行照補）", gi.splitlines().count(".ai-review/state.json") == 1
          and gi.count("# ai-review-kit") <= 1 and ".ai-review/local.json" in gi.splitlines(), gi)
    # 模擬舊版：.gitignore 沒有這行、state.json 已被 commit
    p21 = new_git_project(root, "p21-state-tracked")
    kit("install", "--target", str(p21))
    write(p21 / ".gitignore", read(p21 / ".gitignore").replace(".ai-review/state.json\n", ""))
    git("add", "-A", cwd=p21)
    git("add", "-f", ".ai-review/state.json", cwd=p21)
    git("commit", "-q", "-m", "old kit commits state.json", cwd=p21)
    idx_before = (p21 / ".git/index").read_bytes()
    rc, out, err = kit("update", "--target", str(p21))
    gi = read(p21 / ".gitignore")
    check("T27 舊專案 update 補上 .gitignore 那一行（不重複標題）",
          rc == 0 and gi.splitlines().count(".ai-review/state.json") == 1 and gi.count("# ai-review-kit") == 1, gi)
    check("T27 state.json 仍被追蹤 → 白話提醒 git rm --cached，且說檔案會留著",
          "還在版控" in out and "git rm --cached .ai-review/state.json" in out and "檔案會留在電腦上" in out, out[-500:])
    rc2, ls, _ = git("ls-files", "--error-unmatch", ".ai-review/state.json", cwd=p21)
    check("T27 kit 沒有自己 git rm：state.json 還在 index、index 檔位元組沒變",
          rc2 == 0 and (p21 / ".git/index").read_bytes() == idx_before and (p21 / ".ai-review/state.json").exists())

    # ---------------- T30 claude-review：隔離 Claude 子代理審查的開始與收尾（0.5.0）
    p26 = new_git_project(root, "p26-claude-review")
    kit("install", "--target", str(p26))
    p26kit = p26 / ".ai-review/kit/kit.py"
    write(p26 / ".ai-review/config.md", read(KIT_ROOT / "templates/config.md").replace(
        "```checks\nname | command | required\n```",
        "```checks\nname | command | required\nok | echo ok | yes\nchain | echo a && echo b | no\n```"))
    cache26 = p26 / ".ai-review/.cache"

    def new_handoff(proj, script, scope):
        rc, out, err = kit("snapshot", "--json", cwd=proj, script=script)
        sn = json.loads(out) if rc == 0 else {}
        hid = sn.get("id", "H-missing")
        write(proj / f".ai-review/handoffs/{hid}.md", front(hid, "handoff", target=sn.get("target"), snapshot_ref=sn.get("snapshot_ref"),
                                                             head=sn.get("head"), base=sn.get("base"), recheck_of="", scope=scope))
        return hid, sn

    def review_file(proj, rid, hid, tgt, reviewer="claude-isolated", verdict="no-blocking-found", model="fable"):
        kv = dict(handoff=hid, target=tgt, reviewer=reviewer, verdict=verdict, blocking=0)
        if model:
            kv.update(reviewer_model=model, reviewer_isolation="subagent;omitClaudeMd;no-memory;review-guard")
        write(proj / f".ai-review/reviews/{rid}.md", front(rid, "review", **kv))

    H30, sn30 = new_handoff(p26, p26kit, "t30")
    running30 = cache26 / f"claude-{H30}.running"
    done30p = cache26 / f"claude-{H30}.done"
    before = snapshot(p26)
    rc, out, err = kit("claude-review", "--begin", H30, "--print", cwd=p26, script=p26kit)
    check("T30 --begin --print：印派工資訊、不寫任何檔", rc == 0 and "可派審查員" in out and H30 in out and snapshot(p26) == before,
          out[-500:] + err[-300:])
    rc, out, err = kit("claude-review", "--end", H30, "--model", "fable", cwd=p26, script=p26kit)
    check("T30 --end 沒有開始紀錄（.running）→ exit 2 並叫先 --begin", rc == 2 and "--begin" in out, out[-300:] + err[-300:])
    rc, out, err = kit("claude-review", "--begin", H30, cwd=p26, script=p26kit)
    rj = json.loads(read(running30)) if running30.exists() else {}
    check("T30 --begin 寫 .running（pid、開始時間、審前清單）",
          rc == 0 and rj.get("handoff") == H30 and isinstance(rj.get("pid"), int) and rj.get("started")
          and isinstance(rj.get("before"), dict) and "app.py" in rj["before"], out[-400:] + err[-300:] + json.dumps(rj)[:300])
    check("T30 --begin 印 H、專案絕對路徑、模型建議（與開發 AI 不同的別名）",
          H30 in out and p26.resolve().as_posix() in out and "fable" in out and "opus" in out and "不同" in out, out[-600:])
    check("T30 --begin 印的專案路徑一律正斜線（RV-7：審查員照抄不加引號也不會被 bash 吃掉反斜線）",
          (os.name != "nt" or str(p26.resolve()) not in out) and f"專案：{p26.resolve().as_posix()}" in out, out[-600:])
    check("T30 --begin 寫 .running 時一併記下審前報告清單、清空守門心跳紀錄",
          isinstance(rj.get("reviews_before"), dict) and (cache26 / f"claude-{H30}.guard.jsonl").is_file()
          and read(cache26 / f"claude-{H30}.guard.jsonl") == "", json.dumps(rj, ensure_ascii=False)[:300])
    # RV-10：kit 印的派工 prompt 與 review-ready skill 第 11A 步的四行是同一份
    skill_rr = read(KIT_ROOT / "claude/skills/review-ready/SKILL.md")
    plines = [l.strip().replace(p26.resolve().as_posix(), "<專案>").replace(H30, "<H-id>") for l in out.splitlines()]
    pstart = next((i for i, l in enumerate(plines) if l.startswith("專案：")), None)
    prompt4 = plines[pstart:pstart + 4] if pstart is not None else []
    check("T30 kit 印的四行 prompt 與 review-ready skill 的四行逐字相同（RV-10）",
          len(prompt4) == 4 and prompt4[1] == "交接：<H-id>" and prompt4[2] == "reviewer_model：<別名>"
          and all(("\n      " + l + "\n") in skill_rr for l in prompt4), json.dumps(prompt4, ensure_ascii=False))
    rc, out, err = kit("claude-review", "--begin", H30, cwd=p26, script=p26kit)
    check("T30 審查還在進行（.running 沒逾時）再 --begin → exit 1、提示 --again", rc == 1 and "--again" in out, out[-300:])
    rc, out, err = kit("claude-review", "--end", H30, cwd=p26, script=p26kit)
    check("T30 --end 沒帶 --model → exit 2", rc == 2 and "--model" in out, out[-300:])
    rc, out, err = kit("claude-review", "--end", H30, "--model", "a b", cwd=p26, script=p26kit)
    check("T30 --model 別名不合法 → exit 2", rc == 2 and "不接受" in out, out[-300:])
    review_file(p26, "R-20990102-0001", H30, sn30["target"], reviewer="claude", model=None)
    rc, out, err = kit("state", "--json", cwd=p26, script=p26kit)
    st = json.loads(out) if rc == 0 else {}
    check("T30 reviewer: claude 仍不算獨立審查", st.get("status") == "pending-review"
          and any("不算獨立審查" in n for n in st.get("notes", [])), out[-400:])
    check("T30 待審的未結案寫兩條路線（claude-review 與 codex-review）",
          any("claude-review --begin" in o and "codex-review" in o and "$independent-review" in o for o in st.get("open_items", [])),
          json.dumps(st.get("open_items"), ensure_ascii=False))
    rc, out, err = kit("claude-review", "--end", H30, "--model", "fable", cwd=p26, script=p26kit)
    check("T30 找不到隔離 Claude 的 R → exit 1、提示看子代理回報、開始紀錄留著（補好 R 可再 --end）",
          rc == 1 and "子代理" in out and "R-20990102-0001" in out and running30.exists() and not done30p.exists(), out[-500:])
    check("T30 審查期間新寫的 R 的 reviewer 不是 claude-isolated → 點名（RV-2）",
          "R-20990102-0001.md（reviewer claude）" in out and "reviewer 不是 claude-isolated" in out, out[-500:])
    # 審查員寫錯 reviewer → 重派（--again 重記審前清單：R-0001 變成審前就有的報告）
    rc, out, err = kit("claude-review", "--begin", H30, "--again", cwd=p26, script=p26kit)
    check("T30 --begin --again 重記審前清單（剛才那份 R 算審前就有）", rc == 0 and "R-20990102-0001.md" in
          json.loads(read(running30)).get("reviews_before", {}), out[-300:])

    def guard_call(proj_kit, payload):
        return kit("hook", "review-guard", script=proj_kit, input_text=json.dumps(payload).encode("utf-8"), cwd=root)

    # 審查員第 0 步的守門自檢（echo guard-canary 應被擋）→ 守門心跳 1 筆
    rc, out, err = guard_call(p26kit, {"tool_name": "Bash", "tool_input": {"command": "echo guard-canary"}, "cwd": str(p26)})
    glog30 = cache26 / f"claude-{H30}.guard.jsonl"
    gl = [json.loads(x) for x in read(glog30).splitlines() if x.strip()] if glog30.exists() else []
    check("T30 守門自檢 echo guard-canary 被擋（exit 2），守門心跳記一行：時間、工具名、擋下，不記指令（RV-1）",
          rc == 2 and len(gl) == 1 and gl[0].get("tool") == "Bash" and gl[0].get("decision") == "block" and gl[0].get("time")
          and "guard-canary" not in read(glog30), read(glog30) if glog30.exists() else "沒有心跳檔")
    # 2026-11-01 真 Claude Code 實跑：審查員寫了 verdict: blocked → --end 不收尾、exit 1、開始紀錄留著
    review_file(p26, "R-20990102-0002", H30, sn30["target"], verdict="blocked")
    rc, out, err = kit("claude-review", "--end", H30, "--model", "fable", cwd=p26, script=p26kit)
    check("T30 新 R 的 verdict 不是三種合法值 → exit 1、不寫 .done、開始紀錄留著（補好可再 --end）",
          rc == 1 and "blocked" in out and not done30p.exists() and running30.exists(), out[-400:])
    review_file(p26, "R-20990102-0002", H30, sn30["target"])
    before = snapshot(p26)
    rc, out, err = kit("claude-review", "--end", H30, "--model", "fable", "--print", cwd=p26, script=p26kit)
    check("T30 --end --print：找到 R、只印不寫", rc == 0 and "R-20990102-0002" in out and snapshot(p26) == before and running30.exists(),
          out[-400:])
    rc, out, err = kit("claude-review", "--end", H30, "--model", "fable", cwd=p26, script=p26kit)
    dj = json.loads(read(done30p)) if done30p.exists() else {}
    check("T30 --end 寫 .done：reviewer claude-isolated、reviewer_model、isolation、審查編號與結論",
          rc == 0 and dj.get("reviewer") == "claude-isolated" and dj.get("reviewer_model") == "fable"
          and "review-guard" in (dj.get("isolation") or "") and dj.get("review") == "R-20990102-0002"
          and dj.get("verdict") == "no-blocking-found", out[-500:] + json.dumps(dj, ensure_ascii=False)[:500])
    check("T30 .done 欄位＝codex 的 .done 欄位（T18，不變）＋reviewer、reviewer_model、isolation、guard_calls",
          set(done) == {"handoff", "exit", "started", "finished", "review", "verdict", "sandbox_env", "permissions"}
          and set(dj) == set(done) | {"reviewer", "reviewer_model", "isolation", "guard_calls"}, str(sorted(done)) + " / " + str(sorted(dj)))
    check("T30 有守門心跳 → .done 記 guard_calls 1、isolation 照報告（review-guard），不出守門警告",
          dj.get("guard_calls") == 1 and dj.get("isolation") == "subagent;omitClaudeMd;no-memory;review-guard"
          and "守門 hook 沒有執行紀錄" not in out, json.dumps(dj, ensure_ascii=False)[:300] + out[-300:])
    check("T30 乾淨的審查：.done 沒有警告、開始紀錄已清", "warnings" not in dj and "workspace_changes" not in dj and not running30.exists(),
          json.dumps(dj, ensure_ascii=False)[:400])
    st = json.loads(read(p26 / ".ai-review/state.json"))
    check("T30 狀態 no-blocking-found；state.json 的 review 帶 reviewer_model、reviewer_isolation",
          st["status"] == "no-blocking-found" and (st.get("review") or {}).get("reviewer_model") == "fable"
          and "review-guard" in ((st.get("review") or {}).get("reviewer_isolation") or ""), json.dumps(st, ensure_ascii=False)[:500])
    check("T30 --end 輸出 R 編號、結論並標「非 Codex 審查」", "R-20990102-0002" in out and "no-blocking-found（非 Codex 審查）" in out, out[-500:])
    rc, out, err = kit("status", cwd=p26, script=p26kit)
    check("T30 status 顯示「非 Codex 審查」、模型與子代理已安裝",
          rc == 0 and "結論 no-blocking-found（非 Codex 審查）" in out and "模型 fable" in out and "independent-reviewer ✓" in out, out[-600:])
    rc, out, err = kit("status", "--json", cwd=p26, script=p26kit)
    check("T30 status --json 有 claude_agent", rc == 0 and json.loads(out).get("claude_agent") is True, out[-300:])
    rc, out, err = kit("state", cwd=p26, script=p26kit)
    check("T30 state（人看的輸出）結論後標「非 Codex 審查」", rc == 0 and "no-blocking-found（非 Codex 審查）" in out, out[-400:])
    rc, out, err = kit("hook", "session-start", cwd=p26, script=p26kit, input_text=b"{}")
    check("T30 SessionStart hook 結論後標「非 Codex 審查」", rc == 0 and "no-blocking-found（非 Codex 審查）" in out, out[-500:])
    rc, out, err = kit("gate", cwd=p26, script=p26kit)
    check("T30 gate 不帶參數：隔離 Claude 審查照常通過（行為不變）", rc == 0, out[-400:])
    rc, out, err = kit("gate", "--require-reviewer", "codex", cwd=p26, script=p26kit)
    check("T30 gate --require-reviewer codex：claude-isolated → exit 1「發版前需 Codex 審查」", rc == 1 and "發版前需 Codex 審查" in out,
          out[-400:])
    review_file(p26, "R-20990102-0003", H30, sn30["target"], reviewer="codex", model=None)
    rc, out, err = kit("gate", "--require-reviewer", "codex", cwd=p26, script=p26kit)
    check("T30 gate --require-reviewer codex：沒有 codex-review 紀錄、也不在守門寫檔紀錄（手動開 Codex 審）→ exit 0＋提示依檔頭採信",
          rc == 0 and "未見 codex-review 執行紀錄（手動開 Codex 審查），依報告檔頭採信；守門沒生效時無法分辨" in out
          and "通過條件成立" in out, out[-500:])
    write(cache26 / f"codex-{H30}.done", json.dumps({"handoff": H30, "exit": 0, "review": "R-20990102-0002"}))
    rc, out, err = kit("gate", "--require-reviewer", "codex", cwd=p26, script=p26kit)
    check("T30 gate --require-reviewer codex：codex 執行紀錄指向別份報告 → exit 1", rc == 1 and "R-20990102-0002" in out
          and f"codex-{H30}.done" in out, out[-400:])
    write(cache26 / f"codex-{H30}.done", json.dumps({"handoff": H30, "exit": 0, "review": "R-20990102-0003"}))
    rc, out, err = kit("gate", "--require-reviewer", "codex", cwd=p26, script=p26kit)
    check("T30 gate --require-reviewer codex：最新有效審查是 codex → exit 0", rc == 0 and "通過條件成立" in out, out[-400:])
    check("T30 gate --require-reviewer codex：codex-review 紀錄指向這份 → 不印「未見執行紀錄」", "未見 codex-review" not in out, out[-400:])
    check("T30 gate 印出這份交接的審查歷程一行（RV-5）",
          f"審查歷程（交接 {H30}）" in out and "R-20990102-0001 claude" in out and "R-20990102-0003 codex no-blocking-found（採用）" in out,
          out[-600:])
    rc, out, err = kit("state", cwd=p26, script=p26kit)
    check("T30 Codex 審查的輸出不加「非 Codex 審查」", rc == 0 and "結論 no-blocking-found  審查者 codex" in out and "非 Codex" not in out,
          out[-400:])
    # 第二輪：審查期間多出檔 → 警告、不刪；R 的 reviewer_model 與 --model 不同 → 提醒
    H30b, sn30b = new_handoff(p26, p26kit, "t30b")
    rc, out, err = kit("claude-review", "--begin", H30b, cwd=p26, script=p26kit)
    check("T30 第二輪 --begin exit 0", rc == 0, out[-300:])
    write(p26 / "stray_by_reviewer.txt", "x\n")
    review_file(p26, "R-20990102-0004", H30b, sn30b["target"], model="opus")
    rc, out, err = kit("claude-review", "--end", H30b, "--model", "fable", cwd=p26, script=p26kit)
    dj2p = cache26 / f"claude-{H30b}.done"
    dj2 = json.loads(read(dj2p)) if dj2p.exists() else {}
    check("T30 審查期間多出檔 → 輸出警告並列出路徑、.done 記 workspace_changes 與指紋漂移",
          rc == 0 and "stray_by_reviewer.txt" in out and "不會自動刪" in out
          and "stray_by_reviewer.txt" in (dj2.get("workspace_changes") or {}).get("added", []) and dj2.get("fingerprint_drift") is True
          and "claude-review --begin" in out, out[-800:] + json.dumps(dj2, ensure_ascii=False)[:500])
    check("T30 多出來的檔沒有被刪", (p26 / "stray_by_reviewer.txt").is_file())
    check("T30 R 的 reviewer_model 與 --model 不同 → 提醒，.done 記 --model 的值",
          "與 --model fable 不同" in out and dj2.get("reviewer_model") == "fable", out[-600:])

    # ---------------- T31 review-guard：審查員子代理的守門 hook（0.5.0）
    pj = str(p26.resolve())
    rv = p26.resolve() / ".ai-review" / "reviews"
    p26kit_s = str(p26kit.resolve())
    p10kit_s = str(p10kit.resolve())

    def guard(payload=None, raw=None, script=p26kit, cwd=root):
        data = raw if raw is not None else json.dumps(payload).encode("utf-8")
        return kit("hook", "review-guard", cwd=cwd, script=script, input_text=data)

    def g_edit(path, tool="Edit", hcwd=None):
        return guard({"tool_name": tool, "tool_input": {"file_path": str(path), "old_string": "a", "new_string": "b", "content": "x"},
                      "cwd": hcwd or str(root), "agent_type": "independent-reviewer", "hook_event_name": "PreToolUse"})

    def g_bash(cmd, hcwd=None):
        return guard({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": hcwd or str(root),
                      "agent_type": "independent-reviewer", "hook_event_name": "PreToolUse"})

    def expect(name, res, code):
        rc, out, err = res
        check(f"T31 {name} → exit {code}", rc == code, f"rc={rc} {out[-200:]} {err[-300:]}")

    # 守門要有開審紀錄才准寫（RV-2）：先開一輪審查（新交接 H31）
    H31, sn31 = new_handoff(p26, p26kit, "t31")
    rc, out, err = kit("claude-review", "--begin", H31, cwd=p26, script=p26kit)
    check("T31 前置：claude-review --begin（守門要有開審紀錄才准寫）", rc == 0, out[-300:])
    glog31 = cache26 / f"claude-{H31}.guard.jsonl"
    # 檔案工具
    expect("Write 到 reviews/R-*.md 放行（hook 程序 cwd 在專案外，也找得到專案）", g_edit(rv / "R-20990103-0001.md", "Write"), 0)
    expect("Edit 到 reviews/R-*.md 放行", g_edit(rv / "R-20990103-0001.md"), 0)
    expect("MultiEdit 到 reviews/R-*.md 放行", g_edit(rv / "R-20990103-0001.md", "MultiEdit"), 0)
    expect("Edit 到 reviews 外（app.py）擋", g_edit(p26 / "app.py"), 2)
    expect("Write 到 handoffs 擋", g_edit(p26 / f".ai-review/handoffs/{H30}.md", "Write"), 2)
    expect("Edit 路徑含 .. 跳出 reviews 擋", g_edit(str(rv) + "/../handoffs/x.md"), 2)
    expect("Edit 路徑含 ..（繞一圈回 reviews）也擋", g_edit(str(rv) + "/../reviews/R-20990103-0001.md"), 2)
    expect("reviews 底下不是 R-*.md（notes.md）擋", g_edit(rv / "notes.md", "Write"), 2)
    expect("reviews 底下子資料夾擋", g_edit(rv / "sub" / "R-20990103-0001.md", "Write"), 2)
    expect("檔名帶 :（Windows 替代資料流）擋", g_edit(str(rv / "R-20990103-0001.md") + ":evil", "Write"), 2)
    expect("別專案的 reviews/R-*.md 擋", g_edit(p10.resolve() / ".ai-review/reviews/R-20990103-0001.md", "Write"), 2)
    expect("相對路徑以 hook 的 cwd 解析：cwd＝專案 → reviews 內放行", g_edit(".ai-review/reviews/R-20990103-0001.md", "Write", hcwd=pj), 0)
    expect("相對路徑以 hook 的 cwd 解析：cwd＝上層 → 不在 reviews 擋", g_edit(".ai-review/reviews/R-20990103-0001.md", "Write"), 2)
    if os.name == "nt":
        expect("Windows 不分大小寫：大寫路徑到 reviews 放行", g_edit(str(rv).upper() + "\\R-20990103-0001.md", "Write"), 0)
        expect("斜線方向：正斜線路徑到 reviews 放行", g_edit(str(rv).replace("\\", "/") + "/R-20990103-0001.md", "Write"), 0)
        msys = "/" + pj[0].lower() + pj[2:].replace("\\", "/") + "/.ai-review/reviews/R-20990103-0001.md"
        expect("Git Bash 風格 /c/... 路徑到 reviews 放行", g_edit(msys, "Write"), 0)
        expect("大寫路徑到 reviews 外仍擋", g_edit(str(p26 / "app.py").upper()), 2)
    link = rv / "R-20990103-0099.md"
    try:
        os.symlink(str(p26 / "app.py"), str(link))
        linked = True
    except (OSError, NotImplementedError):
        linked = False
        print("（T31 這台電腦不能建符號連結，略過「符號連結跳出」測試）")
    if linked:
        expect("reviews 裡的符號連結指到 reviews 外擋", g_edit(link, "Write"), 2)
    expect("NotebookEdit 擋", guard({"tool_name": "NotebookEdit", "tool_input": {"notebook_path": str(rv / "R-1.md")}, "cwd": str(root)}), 2)
    for t in ("Read", "Grep", "Glob"):
        expect(f"{t} 放行", guard({"tool_name": t, "tool_input": {"file_path": str(p26 / "app.py"), "pattern": "x"}, "cwd": str(root)}), 0)
    # Bash：git
    expect("git diff 放行", g_bash("git diff"), 0)
    expect("git 多空白（git  diff   HEAD）放行", g_bash("git  diff   HEAD"), 0)
    expect("git --no-pager log --oneline -5 放行", g_bash("git --no-pager log --oneline -5"), 0)
    expect("git -C \"本專案\" diff 放行", g_bash(f'git -C "{pj}" diff HEAD'), 0)
    expect("git -C 相對路徑（以 hook cwd 解析到本專案）放行", g_bash("git -C p26-claude-review status"), 0)
    expect("git show／ls-files／rev-parse／cat-file 放行",
           (max(g_bash(c)[0] for c in ("git show HEAD --stat", "git ls-files", "git rev-parse HEAD", "git cat-file -p HEAD")), "", ""), 0)
    expect("git -C 別專案擋", g_bash(f'git -C "{p10.resolve()}" diff'), 2)
    expect("git diff --output=x 擋", g_bash("git diff --output=x.txt"), 2)
    expect("git diff --outp=x（縮寫）擋", g_bash("git diff --outp=x.txt"), 2)
    expect("git diff --output x（分開寫）擋", g_bash("git diff --output x.txt"), 2)
    expect("git log --ext-diff 擋", g_bash("git log --ext-diff"), 2)
    expect("git show --textconv 擋", g_bash("git show --textconv HEAD"), 2)
    expect("git -c core.pager=x diff 擋", g_bash("git -c core.pager=evil diff"), 2)
    expect("git --exec-path=x diff 擋", g_bash("git --exec-path=/tmp diff"), 2)
    expect("git diff && del x 擋", g_bash("git diff && del x"), 2)
    expect("git diff; rm x 擋", g_bash("git diff; rm x"), 2)
    expect("git diff | tee x 擋", g_bash("git diff | tee x"), 2)
    expect("git diff > x 擋", g_bash("git diff > x"), 2)
    expect("git log $(rm x) 擋", g_bash("git log $(rm x)"), 2)
    expect("git log `rm x` 擋", g_bash("git log `rm x`"), 2)
    expect("git diff 換行 rm x 擋", g_bash("git diff\nrm x"), 2)
    expect("git $'-c' x=y diff（ANSI 引號偷渡 -c）擋", g_bash("git $'-c' x=y diff"), 2)
    expect("git {diff,--output=x}（大括號展開）擋", g_bash("git {diff,--output=x}"), 2)
    expect("git diff *（萬用字元）擋", g_bash("git diff *"), 2)
    expect("GIT_EXTERNAL_DIFF=x git diff（前置環境變數）擋", g_bash("GIT_EXTERNAL_DIFF=evil git diff"), 2)
    expect("git push 擋", g_bash("git push"), 2)
    expect("git checkout -- app.py 擋", g_bash("git checkout -- app.py"), 2)
    expect("git config 擋", g_bash("git config core.pager evil"), 2)
    expect("git 別名或白名單外子命令（git difftool）擋", g_bash("git difftool"), 2)
    expect("'git' diff（引號包命令名仍是 git）放行", g_bash("'git' diff"), 0)
    # Bash：kit.py
    expect("py -3 本專案 kit.py verify 放行", g_bash(f'py -3 "{p26kit_s}" verify'), 0)
    expect("kit.py verify --handoff H --target 本專案 放行", g_bash(f'py -3 "{p26kit_s}" verify --handoff {H30} --target "{pj}"'), 0)
    expect("kit.py new-id R 放行", g_bash(f'py -3 "{p26kit_s}" new-id R'), 0)
    expect("kit.py new-id H 擋", g_bash(f'py -3 "{p26kit_s}" new-id H'), 2)
    expect("kit.py state --no-write --json 放行", g_bash(f'py -3 "{p26kit_s}" state --no-write --json'), 0)
    expect("kit.py state（會寫 state.json）擋", g_bash(f'py -3 "{p26kit_s}" state --json'), 2)
    expect("kit.py checks --run 放行", g_bash(f'py -3 "{p26kit_s}" checks --run --target "{pj}"'), 0)
    expect("kit.py checks --run --handoff H 擋（會蓋掉開發端的檢查紀錄）", g_bash(f'py -3 "{p26kit_s}" checks --run --handoff {H30}'), 2)
    expect("kit.py checks（沒 --run）擋", g_bash(f'py -3 "{p26kit_s}" checks'), 2)
    expect("kit.py install 擋", g_bash(f'py -3 "{p26kit_s}" install'), 2)
    expect("kit.py claude-review 擋", g_bash(f'py -3 "{p26kit_s}" claude-review --end {H30} --model x'), 2)
    expect("kit.py verify 多一個不認得的參數擋", g_bash(f'py -3 "{p26kit_s}" verify --json'), 2)
    expect("kit.py verify --handoff ../../x 擋", g_bash(f'py -3 "{p26kit_s}" verify --handoff ../../x'), 2)
    expect("kit.py verify --target 別專案擋", g_bash(f'py -3 "{p26kit_s}" verify --target "{p10.resolve()}"'), 2)
    expect("python3 本專案 kit.py verify 放行（小隊長 11-01：macOS／Linux 用）", g_bash(f'python3 "{p26kit_s}" verify'), 0)
    expect("python 本專案 kit.py verify 放行", g_bash(f'python "{p26kit_s}" verify'), 0)
    expect("python3 別專案 kit.py 擋", g_bash(f'python3 "{p10kit_s}" verify'), 2)
    expect("py（沒有 -3）擋", g_bash(f'py "{p26kit_s}" verify'), 2)
    expect("py -3 別專案 kit.py 擋", g_bash(f'py -3 "{p10kit_s}" verify'), 2)
    expect("py -3 -c 任意程式擋", g_bash('py -3 -c "print(1)"'), 2)
    expect("py -3 相對路徑（hook cwd＝專案）放行", g_bash("py -3 .ai-review/kit/kit.py verify", hcwd=pj), 0)
    expect("py -3 路徑含 ..、解析後仍是本專案 kit.py 放行", g_bash(f'py -3 "{pj}/.ai-review/kit/../kit/kit.py" verify'), 0)
    if os.name == "nt":
        expect("Windows 不分大小寫：大寫 kit.py 路徑放行", g_bash(f'py -3 "{p26kit_s.upper()}" verify'), 0)
        expect("正斜線 kit.py 路徑放行", g_bash(f'py -3 "{p26kit_s.replace(chr(92), "/")}" verify'), 0)
        expect("沒加引號的反斜線路徑（bash 會吃掉反斜線）擋", g_bash(f"py -3 {p26kit_s} verify"), 2)
    # Bash：config 第 4 節原文
    expect("config 第 4 節命令原文（echo ok）放行", g_bash("echo ok"), 0)
    expect("config 第 4 節命令多一個參數擋", g_bash("echo ok extra"), 2)
    expect("config 第 4 節命令多空白擋", g_bash("echo  ok"), 2)
    expect("config 第 4 節登記但含 && 的命令仍擋（改用 kit.py checks --run）", g_bash("echo a && echo b"), 2)
    expect("白名單外命令（cat app.py）擋", g_bash("cat app.py"), 2)
    # 其他
    expect("未知工具（WebFetch）擋", guard({"tool_name": "WebFetch", "tool_input": {"url": "http://x"}, "cwd": str(root)}), 2)
    expect("沒有 tool_name 擋", guard({"tool_input": {"command": "git diff"}, "cwd": str(root)}), 2)
    expect("壞 JSON 擋（fail-closed）", guard(raw=b"not json"), 2)
    expect("空的 stdin 擋（fail-closed）", guard(raw=b""), 2)
    expect("JSON 不是物件擋（fail-closed）", guard(raw=b"[1, 2]"), 2)
    expect("找不到專案（套件來源的 kit.py、cwd 不在專案裡）擋（fail-closed）",
           guard({"tool_name": "Bash", "tool_input": {"command": "git diff"}, "cwd": str(root)}, script=KIT_PY), 2)
    rc, out, err = g_bash("git diff --output=x.txt")
    check("T31 擋下時 stderr 給白話原因與白名單", rc == 2 and "擋下" in err and "只能寫" in err and "R-*.md" in err and "checks --run" in err,
          err[-500:])
    check("T31 放行時不輸出任何東西", g_bash("git diff")[1:] == ("", ""), str(g_bash("git diff")))
    check("T31 守門沒有在專案留下 x.txt 之類的檔", not (p26 / "x.txt").exists() and not (root / "x.txt").exists())
    # T-0199 W4：V2-B SubagentHandback、RV-9 --show-signature、RV-2 寫入規則、RV-1 心跳、RV-10 說明文字
    expect("SubagentHandback（子代理交最後回報，不碰檔案）放行（V2-B）",
           guard({"tool_name": "SubagentHandback", "tool_input": {"message": "R-x needs-fix"}, "cwd": str(root)}), 0)
    expect("其他未知工具（TodoWrite）仍擋", guard({"tool_name": "TodoWrite", "tool_input": {"todos": []}, "cwd": str(root)}), 2)
    expect("git log --show-signature 擋（會執行 gpg.program，RV-9）", g_bash("git log --show-signature"), 2)
    expect("git log --show-notes 放行（不是 show-signature 的縮寫）", g_bash("git log --show-notes"), 0)
    expect("Write 到審查開始前就有的 R（R-20990102-0002）擋（RV-2）", g_edit(rv / "R-20990102-0002.md", "Write"), 2)
    expect("Edit 審查開始前就有的 R（例如 Codex 的報告）擋（RV-2）", g_edit(rv / "R-20990102-0003.md"), 2)
    expect("MultiEdit 審查開始前就有的 R 擋", g_edit(rv / "R-20990102-0003.md", "MultiEdit"), 2)
    if os.name == "nt":
        expect("Edit 審查開始前就有的 R（檔名大小寫不同）仍擋", g_edit(str(rv) + "\\r-20990102-0003.MD"), 2)
    write(rv / "R-20990103-0002.md", front("R-20990103-0002", "review", handoff=H31, target=sn31["target"], reviewer="claude-isolated",
                                           verdict="needs-fix", blocking=1))
    expect("Edit 這次新寫的 R 放行", g_edit(rv / "R-20990103-0002.md"), 0)
    expect("Write 覆寫這次新寫、已存在的 R 擋（改用 Edit）", g_edit(rv / "R-20990103-0002.md", "Write"), 2)
    rc, out, err = g_edit(rv / "R-20990103-0002.md", "Write")
    check("T31 Write 已存在的 R → 原因寫「Write 只能建新的…用 Edit」", "Write 只能建新的審查報告" in err and "Edit" in err, err[-300:])
    gl31 = [json.loads(x) for x in read(glog31).splitlines() if x.strip()] if glog31.exists() else []
    edit_tools = {"Write", "Edit", "MultiEdit"}
    check("T31 守門心跳：每次呼叫都記一行（有放行也有擋下），時間、工具名、決定三欄；放行的寫檔多記 R 檔名（RV-1）",
          len(gl31) > 50 and {g.get("decision") for g in gl31} == {"allow", "block"}
          and all(set(g) == ({"time", "tool", "decision", "nested", "file"} if (g["tool"] in edit_tools and g["decision"] == "allow")
                             else {"time", "tool", "decision", "nested"}) for g in gl31)
          and all(g.get("nested") is False for g in gl31)
          and "SubagentHandback" in {g.get("tool") for g in gl31}, f"{len(gl31)} 筆 " + json.dumps(gl31[:3], ensure_ascii=False))
    gfiles = {g.get("file") for g in gl31 if "file" in g}
    check("T31 心跳的寫檔紀錄只有 R 檔名（不含路徑），擋下的寫檔不記檔名",
          "R-20990103-0002.md" in gfiles and all(f and "/" not in f and "\\" not in f and f.upper().startswith("R-") for f in gfiles)
          and "R-20990102-0003.md" not in gfiles and "notes.md" not in gfiles, json.dumps(sorted(gfiles), ensure_ascii=False))
    check("T31 守門心跳不記指令與路徑內容", "git diff" not in read(glog31) and pj not in read(glog31) and "p26-claude-review" not in read(glog31),
          read(glog31)[:300])
    rc, out, err = g_bash("git diff --output=x.txt")
    check("T31 擋下說明：new-id 只准 R、只有 state 能帶 --json、路徑用雙引號或正斜線（RV-10／RV-7）",
          "new-id R" in err and "只有 state 可帶 --json" in err and "雙引號或正斜線" in err, err[-600:])
    # 沒有任何開審紀錄 → 所有寫入都擋（強制先 --begin）；指令照白名單
    p10rv = p10.resolve() / ".ai-review" / "reviews"
    p10_guard = lambda pl: guard(pl, script=p10kit)
    expect("沒有開審紀錄（.running）時 Write 到 reviews/R-*.md 也擋（RV-2）",
           p10_guard({"tool_name": "Write", "tool_input": {"file_path": str(p10rv / "R-20990103-0001.md"), "content": "x"},
                      "cwd": str(root)}), 2)
    rc, out, err = p10_guard({"tool_name": "Write", "tool_input": {"file_path": str(p10rv / "R-20990103-0001.md"), "content": "x"},
                              "cwd": str(root)})
    check("T31 沒有開審紀錄 → 原因寫要先 claude-review --begin", "claude-review --begin" in err, err[-300:])
    expect("沒有開審紀錄時唯讀指令照放（git diff）", p10_guard({"tool_name": "Bash", "tool_input": {"command": "git diff"}, "cwd": str(p10)}), 0)
    write(p10 / ".ai-review/.cache/claude-H-20990101-0000.running", "{}\n")
    expect("開審紀錄是舊版格式（沒有審前報告清單）→ 寫入擋",
           p10_guard({"tool_name": "Write", "tool_input": {"file_path": str(p10rv / "R-20990103-0001.md"), "content": "x"},
                      "cwd": str(root)}), 2)
    check("T31 開審紀錄讀不懂時心跳照記（寫到該交接的心跳檔）",
          (p10 / ".ai-review/.cache/claude-H-20990101-0000.guard.jsonl").is_file())

    # ---------------- T32 reviewer-agent：巢狀專案用的子代理定義（0.5.0）
    sess = root / "t32-session"
    nested = new_git_project(sess / "sub", "proj")
    kit("install", "--target", str(nested))
    nk = nested / ".ai-review/kit/kit.py"
    agent_installed = read(nested / ".claude/agents/independent-reviewer.md")
    rc, out, err = kit("reviewer-agent", "--session-root", str(sess), cwd=root, script=nk)
    outn = out.replace("\r\n", "\n")
    check("T32 巢狀：hook 路徑換成 ${CLAUDE_PROJECT_DIR}/sub/proj/.ai-review/kit/kit.py",
          rc == 0 and "${CLAUDE_PROJECT_DIR}/sub/proj/.ai-review/kit/kit.py" in outn
          and "${CLAUDE_PROJECT_DIR}/.ai-review/kit/kit.py" not in outn, out[-400:] + err[-300:])
    check("T32 只換 hook 路徑、其他內容原樣", outn.replace("${CLAUDE_PROJECT_DIR}/sub/proj/", "${CLAUDE_PROJECT_DIR}/")
          == agent_installed.replace("\r\n", "\n"), outn[:300])
    check("T32 輸出不含絕對路徑", str(sess) not in out and str(sess.resolve()) not in out and str(root) not in out, out[:300])
    rc, out, err = kit("reviewer-agent", "--session-root", str(nested), cwd=root, script=nk)
    check("T32 對話根就是專案 → hook 路徑不變", rc == 0 and "${CLAUDE_PROJECT_DIR}/.ai-review/kit/kit.py" in out, out[-300:] + err[-300:])
    if os.name == "nt":
        rc, out, err = kit("reviewer-agent", "--session-root", str(sess).upper(), cwd=root, script=nk)
        check("T32 Windows 不分大小寫：大寫的對話根也認得、相對路徑照專案原本大小寫",
              rc == 0 and "${CLAUDE_PROJECT_DIR}/sub/proj/.ai-review/kit/kit.py" in out, out[-300:] + err[-300:])
    (root / "t32-elsewhere").mkdir(exist_ok=True)
    rc, out, err = kit("reviewer-agent", "--session-root", str(root / "t32-elsewhere"), cwd=root, script=nk)
    check("T32 專案不在對話根底下 → 拒絕（exit 2）", rc == 2 and "不在" in err and out.strip() == "", out[-300:] + err[-300:])
    rc, out, err = kit("reviewer-agent", "--session-root", str(sess / "su"), cwd=root, script=nk)
    check("T32 名稱前綴相同但不是上層（sess/su vs sess/sub）→ 拒絕", rc == 2, out[-300:] + err[-300:])
    outf = root / "t32-out" / "independent-reviewer.md"
    rc, out, err = kit("reviewer-agent", "--session-root", str(sess), "--out", str(outf), cwd=root, script=nk)
    check("T32 --out 寫檔、內容是改好的定義", rc == 0 and outf.is_file()
          and "${CLAUDE_PROJECT_DIR}/sub/proj/.ai-review/kit/kit.py" in read(outf) and "重開 Claude Code" in out, out[-300:] + err[-300:])
    write(outf, "MARK\n")
    rc, out, err = kit("reviewer-agent", "--session-root", str(sess), "--out", str(outf), cwd=root, script=nk)
    check("T32 --out 已存在、沒帶 --force → 不覆寫（exit 1）", rc == 1 and read(outf) == "MARK\n" and "--force" in err, out[-300:] + err[-300:])
    rc, out, err = kit("reviewer-agent", "--session-root", str(sess), "--out", str(outf), "--force", cwd=root, script=nk)
    check("T32 --force 才覆寫", rc == 0 and "sub/proj/.ai-review/kit/kit.py" in read(outf), out[-300:] + err[-300:])
    # 專案沒裝 agent 檔 → 讀套件來源的 claude/agents/independent-reviewer.md
    src32 = root / "kit-src-t32"
    shutil.copytree(KIT_ROOT, src32, ignore=shutil.ignore_patterns(".git", "__pycache__", "dist", "tests"))
    nested2 = sess / "other" / "proj2"
    (nested2 / ".ai-review").mkdir(parents=True)
    rc, out, err = kit("reviewer-agent", "--session-root", str(sess), "--target", str(nested2), cwd=root, script=src32 / "tools/kit.py")
    check("T32 專案沒有 agent 檔 → 改讀套件來源的定義", rc == 0 and "${CLAUDE_PROJECT_DIR}/other/proj2/.ai-review/kit/kit.py" in out,
          out[-300:] + err[-300:])
    # 定義被改壞：沒有 hook 路徑 → reviewer-agent 拒絕；沒有 omitClaudeMd → doctor 列 ✗
    agent_p = nested / ".claude/agents/independent-reviewer.md"
    write(agent_p, agent_installed.replace("omitClaudeMd: true", "omitClaudeMd: false"))
    rc, out, err = kit("doctor", "--json", "--codex", str(root / "no-such-codex.exe"), cwd=nested, script=nk)
    ca = next((i for i in (json.loads(out) if rc == 0 else {}).get("items", []) if i["key"] == "claude_agent"), {})
    check("T32 doctor：agent 檔缺 omitClaudeMd: true → claude_agent ✗ 並說怎麼補", ca.get("ok") is False
          and "omitClaudeMd" in ca.get("detail", "") and "take-source" in ca.get("detail", ""), json.dumps(ca, ensure_ascii=False))
    write(agent_p, "---\nname: independent-reviewer\n---\nno hook here\n")
    rc, out, err = kit("reviewer-agent", "--session-root", str(sess), cwd=root, script=nk)
    check("T32 agent 檔裡沒有 hook 路徑 → 拒絕（exit 1）", rc == 1 and "找不到 hook 路徑" in err, out[-300:] + err[-300:])
    rc, out, err = kit("doctor", "--json", "--codex", str(root / "no-such-codex.exe"), cwd=nested, script=nk)
    ca = next((i for i in (json.loads(out) if rc == 0 else {}).get("items", []) if i["key"] == "claude_agent"), {})
    check("T32 doctor：agent 檔缺 review-guard → ✗", ca.get("ok") is False and "review-guard" in ca.get("detail", ""),
          json.dumps(ca, ensure_ascii=False))

    # ---------------- T33 修正輪（T-0199 W4）：RV-1～RV-11、V2-A～C 的重現改寫成測試
    # 子代理定義：守門自檢、onFailure、路徑寫法、Write 只建新檔（RV-1 c／d、RV-7、V2-C、RV-10）
    agent_src = read(KIT_ROOT / "claude/agents/independent-reviewer.md")
    check("T33 agent 檔：守門 hook 加 onFailure: block（RV-1 d）", re.search(r"^\s+onFailure: block\s*$", agent_src, re.M) is not None,
          agent_src[:600])
    check("T33 agent 檔：第 0 步守門自檢 echo guard-canary，沒被擋就回報「守門未生效，停止審查」、不寫 R（RV-1 c）",
          "echo guard-canary" in agent_src and "守門未生效，停止審查" in agent_src and "不寫 R" in agent_src, "")
    check("T33 agent 檔：路徑一律用雙引號或正斜線、Write 只建新檔（RV-7／V2-C／RV-2）",
          "路徑一律用雙引號或正斜線" in agent_src and "Write 只能建新檔" in agent_src, "")
    check("T33 review-ready skill：路徑一律用雙引號或正斜線（V2-C）", "路徑一律用雙引號或正斜線" in skill_rr, "")
    # reviewer-agent --python：沒有 py 的電腦（RV-1／RV-8）
    rc, out, err = kit("reviewer-agent", "--session-root", str(p26), "--python", "python3", cwd=root, script=p26kit)
    outp = out.replace("\r\n", "\n")
    check("T33 reviewer-agent --python python3：command 換成 python3、args 拿掉 -3、其他不變",
          rc == 0 and re.search(r"^\s+command: python3$", outp, re.M) is not None and '"-3"' not in outp
          and 'args: ["${CLAUDE_PROJECT_DIR}/.ai-review/kit/kit.py", "hook", "review-guard"]' in outp
          and outp.replace("command: python3", "command: py").replace('args: ["${', 'args: ["-3", "${')
          == read(p26 / ".claude/agents/independent-reviewer.md").replace("\r\n", "\n"), out[:400] + err[-300:])
    rc, out, err = kit("reviewer-agent", "--session-root", str(p26), "--python", "a b", cwd=root, script=p26kit)
    check("T33 reviewer-agent --python 含空白 → 拒絕（exit 2）", rc == 2 and out.strip() == "", err[-300:])

    p27 = new_git_project(root, "p27-fix-round")
    kit("install", "--target", str(p27))
    p27kit = p27 / ".ai-review/kit/kit.py"
    write(p27 / ".ai-review/config.md", read(p26 / ".ai-review/config.md"))
    cache27 = p27 / ".ai-review/.cache"

    def st27():
        rc, out, err = kit("state", "--json", "--no-write", cwd=p27, script=p27kit)
        return json.loads(out) if rc == 0 else {}

    # RV-6：state.json 原本不存在時，--end 不把自己寫的 state.json 報成「審查期間多了 1 項」
    os.replace(p27 / ".ai-review/state.json", p27 / ".ai-review/state.json.t33-moved")
    HA, snA = new_handoff(p27, p27kit, "t33a")
    rc, out, err = kit("claude-review", "--begin", HA, cwd=p27, script=p27kit)
    check("T33 前置：--begin exit 0", rc == 0, out[-300:])
    review_file(p27, "R-20990104-0001", HA, snA["target"])
    # RV-1／V2-A：守門心跳 0 筆（守門沒執行）→ 顯眼警告、照收、.done 記 guard_calls 0、isolation 標 guard-not-observed、exit 0
    rc, out, err = kit("claude-review", "--end", HA, "--model", "fable", cwd=p27, script=p27kit)
    djA = json.loads(read(cache27 / f"claude-{HA}.done")) if (cache27 / f"claude-{HA}.done").exists() else {}
    check("T33 RV-6 前：state.json 原本不存在，--end 不再警告「多了 .ai-review/state.json」",
          rc == 0 and "state.json" not in out and "new_ignored_entries" not in djA, out[-600:] + json.dumps(djA, ensure_ascii=False)[:300])
    check("T33 RV-1：守門心跳 0 筆 → 顯眼警告（未信任資料夾、找不到 py、沒有守門保護）、exit 仍 0",
          rc == 0 and "守門 hook 沒有執行紀錄" in out and "信任" in out and "py" in out and "沒有守門保護" in out
          and "doctor" in out, out[-900:])
    check("T33 RV-1：.done 記 guard_calls 0、isolation＝subagent;omitClaudeMd;no-memory;guard-not-observed",
          djA.get("guard_calls") == 0 and djA.get("isolation") == "subagent;omitClaudeMd;no-memory;guard-not-observed",
          json.dumps(djA, ensure_ascii=False)[:400])
    check("T33 RV-1：--end 與 state 的結論標「（非 Codex 審查；守門未生效）」",
          "no-blocking-found（非 Codex 審查；守門未生效）" in out, out[-500:])
    rc, out, err = kit("status", cwd=p27, script=p27kit)
    check("T33 RV-1：status 也標「守門未生效」", rc == 0 and "（非 Codex 審查；守門未生效）" in out, out[-400:])
    rc, out, err = kit("hook", "session-start", cwd=p27, script=p27kit, input_text=b"{}")
    check("T33 RV-1：SessionStart 也標「守門未生效」", rc == 0 and "（非 Codex 審查；守門未生效）" in out, out[-400:])
    check("T33 RV-1：state.json 的 review.guard_observed＝false", (st27().get("review") or {}).get("guard_observed") is False,
          json.dumps(st27().get("review"), ensure_ascii=False))
    # RV-3：--begin --again 後審查員沒寫新報告 → --end exit 1「這次沒有新的審查報告」，不把舊 R 當這次的結果
    rc, out, err = kit("claude-review", "--begin", HA, "--again", cwd=p27, script=p27kit)
    rc, out, err = kit("claude-review", "--end", HA, "--model", "fable", cwd=p27, script=p27kit)
    check("T33 RV-3：沒有新 R → exit 1「這次沒有新的審查報告」、不寫 .done、開始紀錄留著",
          rc == 1 and "這次沒有新的審查報告" in out and "隔離 Claude 審查結束" not in out
          and not (cache27 / f"claude-{HA}.done").exists() and (cache27 / f"claude-{HA}.running").exists(), out[-600:])
    # RV-2：審查期間舊 R 被改 → --end 警告並 exit 1；.done 記 review_integrity
    write(p27 / ".ai-review/reviews/R-20990104-0001.md",
          read(p27 / ".ai-review/reviews/R-20990104-0001.md").replace("no-blocking-found", "needs-fix"))
    review_file(p27, "R-20990104-0002", HA, snA["target"])
    rc, out, err = kit("claude-review", "--end", HA, "--model", "fable", cwd=p27, script=p27kit)
    djA2 = json.loads(read(cache27 / f"claude-{HA}.done")) if (cache27 / f"claude-{HA}.done").exists() else {}
    check("T33 RV-2：審查開始前就有的 R 被改 → 警告「被改或被刪」並 exit 1，.done 記 review_integrity",
          rc == 1 and "被改或被刪" in out and "改：R-20990104-0001.md" in out
          and (djA2.get("review_integrity") or {}).get("modified") == ["R-20990104-0001.md"], out[-700:] + json.dumps(djA2)[:300])
    # RV-2：審查期間新寫的 R 自稱 codex → exit 1；gate --require-reviewer codex 也不放行（沒有 codex-review 紀錄）
    HB, snB = new_handoff(p27, p27kit, "t33b")
    kit("claude-review", "--begin", HB, cwd=p27, script=p27kit)
    rc, out, err = guard_call(p27kit, {"tool_name": "Write", "tool_input": {
        "file_path": str(p27.resolve() / ".ai-review/reviews/R-20990104-0003.md"), "content": "x"}, "cwd": str(p27)})
    check("T33 前置：隔離 Claude 審查員 Write 新的 R-0003 → 守門放行並在心跳記檔名",
          rc == 0 and '"file": "R-20990104-0003.md"' in read(cache27 / f"claude-{HB}.guard.jsonl"), err[-300:])
    review_file(p27, "R-20990104-0003", HB, snB["target"], reviewer="codex", model=None)
    review_file(p27, "R-20990104-0004", HB, snB["target"])
    rc, out, err = kit("claude-review", "--end", HB, "--model", "fable", cwd=p27, script=p27kit)
    check("T33 RV-2：審查期間新寫的 R 自稱 reviewer codex → 點名並 exit 1",
          rc == 1 and "R-20990104-0003.md（reviewer codex）" in out, out[-600:])
    os.replace(p27 / ".ai-review/reviews/R-20990104-0004.md", p27 / ".ai-review/R-20990104-0004.md.t33-moved")
    rc, out, err = kit("gate", "--require-reviewer", "codex", cwd=p27, script=p27kit)
    check("T33 RV-2：隔離 Claude 審查員寫的 reviewer: codex 報告（在守門寫檔紀錄裡）過不了 gate --require-reviewer codex",
          rc == 1 and "冒充 Codex" in out and "guard.jsonl" in out, out[-500:])
    # RV-4：Codex 失敗（沒寫報告），最新的 R 是隔離 Claude 的 → codex-review 不把它報成 Codex 的結果
    HC, snC = new_handoff(p27, p27kit, "t33c")
    kit("claude-review", "--begin", HC, cwd=p27, script=p27kit)
    guard_call(p27kit, {"tool_name": "Bash", "tool_input": {"command": "echo guard-canary"}, "cwd": str(p27)})
    review_file(p27, "R-20990104-0005", HC, snC["target"])
    rc, out, err = kit("claude-review", "--end", HC, "--model", "fable", cwd=p27, script=p27kit)
    check("T33 前置：隔離 Claude 審查 R-0005 收尾 exit 0（有心跳，不標守門未生效）",
          rc == 0 and "no-blocking-found（非 Codex 審查）" in out and "守門未生效" not in out, out[-500:])
    rc, out, err = sh([PY, str(p27kit), "codex-review", "--again", "--codex", str(fake)], cwd=p27,
                      env=dict(ENV, FAKE_CODEX_MODE="noreport"))
    dC = json.loads(read(cache27 / f"codex-{HC}.done")) if (cache27 / f"codex-{HC}.done").exists() else {}
    check("T33 RV-4：Codex 沒寫報告 → 不收隔離 Claude 的 R、走「沒有找到對應交接的審查報告」exit 1、.done review 空",
          rc == 1 and "沒有找到對應交接" in out and "審查報告：R-20990104-0005" not in out and dC.get("review") is None,
          out[-600:] + json.dumps(dC)[:300])
    # RV-5：Codex 判 needs-fix 後，較弱的隔離 Claude 判 no-blocking-found 不能推翻
    # 報告編號照時間排序：Claude R-0005（0104）→ Codex（0105）→ Claude（0106）→ Codex（0107）
    rc, out, err = sh([PY, str(p27kit), "codex-review", "--again", "--codex", str(fake)], cwd=p27,
                      env=dict(ENV, FAKE_CODEX_MODE="needsfix", FAKE_CODEX_RID="R-20990105-0001"))
    dC = json.loads(read(cache27 / f"codex-{HC}.done")) if (cache27 / f"codex-{HC}.done").exists() else {}
    rid_codex = dC.get("review") or "R-missing"
    check("T33 RV-4／5 前置：Codex 寫新報告 needs-fix → codex-review 收這份（reviewer codex）",
          rc == 0 and dC.get("verdict") == "needs-fix" and rid_codex == "R-20990105-0001", out[-500:] + json.dumps(dC)[:300])
    kit("claude-review", "--begin", HC, "--again", cwd=p27, script=p27kit)
    guard_call(p27kit, {"tool_name": "Bash", "tool_input": {"command": "echo guard-canary"}, "cwd": str(p27)})
    review_file(p27, "R-20990106-0001", HC, snC["target"])
    rc, out, err = kit("claude-review", "--end", HC, "--model", "fable", cwd=p27, script=p27kit)
    s = st27()
    check("T33 RV-5：Codex needs-fix 之後的隔離 Claude no-blocking-found 不取代 → 狀態維持 needs-fix、註明理由",
          s.get("status") == "needs-fix" and (s.get("review") or {}).get("id") == rid_codex
          and any(f"此交接曾被 {rid_codex}" in n and "較弱的審查員不能推翻" in n and "重審請用 Codex 或修正後重新交接" in n
                  for n in s.get("notes", [])), json.dumps(s, ensure_ascii=False)[:700])
    check("T33 RV-5：--end 提醒狀態採用的不是這份報告", f"狀態採用的是 {rid_codex}" in out, out[-500:])
    rc, out, err = kit("gate", cwd=p27, script=p27kit)
    check("T33 RV-5：gate exit 1，並印審查歷程（Claude 的那份標未採用）",
          rc == 1 and f"審查歷程（交接 {HC}）" in out and "R-20990106-0001 claude-isolated no-blocking-found（未採用" in out
          and f"{rid_codex} codex needs-fix（採用）" in out, out[-700:])
    # 同種審查員重審：Codex → Codex 後者為準；Codex 可以取代 Claude
    rc, out, err = sh([PY, str(p27kit), "codex-review", "--again", "--codex", str(fake)], cwd=p27,
                      env=dict(ENV, FAKE_CODEX_RID="R-20990107-0001"))
    s = st27()
    check("T33 RV-5：Codex 重審（Codex → Codex）後者為準 → no-blocking-found",
          rc == 0 and s.get("status") == "no-blocking-found" and (s.get("review") or {}).get("reviewer") == "codex",
          out[-400:] + json.dumps(s, ensure_ascii=False)[:400])
    HD, snD = new_handoff(p27, p27kit, "t33d")
    review_file(p27, "R-20990104-0007", HD, snD["target"], verdict="needs-fix")
    review_file(p27, "R-20990104-0008", HD, snD["target"])
    check("T33 RV-5：Claude → Claude 照舊後者為準（no-blocking-found）", st27().get("status") == "no-blocking-found",
          json.dumps(st27(), ensure_ascii=False)[:400])
    review_file(p27, "R-20990104-0009", HD, snD["target"], verdict="needs-fix")
    review_file(p27, "R-20990104-0010", HD, snD["target"], reviewer="codex", model=None)
    check("T33 RV-5：Claude needs-fix 之後的 Codex no-blocking-found 可以取代", st27().get("status") == "no-blocking-found"
          and (st27().get("review") or {}).get("id") == "R-20990104-0010", json.dumps(st27(), ensure_ascii=False)[:400])
    check("T33 所有情境都沒刪任何報告",
          all((p27 / ".ai-review/reviews" / f"R-20990104-{n:04d}.md").is_file() for n in (1, 2, 3, 5, 7, 8, 9, 10))
          and all((p27 / ".ai-review/reviews" / f"{r}.md").is_file() for r in ("R-20990105-0001", "R-20990106-0001", "R-20990107-0001")))

    # ---------------- T34 修正輪（T-0204）：R-20261101-1302 的 -1、-3、-4、Q3
    # Q3：檢查命令的子程序補 PYTHONIOENCODING=utf-8（審查員環境主控台是 cp1252／cp950 時，印 ✓ 或 emoji 的測試不會崩）
    p34 = new_git_project(root, "p34-checks-encoding")
    kit("install", "--target", str(p34))
    p34kit = p34 / ".ai-review/kit/kit.py"
    write(p34 / "qcheck.py", 'print("\\u2713 ok \\U0001F600")\n')
    write(p34 / ".ai-review/config.md", read(KIT_ROOT / "templates/config.md").replace(
        "```checks\nname | command | required\n```",
        f"```checks\nname | command | required\nuni | \"{PY}\" qcheck.py | yes\n```"))
    env_noio = {k: v for k, v in ENV.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    rc, out, err = sh([PY, str(p34kit), "checks", "--run"], cwd=p34, env=env_noio)
    cj34 = json.loads(read(p34 / ".ai-review/.cache/checks-adhoc.json")) if (p34 / ".ai-review/.cache/checks-adhoc.json").exists() else {}
    r34 = (cj34.get("results") or [{}])[0]
    check("T34 Q3：子程序環境沒有 PYTHONIOENCODING／PYTHONUTF8 時，印 ✓ 與 emoji 的檢查命令經 checks --run 判 pass",
          rc == 0 and r34.get("result") == "pass" and "\u2713 ok \U0001F600" in (r34.get("tail") or ""),
          out[-400:] + err[-300:] + json.dumps(r34, ensure_ascii=False)[:400])
    check("T34 Q3：真的補了才印「檢查命令的子程序補了 PYTHONIOENCODING=utf-8」",
          "檢查命令的子程序補了 PYTHONIOENCODING=utf-8" in out, out[-400:])
    rc, out, err = sh([PY, str(p34kit), "checks", "--run"], cwd=p34, env=dict(env_noio, PYTHONIOENCODING="ascii:backslashreplace"))
    cj34 = json.loads(read(p34 / ".ai-review/.cache/checks-adhoc.json")) if (p34 / ".ai-review/.cache/checks-adhoc.json").exists() else {}
    r34 = (cj34.get("results") or [{}])[0]
    check("T34 Q3：已設 PYTHONIOENCODING 就照原值（ascii:backslashreplace → 輸出是跳脫字），不印「補了」",
          r34.get("result") == "pass" and "\\u2713 ok" in (r34.get("tail") or "") and "補了 PYTHONIOENCODING" not in out,
          out[-400:] + json.dumps(r34, ensure_ascii=False)[:400])
    # -3：一般 gate（不帶 --require-reviewer）也擋「守門沒生效」與「隔離 Claude 審查員寫的報告冒充別的審查者」
    cache34 = p34 / ".ai-review/.cache"
    HG1, snG1 = new_handoff(p34, p34kit, "t34-gate-a")
    kit("claude-review", "--begin", HG1, cwd=p34, script=p34kit)
    review_file(p34, "R-20990108-0001", HG1, snG1["target"])
    rc, out, err = kit("claude-review", "--end", HG1, "--model", "fable", cwd=p34, script=p34kit)
    dG1 = json.loads(read(cache34 / f"claude-{HG1}.done")) if (cache34 / f"claude-{HG1}.done").exists() else {}
    check("T34 -3 前置：守門心跳 0 筆的隔離 Claude 審查收尾（.done guard_calls 0）", rc == 0 and dG1.get("guard_calls") == 0,
          out[-400:] + json.dumps(dG1, ensure_ascii=False)[:300])
    rc, out, err = kit("gate", cwd=p34, script=p34kit)
    check("T34 -3：一般 gate、守門心跳 0 筆 → exit 1（不成立、說明守門沒生效與 --allow-no-guard）",
          rc == 1 and "守門心跳 0 筆" in out and "--allow-no-guard" in out and "通過條件成立" not in out, out[-600:])
    rc, out, err = kit("gate", "--allow-no-guard", cwd=p34, script=p34kit)
    check("T34 -3：gate --allow-no-guard → 放行（exit 0）並印提醒", rc == 0 and "通過條件成立" in out and "已帶 --allow-no-guard" in out,
          out[-600:])
    os.replace(cache34 / f"claude-{HG1}.done", cache34 / f"claude-{HG1}.done.t34-moved")
    rc, out, err = kit("gate", cwd=p34, script=p34kit)
    check("T34 -3：本機沒有 .done（換電腦、CI）→ 不擋（exit 0），印「本機沒有這份審查的收尾紀錄，守門有沒有生效無法核對」",
          rc == 0 and "通過條件成立" in out and "本機沒有這份審查的收尾紀錄，守門有沒有生效無法核對" in out, out[-600:])
    os.replace(cache34 / f"claude-{HG1}.done.t34-moved", cache34 / f"claude-{HG1}.done")
    HG2, snG2 = new_handoff(p34, p34kit, "t34-gate-b")
    kit("claude-review", "--begin", HG2, cwd=p34, script=p34kit)
    rc, out, err = guard_call(p34kit, {"tool_name": "Write", "tool_input": {
        "file_path": str(p34.resolve() / ".ai-review/reviews/R-20990108-0002.md"), "content": "x"}, "cwd": str(p34)})
    check("T34 -3 前置：隔離 Claude 審查員 Write R-0002 → 守門放行並在心跳記檔名",
          rc == 0 and '"file": "R-20990108-0002.md"' in read(cache34 / f"claude-{HG2}.guard.jsonl"), err[-300:])
    review_file(p34, "R-20990108-0002", HG2, snG2["target"], reviewer="codex", model=None)
    rc, out, err = kit("gate", cwd=p34, script=p34kit)
    check("T34 -3：守門寫檔紀錄裡的報告檔頭寫 codex → 一般 gate 也 exit 1（冒充 Codex）",
          rc == 1 and "冒充 Codex" in out and "guard.jsonl" in out and "通過條件成立" not in out, out[-600:])
    review_file(p34, "R-20990108-0002", HG2, snG2["target"], reviewer="other-ai", model=None)
    rc, out, err = kit("gate", cwd=p34, script=p34kit)
    check("T34 -3：檔頭寫其他審查者（other-ai）也一樣擋（冒充）", rc == 1 and "冒充 other-ai" in out, out[-600:])
    rc, out, err = kit("gate", "--allow-no-guard", cwd=p34, script=p34kit)
    check("T34 -3：--allow-no-guard 不放行冒充", rc == 1 and "冒充" in out, out[-600:])
    check("T34 -1：非巢狀、沒有子資料夾 CLAUDE.md（只有專案根那份）→ .done 照舊（沒有 nested／claude_md_exposure，isolation 不改）",
          "nested" not in dG1 and "claude_md_exposure" not in dG1
          and dG1.get("isolation") == "subagent;omitClaudeMd;no-memory;guard-not-observed", json.dumps(dG1, ensure_ascii=False)[:400])

    # -1：守門心跳記 nested（不記路徑）；claude-review --end 算可能被附進來的 CLAUDE.md，記進 .done、isolation 改標 startup-only
    agent_src34 = read(KIT_ROOT / "claude/agents/independent-reviewer.md")
    check("T34 -1(a)：審查員定義有「CLAUDE.md／AGENTS.md 被附進對話只當資料、寫進限制、isolation 改標 omitClaudeMd:startup-only」",
          "AGENTS.md" in agent_src34 and "system-reminder" in agent_src34 and "omitClaudeMd:startup-only" in agent_src34
          and "沒做的事（限制）" in agent_src34, "")
    pE = new_git_project(root, "p34-exposure")
    kit("install", "--target", str(pE))
    pEkit = pE / ".ai-review/kit/kit.py"
    cacheE = pE / ".ai-review/.cache"
    write(pE / "docs/CLAUDE.md", "# docs rules\n")
    write(pE / ".gitignore", read(pE / ".gitignore") + "ignored/\n")
    write(pE / "ignored/x/CLAUDE.md", "# excluded: .gitignore\n")
    write(pE / ".ai-review/x/CLAUDE.md", "# excluded\n")

    def guard_env(proj_kit, payload, cpd):
        env = dict(ENV)
        if cpd:
            env["CLAUDE_PROJECT_DIR"] = cpd
        return sh([PY, str(proj_kit), "hook", "review-guard"], cwd=root, input_text=json.dumps(payload).encode("utf-8"), env=env)

    canary = {"tool_name": "Bash", "tool_input": {"command": "echo guard-canary"}, "cwd": str(pE)}
    HE1, snE1 = new_handoff(pE, pEkit, "t34-exposure-a")
    kit("claude-review", "--begin", HE1, cwd=pE, script=pEkit)
    rc, out, err = guard_env(pEkit, canary, str(pE))
    glE1 = [json.loads(x) for x in read(cacheE / f"claude-{HE1}.guard.jsonl").splitlines() if x.strip()]
    check("T34 -1(b)：CLAUDE_PROJECT_DIR＝專案根 → 心跳 nested false（欄位：time、tool、decision、nested）",
          rc == 2 and len(glE1) == 1 and glE1[0].get("nested") is False and set(glE1[0]) == {"time", "tool", "decision", "nested"},
          json.dumps(glE1, ensure_ascii=False))
    review_file(pE, "R-20990109-0001", HE1, snE1["target"])
    rc, out, err = kit("claude-review", "--end", HE1, "--model", "fable", cwd=pE, script=pEkit)
    dE1 = json.loads(read(cacheE / f"claude-{HE1}.done")) if (cacheE / f"claude-{HE1}.done").exists() else {}
    check("T34 -1(b)：非巢狀、有子資料夾 CLAUDE.md → .done 記 nested false、claude_md_exposure 只有 docs/CLAUDE.md（不含專案根、"
          ".gitignore 排除的、.ai-review）、isolation 改標 omitClaudeMd:startup-only",
          rc == 0 and dE1.get("nested") is False and dE1.get("claude_md_exposure") == ["docs/CLAUDE.md"]
          and dE1.get("isolation") == "subagent;omitClaudeMd:startup-only;no-memory;review-guard",
          out[-400:] + json.dumps(dE1, ensure_ascii=False)[:500])
    check("T34 -1(b)：--end 畫面印一行白話提醒（列出檔名）", "提醒：審查員讀到這些資料夾的檔時" in out and "docs/CLAUDE.md" in out, out[-600:])
    HE2, snE2 = new_handoff(pE, pEkit, "t34-exposure-b")
    kit("claude-review", "--begin", HE2, cwd=pE, script=pEkit)
    guard_env(pEkit, canary, str(root))
    guard_env(pEkit, canary, None)
    glE2 = [json.loads(x) for x in read(cacheE / f"claude-{HE2}.guard.jsonl").splitlines() if x.strip()]
    check("T34 -1(b)：CLAUDE_PROJECT_DIR＝專案上層 → nested true；沒有這個環境變數 → nested false；心跳不記路徑",
          [g.get("nested") for g in glE2] == [True, False] and str(root) not in read(cacheE / f"claude-{HE2}.guard.jsonl")
          and "p34-exposure" not in read(cacheE / f"claude-{HE2}.guard.jsonl"), json.dumps(glE2, ensure_ascii=False))
    write(pE / ".ai-review/reviews/R-20990109-0002.md", front("R-20990109-0002", "review", handoff=HE2, target=snE2["target"],
                                                             reviewer="claude-isolated", verdict="no-blocking-found", blocking=0,
                                                             reviewer_model="fable",
                                                             reviewer_isolation="subagent;omitClaudeMd:startup-only;no-memory;review-guard"))
    rc, out, err = kit("claude-review", "--end", HE2, "--model", "fable", cwd=pE, script=pEkit)
    dE2 = json.loads(read(cacheE / f"claude-{HE2}.done")) if (cacheE / f"claude-{HE2}.done").exists() else {}
    check("T34 -1(b)：巢狀 → claude_md_exposure 加專案根的 CLAUDE.md、nested true；報告已寫 startup-only 不重複加",
          rc == 0 and dE2.get("nested") is True and dE2.get("claude_md_exposure") == ["CLAUDE.md", "docs/CLAUDE.md"]
          and dE2.get("isolation") == "subagent;omitClaudeMd:startup-only;no-memory;review-guard"
          and "專案根的 CLAUDE.md 也算" in out, out[-400:] + json.dumps(dE2, ensure_ascii=False)[:500])
    # 非 git 專案：照指紋的收檔規則（不進 EXCLUDE_DIRS），直接呼叫函式
    ng = root / "t34-nongit-exposure"
    for rp in ("CLAUDE.md", "sub/CLAUDE.md", "sub/deep/claude.md", "node_modules/x/CLAUDE.md", ".git/CLAUDE.md", ".ai-review/CLAUDE.md"):
        write(ng / rp, "x\n")
    probe = ("import json, sys; from pathlib import Path; sys.dont_write_bytecode = True; sys.path.insert(0, sys.argv[1]); import kit; "
             "print(json.dumps([kit.claude_md_exposure(Path(sys.argv[2]), n) for n in (False, True)]))")
    rc, out, err = sh([PY, "-c", probe, str(KIT_ROOT / "tools"), str(ng)], cwd=root)
    check("T34 -1(b)：非 git 專案 → 不進 node_modules／.git／.ai-review，檔名不分大小寫；巢狀才含專案根那份",
          rc == 0 and json.loads(out) == [["sub/CLAUDE.md", "sub/deep/claude.md"], ["CLAUDE.md", "sub/CLAUDE.md", "sub/deep/claude.md"]],
          out[-300:] + err[-300:])

    # -4：倉庫外（對話根）的審查員定義：doctor、update、claude-review --begin 往上找、比對，kit 不寫專案外的檔
    sess34 = root / "t34-session"
    n34 = new_git_project(sess34 / "sub", "proj34")
    kit("install", "--target", str(n34))
    n34kit = n34 / ".ai-review/kit/kit.py"
    n34agent = n34 / ".claude/agents/independent-reviewer.md"
    out34 = sess34 / ".claude/agents/independent-reviewer.md"
    hook_old, hook_new = b"${CLAUDE_PROJECT_DIR}/.ai-review/kit/kit.py", b"${CLAUDE_PROJECT_DIR}/sub/proj34/.ai-review/kit/kit.py"

    def ca34():
        rc, out, err = kit("doctor", "--json", "--codex", str(root / "no-such-codex.exe"), cwd=n34, script=n34kit)
        return next((i for i in (json.loads(out) if rc == 0 else {}).get("items", []) if i["key"] == "claude_agent"), {})

    c34 = ca34()
    check("T34 -4：祖先都沒有倉庫外定義 → doctor 不提", c34 and "倉庫外定義" not in c34.get("detail", ""), json.dumps(c34, ensure_ascii=False))
    cp = subprocess.run([PY, str(n34kit), "reviewer-agent", "--session-root", str(sess34)], capture_output=True, env=ENV, timeout=120)
    check("T34 -4：reviewer-agent 輸出（抽成函式後）與專案內定義只差 hook 路徑，逐位元相同（含換行）",
          cp.returncode == 0 and cp.stdout == n34agent.read_bytes().replace(hook_old, hook_new), cp.stderr.decode("utf-8", "replace")[-300:])
    cp = subprocess.run([PY, str(n34kit), "reviewer-agent", "--session-root", str(sess34), "--python", "python3"], capture_output=True,
                        env=ENV, timeout=120)
    agent_b = n34agent.read_bytes()
    nlb = b"\r\n" if b"\r\n" in agent_b else b"\n"
    check("T34 -4：reviewer-agent --python python3 在 CRLF／LF 定義檔都換得了，行尾照原檔",
          cp.returncode == 0 and (b"command: python3" + nlb) in cp.stdout and b'"-3"' not in cp.stdout
          and cp.stdout.count(b"\r\n") == (cp.stdout.count(b"\n") if nlb == b"\r\n" else 0), cp.stderr.decode("utf-8", "replace")[-300:])
    rc, out, err = kit("reviewer-agent", "--session-root", str(sess34), "--out", str(out34), cwd=root, script=n34kit)
    c34 = ca34()
    check("T34 -4：祖先有同步的倉庫外定義 → doctor 說明加「倉庫外定義同步」",
          rc == 0 and "倉庫外定義同步" in c34.get("detail", "") and "不同步" not in c34.get("detail", ""), json.dumps(c34, ensure_ascii=False))
    write(out34, read(out34) + "\n# 舊版留下的一行\n")
    c34 = ca34()
    d34 = c34.get("detail", "")
    check("T34 -4：祖先的倉庫外定義不同步 → doctor ✗，說明寫「與專案內版本不同步（套件更新後沒重產）」與修法指令＋重開 Claude Code",
          c34.get("ok") is False and "與專案內版本不同步（套件更新後沒重產）" in d34 and "reviewer-agent --target" in d34
          and f'--session-root "{sess34.resolve()}"' in d34 and f'--out "{out34.resolve()}" --force' in d34
          and "重開 Claude Code" in d34 and "--python" not in d34, d34)
    before34 = (out34.read_bytes(), out34.stat().st_mtime_ns)
    rc, out, err = kit("update", "--target", str(n34), cwd=n34, script=n34kit)
    check("T34 -4：kit update 不同步 → 印 ⚠️ 與同一條修法指令，倉庫外的檔沒被寫（內容與修改時間不變）",
          rc == 0 and "⚠️ 倉庫外定義" in out and "reviewer-agent --target" in out
          and (out34.read_bytes(), out34.stat().st_mtime_ns) == before34, out[-600:] + err[-300:])
    HN, snN = new_handoff(n34, n34kit, "t34-stale")
    rc, out, err = kit("claude-review", "--begin", HN, cwd=n34, script=n34kit)
    runN = json.loads(read(n34 / f".ai-review/.cache/claude-{HN}.running")) if (n34 / f".ai-review/.cache/claude-{HN}.running").exists() else {}
    check("T34 -4：claude-review --begin 不同步 → 印 ⚠️（不擋，exit 0）、.running 記 agent_stale: true",
          rc == 0 and "⚠️ 倉庫外定義" in out and runN.get("agent_stale") is True and (out34.read_bytes(), out34.stat().st_mtime_ns) == before34,
          out[-500:])
    review_file(n34, "R-20990110-0001", HN, snN["target"])
    rc, out, err = kit("claude-review", "--end", HN, "--model", "fable", cwd=n34, script=n34kit)
    dN = json.loads(read(n34 / f".ai-review/.cache/claude-{HN}.done")) if (n34 / f".ai-review/.cache/claude-{HN}.done").exists() else {}
    check("T34 -4：--end 把 agent_stale: true 帶進 .done", rc == 0 and dN.get("agent_stale") is True, out[-400:] + json.dumps(dN)[:300])
    rc, out, err = kit("reviewer-agent", "--session-root", str(sess34), "--python", "python3", "--out", str(out34), "--force",
                       cwd=root, script=n34kit)
    c34 = ca34()
    check("T34 -4：倉庫外定義用 python3 產生 → doctor 讀那份的 command 行比對，判同步", rc == 0 and "倉庫外定義同步" in c34.get("detail", ""),
          json.dumps(c34, ensure_ascii=False))
    write(out34, read(out34).replace("independent-reviewer", "independent-reviewer-old", 1))
    c34 = ca34()
    check("T34 -4：python3 版不同步 → 修法指令帶 --python python3", c34.get("ok") is False and "--python python3" in c34.get("detail", ""),
          json.dumps(c34, ensure_ascii=False))
    rc, out, err = kit("reviewer-agent", "--session-root", str(sess34), "--out", str(out34), "--force", cwd=root, script=n34kit)
    HN2, snN2 = new_handoff(n34, n34kit, "t34-synced")
    rc, out, err = kit("claude-review", "--begin", HN2, cwd=n34, script=n34kit)
    runN2 = json.loads(read(n34 / f".ai-review/.cache/claude-{HN2}.running")) if (n34 / f".ai-review/.cache/claude-{HN2}.running").exists() else {}
    check("T34 -4：同步時 --begin 不印 ⚠️、.running 沒有 agent_stale", rc == 0 and "倉庫外定義" not in out and "agent_stale" not in runN2,
          out[-400:])

    # ---------------- 總結
    fails = [r for r in RESULTS if not r[1]]
    print(f"\n共 {len(RESULTS)} 項，通過 {len(RESULTS) - len(fails)}，失敗 {len(fails)}")
    if not a.keep and not a.dir:
        print(f"（測試資料夾保留在 {root}，依刪除先問原則不自動刪除）")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
