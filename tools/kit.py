#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ai-review-kit 工具（純 Python 標準函式庫，Python 3.9+）

兩種身分、同一支檔案：
  A. 放在套件來源 `ai-review-kit/tools/kit.py`  → 管理指令：install / update / restore / status / pack / check-update
  B. 被安裝到專案 `<專案>/.ai-review/kit/kit.py` → 專案指令：status / snapshot / checks / state / verify / gate / new-id / codex-review / ignore-check / doctor / hook / relink
     （B 也能跑 update，來源用 --source 指定，或用安裝紀錄裡記住的來源路徑）

設計要點
- 指紋（fingerprint）＝工作目錄內容的 git tree 雜湊，不含 .ai-review/；含未提交與未追蹤（非 ignore）檔案。
  非 git 專案退回檔案內容雜湊（能力較弱，會標明）。
- 狀態不是誰宣告的：由 handoffs/ reviews/ fixes/ 三種報告的檔頭 + 目前指紋推導（見 core/workflow.md 第 3 節）。
- 安裝／更新：管理區塊（CLAUDE.md、AGENTS.md）只動標記之間；hook 條目只動含 `.ai-review/kit/kit.py` 的那幾條；
  檔案用三方比對（安裝時雜湊／目前雜湊／新來源雜湊）判斷「使用者改過」與「衝突」，衝突不覆蓋。
- 任何修改前先備份到 .ai-review/.backup/<時間>/，restore 可逐次還原。
- 不連網（除了使用者明確下 check-update --url）、不上傳、不碰登入資訊與對話紀錄。
"""
import argparse
import difflib
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

KIT_NAME = "ai-review-kit"
HERE = Path(__file__).resolve().parent
HOOK_TAG = ".ai-review/kit/kit.py"          # 辨識「我們的」hook 條目
BLOCK_BEGIN_RE = re.compile(r"^<!-- ai-review-kit:begin[^\n]*-->[ \t]*\r?\n?", re.M)
BLOCK_END = "<!-- ai-review-kit:end -->"
BLOCK_END_RE = re.compile(r"^<!-- ai-review-kit:end -->[ \t]*\r?\n?", re.M)
GITIGNORE_LINES = ["# ai-review-kit（本機資料，不提交）", ".ai-review/.cache/", ".ai-review/.backup/", ".ai-review/local.json",
                   ".ai-review/state.json"]   # state.json＝本機推導的追蹤資料，進版控只會讓工作區一直顯示已修改（未發版）
LOCAL_KEYS = ("python", "python_args", "source")   # 每台電腦不同、可能含使用者名稱 → 存 local.json，不進版控
HOOK_KIT_PY = "${CLAUDE_PROJECT_DIR}/.ai-review/kit/kit.py"   # Claude Code 執行 hook 前會展開（2026-09-18 實測 exec 形式可用）
EXCLUDE_DIRS = {".git", ".ai-review", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
                "bin", "obj", ".mypy_cache", ".pytest_cache", ".tox", "target"}
STATUS_LABELS = {
    "not-ready": "尚未準備",
    "pending-review": "待獨立審查",
    "needs-fix": "需修正",
    "pending-recheck": "待複查",
    "no-blocking-found": "本次範圍內未發現阻擋問題",
}
SELF_REVIEWERS = {"", "self", "claude", "claude-code", "developer", "developer-ai", "dev", "author"}
DEFAULT_TIMEOUT = 600


# ---------------------------------------------------------------- 基本工具
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def now_id():
    return datetime.now().strftime("%Y%m%d-%H%M")


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    return sha256_bytes(Path(p).read_bytes())


def read_text(p):
    with io.open(p, "r", encoding="utf-8-sig", newline="") as f:   # newline="" 保留原始 CRLF/LF
        return f.read()


def write_text(p, s, newline=None):
    """照字面寫入（newline="" 關掉平台換行轉換，避免 CRLF 變成 CRCRLF）；內容的換行由呼叫端決定。"""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)


def detect_newline(s):
    return "\r\n" if "\r\n" in s else "\n"


def norm_nl(s):
    return s.replace("\r\n", "\n")


def load_json(p, default=None):
    try:
        return json.loads(read_text(p))
    except Exception:
        return default


def dump_json(p, obj):
    write_text(p, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def run(cmd, cwd=None, env=None, timeout=120, shell=False, input_text=None):
    try:
        cp = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, capture_output=True,
                            timeout=timeout, shell=shell, input=input_text)
        out = cp.stdout.decode("utf-8", "replace")
        err = cp.stderr.decode("utf-8", "replace")
        return cp.returncode, out, err
    except subprocess.TimeoutExpired as e:
        return -1, (e.stdout or b"").decode("utf-8", "replace"), "timeout"
    except FileNotFoundError as e:
        return 127, "", str(e)


def rel(p, root):
    return Path(p).resolve().relative_to(Path(root).resolve()).as_posix()


def short(fp):
    if not fp:
        return "-"
    return fp[:12]


# ---------------------------------------------------------------- 找根目錄
def source_root_from_here():
    if HERE.name == "tools" and (HERE.parent / "VERSION").exists() and (HERE.parent / "core").is_dir():
        return HERE.parent
    return None


def project_root_from_here():
    if HERE.name == "kit" and HERE.parent.name == ".ai-review":
        return HERE.parent.parent
    return None


def find_project_root(start=None):
    p = Path(start or os.getcwd()).resolve()
    for cand in [p] + list(p.parents):
        if (cand / ".ai-review").is_dir():
            return cand
    return None


def resolve_target(args):
    t = getattr(args, "target", None)
    if t:
        return Path(t).resolve()
    r = project_root_from_here()
    if r:
        return r
    r = find_project_root()
    if r:
        return r
    return Path(os.getcwd()).resolve()


def kit_version_of(root):
    """root 可以是套件來源或專案（讀 .ai-review/kit/VERSION）"""
    for cand in (Path(root) / "VERSION", Path(root) / ".ai-review" / "kit" / "VERSION"):
        if cand.exists():
            return read_text(cand).strip()
    return None


# ---------------------------------------------------------------- 來源（資料夾或 zip）
class Source:
    def __init__(self, path):
        self.given = Path(path)
        self._tmp = None
        if self.given.is_file() and self.given.suffix.lower() == ".zip":
            self._tmp = tempfile.mkdtemp(prefix="ai-review-kit-src-")
            with zipfile.ZipFile(self.given) as z:
                z.extractall(self._tmp)
            root = None
            for cand in [Path(self._tmp)] + [p for p in Path(self._tmp).rglob("VERSION")]:
                c = cand if cand.is_dir() else cand.parent
                if (c / "VERSION").exists() and (c / "core").is_dir():
                    root = c
                    break
            if not root:
                raise SystemExit(f"zip 裡找不到套件（要有 VERSION 與 core/）：{self.given}")
            self.root = root
        elif self.given.is_dir() and (self.given / "VERSION").exists() and (self.given / "core").is_dir():
            self.root = self.given.resolve()
        else:
            raise SystemExit(f"不是有效的套件來源（需要資料夾含 VERSION 與 core/，或 .zip）：{self.given}")
        self.version = read_text(self.root / "VERSION").strip()

    def cleanup(self):
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)


def resolve_source(args, manifest=None, required=True, local=None):
    s = getattr(args, "source", None)
    remembered = (local or {}).get("source") or (manifest or {}).get("source")
    if not s and remembered and Path(remembered).exists():
        s = remembered
    if not s:
        r = source_root_from_here()
        if r:
            s = r
    if not s:
        if required:
            raise SystemExit("找不到套件來源：請用 --source <ai-review-kit 資料夾或 .zip>")
        return None
    return Source(s)


# ---------------------------------------------------------------- 檔案對照表
def file_map(src_root):
    """(來源相對路徑, 專案相對路徑)"""
    m = []
    for p in sorted((src_root / "core").glob("*.md")):
        m.append((f"core/{p.name}", f".ai-review/kit/{p.name}"))
    m.append(("VERSION", ".ai-review/kit/VERSION"))
    m.append(("tools/kit.py", ".ai-review/kit/kit.py"))
    for p in sorted((src_root / "templates").glob("*.md")):
        m.append((f"templates/{p.name}", f".ai-review/kit/templates/{p.name}"))
    d = src_root / "docs" / "codex-start.md"
    if d.exists():
        m.append(("docs/codex-start.md", ".ai-review/kit/docs/codex-start.md"))
    for d in sorted((src_root / "claude" / "skills").iterdir()):
        if (d / "SKILL.md").exists():
            m.append((f"claude/skills/{d.name}/SKILL.md", f".claude/skills/{d.name}/SKILL.md"))
    for d in sorted((src_root / "codex" / "skills").iterdir()):
        if (d / "SKILL.md").exists():
            m.append((f"codex/skills/{d.name}/SKILL.md", f".agents/skills/{d.name}/SKILL.md"))
    return m


# ---------------------------------------------------------------- 安裝紀錄（manifest）
def manifest_path(target):
    return Path(target) / ".ai-review" / "kit-version.json"


def load_manifest(target):
    return load_json(manifest_path(target), None)


def local_path(target):
    return Path(target) / ".ai-review" / "local.json"


def load_local(target, manifest=None):
    """本機設定（直譯器、來源路徑）。0.1.0 存在 manifest 裡，讀得到就沿用當作舊值。"""
    loc = load_json(local_path(target), None)
    if isinstance(loc, dict):
        return loc
    return {k: manifest[k] for k in LOCAL_KEYS if manifest and k in manifest}


def save_local(target, manifest, python, python_args, source):
    dump_json(local_path(target), {"python": python, "python_args": list(python_args),
                                   "source": str(source) if source else None,
                                   "_note": "本機設定，不進版控（每台電腦不同）。換電腦後跑 relink 重建。"})
    for k in LOCAL_KEYS:
        manifest.pop(k, None)


def new_manifest(version):
    return {
        "kit": KIT_NAME,
        "kit_version": version,
        "installed_at": now_str(),
        "updated_at": now_str(),
        "files": {},
        "blocks": {},
        "runs": [],
        "_note": "安裝紀錄。files 是安裝時寫入的雜湊，用來判斷使用者是否改過；不是安全證明。",
    }


# ---------------------------------------------------------------- 管理區塊
def block_text(version, body):
    body = norm_nl(body).strip("\n")
    return f"<!-- ai-review-kit:begin v{version} （此區塊由安裝工具維護；要改請改區塊外或改套件範本） -->\n{body}\n{BLOCK_END}\n"


def extract_block(text):
    """回傳 (區塊起, 區塊迄, 區塊本文) 或 None"""
    t = text
    m1 = BLOCK_BEGIN_RE.search(t)
    if not m1:
        return None
    m2 = BLOCK_END_RE.search(t, m1.end())
    if not m2:
        return None
    body = t[m1.end():m2.start()]
    mv = re.search(r"begin v(\S+)", m1.group(0))
    return (m1.start(), m2.end(), norm_nl(body).strip("\n"), mv.group(1) if mv else None)


def apply_block(text, version, body):
    """text 可為 None（檔案不存在）。回傳新內容。"""
    blk = block_text(version, body)
    if text is None:
        return blk
    nl = detect_newline(text)
    t = norm_nl(text)
    ex = extract_block(t)
    if ex:
        s, e, _, _ = ex
        t = t[:s] + blk + t[e:]
    else:
        if t and not t.endswith("\n"):
            t += "\n"
        if t.strip():
            t += "\n"
        t += blk
    return t.replace("\n", nl) if nl != "\n" else t


# ---------------------------------------------------------------- hooks（Claude Code / Codex）
def is_our_hook_group(group):
    for h in group.get("hooks", []) or []:
        s = str(h.get("command", "")) + " " + " ".join(str(a) for a in (h.get("args") or []))
        if HOOK_TAG in s.replace("\\", "/"):
            return True
    return False


def claude_hook_groups(python, python_args, kit_py=HOOK_KIT_PY):
    def entry(event, msg):
        return {"matcher": "", "hooks": [{
            "type": "command",
            "command": python,
            "args": list(python_args) + [kit_py, "hook", event],
            "timeout": 20,
            "statusMessage": msg,
        }]}
    return {
        "SessionStart": [entry("session-start", "ai-review-kit：讀取流程狀態…")],
        "Stop": [entry("stop", "ai-review-kit：檢查交接是否過期…")],
    }


def codex_hook_groups(python, python_args, kit_py_rel=".ai-review/kit/kit.py"):
    posix = " ".join(shlex.quote(x) for x in (["python3"] + [kit_py_rel, "hook", "session-start", "--agent", "codex"]))
    win_parts = [python] + list(python_args) + [kit_py_rel, "hook", "session-start", "--agent", "codex"]
    win = "& " + " ".join('"' + x.replace('"', '`"') + '"' for x in win_parts)
    return {"SessionStart": [{"matcher": "", "hooks": [{
        "type": "command", "command": posix, "commandWindows": win, "timeout": 20,
        "statusMessage": "ai-review-kit：讀取流程狀態…",
    }]}]}


def merge_hooks(settings, ours):
    """settings: dict（整份設定），ours: {event: [group,...]}。移除舊的我們的條目、加入新的；其他條目原樣保留。"""
    settings = settings if isinstance(settings, dict) else {}
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    for event, groups in ours.items():
        cur = hooks.get(event)
        if not isinstance(cur, list):
            cur = []
        kept = [g for g in cur if not (isinstance(g, dict) and is_our_hook_group(g))]
        hooks[event] = kept + groups
    settings["hooks"] = hooks
    return settings


def strip_our_hooks(settings):
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    if not isinstance(hooks, dict):
        return settings
    for event in list(hooks.keys()):
        cur = hooks.get(event)
        if isinstance(cur, list):
            kept = [g for g in cur if not (isinstance(g, dict) and is_our_hook_group(g))]
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
    if not hooks:
        settings.pop("hooks", None)
    return settings


def portable_python():
    """寫進 hook 的預設直譯器：用 PATH 上的通用命令，不寫本機絕對路徑（會進版控、可能含使用者名稱）。"""
    if os.name == "nt":
        if shutil.which("py"):
            return "py", ["-3"]
    elif shutil.which("python3"):
        return "python3", []
    return sys.executable, []


def resolve_python(args):
    spec = getattr(args, "python", None)
    if spec:
        parts = shlex.split(spec, posix=(os.name != "nt"))
        return parts[0], parts[1:]
    return portable_python()


def warn_if_personal_path(python):
    try:
        home = Path.home().resolve()
        pp = Path(python)
        if pp.is_absolute() and (pp.resolve() == home or home in pp.resolve().parents):
            print(f"⚠ 直譯器路徑在使用者資料夾內（{python}），會寫進 .claude/settings.json 並進版控，路徑含使用者名稱。"
                  f"建議改用 --python \"py -3\"（Windows）或 --python python3。")
    except (ValueError, OSError, RuntimeError):
        pass


# ---------------------------------------------------------------- 計畫（三方比對）
def plan(src, target, manifest, take):
    """回傳 actions 清單。take: set of rel paths（或 '*'）強制採用來源版。"""
    actions = []
    rec_files = (manifest or {}).get("files", {})
    for src_rel, dst_rel in file_map(src.root):
        sp = src.root / src_rel
        dp = target / dst_rel
        src_hash = sha256_file(sp)
        cur_hash = sha256_file(dp) if dp.exists() else None
        rec = rec_files.get(dst_rel)
        forced = ("*" in take) or (dst_rel in take)
        if cur_hash is None:
            act = "add"
        elif cur_hash == src_hash:
            act = "unchanged"
        elif rec is None:
            act = "conflict-existing"      # 專案原本就有同名檔，不是我們裝的
        elif cur_hash == rec:
            act = "update"                 # 使用者沒動、來源有新版
        elif src_hash == rec:
            act = "keep-user"              # 使用者改過、來源沒變
        else:
            act = "conflict"               # 兩邊都改
        if forced and act in ("conflict", "conflict-existing", "keep-user"):
            act = "update(forced)"
        actions.append({"kind": "file", "rel": dst_rel, "action": act, "src": sp, "src_hash": src_hash,
                        "cur_hash": cur_hash, "rec_hash": rec})
    # 管理區塊
    rec_blocks = (manifest or {}).get("blocks", {})
    for name, tmpl in (("CLAUDE.md", "templates/entry-claude.md"), ("AGENTS.md", "templates/entry-agents.md")):
        body = norm_nl(read_text(src.root / tmpl)).strip("\n")
        new_hash = sha256_bytes(body.encode("utf-8"))
        fp = target / name
        cur_text = read_text(fp) if fp.exists() else None
        ex = extract_block(norm_nl(cur_text)) if cur_text is not None else None
        rec = rec_blocks.get(name)
        forced = ("*" in take) or (name in take)
        if cur_text is None:
            act = "create-with-block"
        elif ex is None:
            act = "append-block"
        else:
            cur_hash = sha256_bytes(ex[2].encode("utf-8"))
            if cur_hash == new_hash:
                act = "unchanged" if ex[3] == src.version else "update-block"   # 本文相同只換版本標記
            elif rec is None or cur_hash == rec:
                act = "update-block"
            elif new_hash == rec:
                act = "keep-user"
            else:
                act = "conflict"
        if forced and act in ("conflict", "keep-user"):
            act = "update-block(forced)"
        actions.append({"kind": "block", "rel": name, "action": act, "body": body, "new_hash": new_hash})
    return actions


def plan_config(target, python, python_args):
    """套件檔以外、安裝時會一併寫入的設定與紀錄檔。預覽要完整列出（hook 與設定檔屬於要先徵得同意的變更）。
    回傳 actions（kind="config" 附 text 供寫入；kind="record" 由 manifest／local／state 流程自己寫，只列不寫）。"""
    actions = []

    def cfg(rel_path, text):
        p = target / rel_path
        if not p.exists():
            act = "create"
        elif norm_nl(read_text(p)).strip() == norm_nl(text).strip():
            act = "unchanged"
        else:
            act = "modify"
        actions.append({"kind": "config", "rel": rel_path, "action": act, "text": text})

    # hooks：Claude Code 與 Codex（選用）
    for rel_path, groups in ((".claude/settings.json", claude_hook_groups(python, python_args)),
                             (".codex/hooks.json", codex_hook_groups(python, python_args))):
        p = target / rel_path
        cur = load_json(p, None) if p.exists() else None
        if p.exists() and cur is None:
            actions.append({"kind": "config", "rel": rel_path, "action": "skip(非有效 JSON)", "text": None})
            continue
        merged = merge_hooks(dict(cur or {}), groups)
        cfg(rel_path, json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    # .gitignore
    gi = target / ".gitignore"
    gi_txt = read_text(gi) if gi.exists() else ""
    missing = [l for l in GITIGNORE_LINES[1:] if l not in norm_nl(gi_txt).splitlines()]
    if missing:
        nl = detect_newline(gi_txt) if gi_txt else "\n"
        t = norm_nl(gi_txt)
        if t and not t.endswith("\n"):
            t += "\n"
        tail = [l for l in t.splitlines() if l.strip()][-1:]
        if tail and tail[0] in GITIGNORE_LINES:   # 檔尾就是我們的區段 → 接在後面，不重複標題
            t += "\n".join(missing) + "\n"
        else:
            if t.strip():
                t += "\n"
            t += "\n".join([GITIGNORE_LINES[0]] + missing) + "\n"
        actions.append({"kind": "config", "rel": ".gitignore", "action": "modify" if gi.exists() else "create",
                        "text": t.replace("\n", nl) if nl != "\n" else t})
    # 資料夾與佔位
    for d in ("handoffs", "reviews", "fixes"):
        keep = f".ai-review/{d}/.gitkeep"
        if not (target / keep).exists():
            actions.append({"kind": "config", "rel": keep, "action": "create", "text": ""})
    # 紀錄檔（每次都會寫）
    for rel_path in (".ai-review/kit-version.json", ".ai-review/local.json", ".ai-review/state.json"):
        actions.append({"kind": "record", "rel": rel_path,
                        "action": "modify" if (target / rel_path).exists() else "create"})
    return actions


def print_plan(actions, target, show_diff=False, config=None):
    print(f"目標專案：{target}")
    print("| 項目 | 動作 |")
    print("|---|---|")
    for a in actions:
        print(f"| {a['rel']} | {a['action']} |")
    if config:
        print("\n設定與紀錄檔（hook 會讓 Claude Code／Codex 開工時自動執行 kit.py，請確認後再安裝）：")
        print("| 項目 | 動作 |")
        print("|---|---|")
        for a in config:
            print(f"| {a['rel']} | {a['action']} |")
    if show_diff:
        for a in actions:
            if a["kind"] == "file" and a["action"] in ("update", "conflict", "keep-user", "update(forced)"):
                cur = norm_nl(read_text(target / a["rel"])).splitlines()
                new = norm_nl(read_text(a["src"])).splitlines()
                diff = list(difflib.unified_diff(cur, new, f"專案/{a['rel']}", f"來源/{a['rel']}", lineterm="", n=2))
                print(f"\n--- 差異：{a['rel']}（{a['action']}）---")
                print("\n".join(diff[:200]))
                if len(diff) > 200:
                    print(f"… 共 {len(diff)} 行，只顯示前 200 行")
        for a in config or []:
            if a["kind"] == "config" and a["action"] in ("create", "modify") and a["rel"].endswith(".json"):
                p = target / a["rel"]
                cur = norm_nl(read_text(p)).splitlines() if p.exists() else []
                diff = list(difflib.unified_diff(cur, norm_nl(a["text"]).splitlines(),
                                                 f"專案/{a['rel']}", f"安裝後/{a['rel']}", lineterm="", n=2))
                print(f"\n--- 差異：{a['rel']}（{a['action']}）---")
                print("\n".join(diff[:200]))


# ---------------------------------------------------------------- 執行安裝／更新
class Run:
    def __init__(self, target):
        self.target = Path(target)
        self.ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.backup_dir = self.target / ".ai-review" / ".backup" / self.ts
        self.created = []
        self.backed_up = []

    def backup(self, rel_path):
        p = self.target / rel_path
        if p.exists() and rel_path not in self.backed_up:
            dst = self.backup_dir / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            self.backed_up.append(rel_path)

    def write(self, rel_path, data_bytes=None, text=None, newline=None):
        p = self.target / rel_path
        existed = p.exists()
        if existed:
            self.backup(rel_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if data_bytes is not None:
            p.write_bytes(data_bytes)
        else:
            write_text(p, text, newline=newline)
        if not existed and rel_path not in self.created:
            self.created.append(rel_path)

    def record(self):
        return {"ts": self.ts, "backup_dir": rel(self.backup_dir, self.target) if self.backup_dir.exists() else None,
                "created": self.created, "backed_up": self.backed_up}


def do_install_or_update(args, mode):
    target = resolve_target(args)
    manifest = load_manifest(target)
    if mode == "install" and manifest:
        print(f"[提示] 專案已安裝 {manifest.get('kit_version')}，改以 update 流程處理（重複執行不會重複插入）。")
        mode = "update"
    if mode == "update" and not manifest:
        print("[提示] 專案尚未安裝，改以 install 流程處理。")
        mode = "install"
    local = load_local(target, manifest)
    src = resolve_source(args, manifest, local=local)
    take = set(getattr(args, "take_source", None) or [])
    preview = bool(getattr(args, "preview", False) or getattr(args, "dry_run", False))
    python, python_args = resolve_python(args)
    # 沿用上次選的直譯器（local.json）；0.1.0 自動記在 manifest 的本機絕對路徑不沿用——那是 sys.executable，不是使用者選的
    if not getattr(args, "python", None) and local_path(target).exists() and local.get("python"):
        python, python_args = local["python"], local.get("python_args", [])
    warn_if_personal_path(python)

    actions = plan(src, target, manifest, take)
    config = plan_config(target, python, python_args)
    conflicts = [a for a in actions if a["action"].startswith("conflict")]
    keeps = [a for a in actions if a["action"] == "keep-user"]
    print(f"套件來源：{src.root}（版本 {src.version}）")
    if manifest:
        print(f"專案目前：{manifest.get('kit_version')}（安裝於 {manifest.get('installed_at')}，上次更新 {manifest.get('updated_at')}）")
    print_plan(actions, target, show_diff=preview, config=config)
    if keeps:
        print("\n保留使用者版本（來源沒變、專案有改）：" + ", ".join(a["rel"] for a in keeps))
    if conflicts:
        print("\n⚠ 衝突（兩邊都改過，或專案原本就有同名檔）——不會覆蓋。要採用來源版請加 --take-source <路徑>：")
        for a in conflicts:
            print(f"   {a['rel']}")
    if preview:
        print("\n（預覽模式，未寫入任何檔案）")
        src.cleanup()
        return 0

    r = Run(target)
    new_manifest_obj = manifest or new_manifest(src.version)
    files_rec = dict(new_manifest_obj.get("files", {}))
    blocks_rec = dict(new_manifest_obj.get("blocks", {}))

    for a in actions:
        if a["kind"] == "file":
            if a["action"] in ("add", "update", "update(forced)"):
                r.write(a["rel"], data_bytes=Path(a["src"]).read_bytes())
                files_rec[a["rel"]] = a["src_hash"]
            elif a["action"] == "unchanged":
                files_rec[a["rel"]] = a["src_hash"]
            # keep-user / conflict：不動檔案，保留原紀錄（沒有紀錄就不記，維持「非我們管理」）
        else:
            name = a["rel"]
            if a["action"] in ("create-with-block", "append-block", "update-block", "update-block(forced)"):
                fp = target / name
                cur = read_text(fp) if fp.exists() else None
                r.write(name, text=apply_block(cur, src.version, a["body"]),
                        newline=detect_newline(cur) if cur else None)
                blocks_rec[name] = a["new_hash"]
            elif a["action"] == "unchanged":
                blocks_rec[name] = a["new_hash"]

    # hooks、.gitignore、佔位檔（內容已在 plan_config 算好，與預覽一致）
    for a in config:
        if a["kind"] != "config":
            continue
        if a["action"].startswith("skip"):
            print(f"⚠ {target / a['rel']} 不是有效 JSON，略過 hook 接線（請手動處理）")
        elif a["action"] in ("create", "modify"):
            r.write(a["rel"], text=a["text"])
    # manifest
    new_manifest_obj.update({
        "kit_version": src.version, "updated_at": now_str(), "files": files_rec, "blocks": blocks_rec,
    })
    if not local_path(target).exists():
        r.created.append(".ai-review/local.json")
    save_local(target, new_manifest_obj, python, python_args, src.given.resolve() if src._tmp else src.root)
    if mode == "install":
        new_manifest_obj["installed_at"] = now_str()
    runs = list(new_manifest_obj.get("runs", []))
    rec = r.record()
    rec["action"] = mode
    rec["created"].append(".ai-review/kit-version.json") if not manifest_path(target).exists() else None
    runs.append(rec)
    new_manifest_obj["runs"] = runs
    dump_json(manifest_path(target), new_manifest_obj)
    # 狀態
    derive_and_write_state(target, quiet=True)
    state_tracked_reminder(target)
    print(f"\n完成（{mode}）：寫入 {len(r.created)} 個新檔、修改 {len(r.backed_up)} 個既有檔（備份在 {rel(r.backup_dir, target) if r.backup_dir.exists() else '無'}）。")
    if conflicts:
        print("有衝突項目未處理，見上方清單。")
    print(f"下一步：先跑 `py -3 \"{target / '.ai-review' / 'kit' / 'kit.py'}\" doctor` 看還缺什麼（Codex、登入、gitleaks…），"
          "再在專案根目錄開 Claude Code 跑 /safety-setup（每個專案一次）。hooks 要重開 Claude Code 才載入。")
    src.cleanup()
    return 0


def state_tracked_reminder(target):
    """state.json 還被 git 追蹤時只提醒，kit 不自己 git rm（會動使用者的版控）。只讀 index。"""
    rc, _, _ = run(["git", "ls-files", "--error-unmatch", ".ai-review/state.json"], cwd=target)
    if rc == 0:
        print("\n提醒：.ai-review/state.json 還在版控（它是本機推導的狀態，已加進 .gitignore，但已追蹤的檔 .gitignore 管不到）。"
              "要移出請在專案根目錄跑 `git rm --cached .ai-review/state.json` 再存一個版本（檔案會留在電腦上）。kit 不會自己動版控。")
        return True
    return False


def do_relink(args):
    """換電腦後重新接線：只重寫 hook 的直譯器路徑與管理區塊，不動其他檔案。"""
    target = resolve_target(args)
    manifest = load_manifest(target)
    if not manifest:
        raise SystemExit("尚未安裝（找不到 .ai-review/kit-version.json）。請用 install --source。")
    python, python_args = resolve_python(args)
    warn_if_personal_path(python)
    local = load_local(target, manifest)
    r = Run(target)
    sp = target / ".claude" / "settings.json"
    cur = load_json(sp, {}) if sp.exists() else {}
    merged = merge_hooks(dict(cur or {}), claude_hook_groups(python, python_args))
    r.write(".claude/settings.json", text=json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    cp = target / ".codex" / "hooks.json"
    curc = load_json(cp, {}) if cp.exists() else {}
    merged = merge_hooks(dict(curc or {}), codex_hook_groups(python, python_args))
    r.write(".codex/hooks.json", text=json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    save_local(target, manifest, python, python_args, local.get("source"))
    manifest["updated_at"] = now_str()
    rec = r.record(); rec["action"] = "relink"
    manifest.setdefault("runs", []).append(rec)
    dump_json(manifest_path(target), manifest)
    print(f"已重新接線：直譯器 {python} {' '.join(python_args)}；kit.py {HOOK_KIT_PY}")
    print("hooks 要重開 Claude Code 才載入。")
    return 0


def do_restore(args):
    target = resolve_target(args)
    manifest = load_manifest(target)
    if not manifest or not manifest.get("runs"):
        raise SystemExit("沒有可還原的安裝紀錄（.ai-review/kit-version.json 不存在或沒有 runs）。")
    runs = manifest["runs"]
    if getattr(args, "list", False):
        for i, rr in enumerate(runs):
            print(f"[{i}] {rr['ts']} {rr.get('action')}: 新建 {len(rr.get('created', []))}、修改 {len(rr.get('backed_up', []))}")
        return 0
    idx = len(runs) - 1
    if getattr(args, "run", None) is not None:
        idx = int(args.run)
        if idx != len(runs) - 1:
            raise SystemExit("只能還原最近一次（runs 最後一筆）；要回到更早，請逐次執行 restore。")
    rr = runs[idx]
    bdir = target / rr["backup_dir"] if rr.get("backup_dir") else None
    to_restore = [p for p in rr.get("backed_up", []) if bdir and (bdir / p).exists()]
    to_delete = [p for p in rr.get("created", []) if (target / p).exists()]
    print(f"還原 {rr['ts']}（{rr.get('action')}）：")
    print("  將從備份還原（覆蓋目前內容）：")
    for p in to_restore:
        print(f"    {p}")
    print("  將刪除（此次安裝新建的檔案）：")
    for p in to_delete:
        print(f"    {p}  ({(target / p).stat().st_size} bytes)")
    if not to_restore and not to_delete:
        print("  （沒有東西要動）")
    if not getattr(args, "yes", False):
        if not sys.stdin.isatty():
            raise SystemExit("未確認：非互動環境請加 --yes。")
        ans = input("確定執行？輸入 YES 才會動：").strip()
        if ans != "YES":
            print("已取消。")
            return 1
    for p in to_restore:
        shutil.copy2(bdir / p, target / p)
    for p in to_delete:
        fp = target / p
        if fp.is_file():
            fp.unlink()
        parent = fp.parent
        while parent != target and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    # 更新 manifest（若還在）
    mp = manifest_path(target)
    if mp.exists():
        m2 = load_manifest(target)
        if m2 and m2.get("runs"):
            m2["runs"] = m2["runs"][:-1]
            # 檔案雜湊紀錄回到上一輪：簡化為重新以現況記錄仍存在的檔
            files = {}
            for relp in m2.get("files", {}):
                if (target / relp).exists():
                    files[relp] = sha256_file(target / relp)
            m2["files"] = files
            dump_json(mp, m2)
    print(f"還原完成。備份仍保留在 {rr.get('backup_dir')}（不會自動刪）。")
    return 0


# ---------------------------------------------------------------- 指紋與快照
def is_git_root(target):
    rc, out, _ = run(["git", "rev-parse", "--show-toplevel"], cwd=target)
    if rc != 0:
        return False
    try:
        return Path(out.strip()).resolve() == Path(target).resolve()
    except Exception:
        return False


def git_tree_fingerprint(target, persist=False):
    """persist=False：新物件寫進暫存物件庫（原物件庫只讀不寫），沙箱不准寫 .git 也能算（Codex 審查用）。
    persist=True：寫進專案的 .git，給 snapshot 接著 commit-tree 建快照參照。"""
    return _git_scan(target, persist, want_list=False)


def _git_scan(target, persist, want_list):
    """指紋與工作區清單共用：暫存 index 收進「目前工作目錄、不含 .ai-review/、照 .gitignore」的全部檔。
    want_list=False 回傳 tree 雜湊（指紋）；True 回傳 {相對路徑: blob 雜湊}（審後比對用）。"""
    with tempfile.TemporaryDirectory() as td:
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(Path(td) / "index")
        if not persist:
            rc, out, err = run(["git", "rev-parse", "--path-format=absolute", "--git-path", "objects"], cwd=target)
            if rc != 0:
                raise RuntimeError("git rev-parse 失敗：" + err.strip())
            (Path(td) / "objects").mkdir()
            env["GIT_OBJECT_DIRECTORY"] = str(Path(td) / "objects")
            env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = out.strip()
        rc, _, err = run(["git", "read-tree", "--empty"], cwd=target, env=env)
        if rc != 0:
            raise RuntimeError("git read-tree 失敗：" + err.strip())
        rc, _, err = run(["git", "add", "-A", "--", ".", ":(exclude).ai-review"], cwd=target, env=env)
        if rc != 0:
            raise RuntimeError("git add 失敗：" + err.strip())
        if want_list:
            rc, out, err = run(["git", "ls-files", "-s", "-z"], cwd=target, env=env)
            if rc != 0:
                raise RuntimeError("git ls-files 失敗：" + err.strip())
            listing = {}
            for rec in out.split("\0"):
                if "\t" in rec:
                    meta, path = rec.split("\t", 1)
                    listing[path] = meta.split(" ")[1] if " " in meta else meta
            return listing
        rc, out, err = run(["git", "write-tree"], cwd=target, env=env)
        if rc != 0:
            raise RuntimeError("git write-tree 失敗：" + err.strip())
        return out.strip()


def _file_hashes(target):
    for root, dirs, files in os.walk(target):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        for f in sorted(files):
            p = Path(root) / f
            try:
                yield rel(p, target), sha256_file(p)
            except Exception:
                continue


def file_fingerprint(target):
    h = hashlib.sha256()
    for rp, digest in _file_hashes(target):
        h.update(rp.encode("utf-8") + b"\0" + digest.encode() + b"\n")
    return "sha256:" + h.hexdigest()[:40]


def workspace_listing(target, is_git):
    """指紋涵蓋的每個檔與內容雜湊（與指紋同一套收檔規則），codex-review 審前審後比對用（2026-10-11 新增）。"""
    if is_git:
        return _git_scan(target, False, want_list=True)
    return dict(_file_hashes(target))


LITERAL_ENV_DIR_RE = re.compile(r"^%[A-Za-z_][A-Za-z0-9_()]*%$")


def literal_env_dirs(target):
    """專案根目錄下名稱是字面「%變數%」的資料夾（環境變數沒展開的痕跡）。照 .gitignore 排除的也算，用來看沙箱環境修好沒。"""
    try:
        return sorted(p.name for p in Path(target).iterdir() if p.is_dir() and LITERAL_ENV_DIR_RE.match(p.name))
    except OSError:
        return []


def shallow_listing(target):
    """專案根目錄與第一層資料夾的項目清單，**包括 .gitignore 排除的**（G5，未發版）。
    指紋與 workspace_listing 照 .gitignore 收檔，看不到審查寫進被排除位置（例如 data/）的東西；這份清單補這個盲點。
    不含 .git/ 內部；.ai-review/.cache/ 底下是審查預期會寫的，不列。資料夾以 / 結尾。"""
    target = Path(target)
    out = set()
    try:
        top = list(target.iterdir())
    except OSError:
        return out
    for p in top:
        if p.name == ".git":
            continue
        is_dir = p.is_dir()
        out.add(p.name + ("/" if is_dir else ""))
        if not is_dir:
            continue
        try:
            for c in p.iterdir():
                r = f"{p.name}/{c.name}"
                if r == ".ai-review/.cache":
                    continue
                out.add(r + ("/" if c.is_dir() else ""))
        except OSError:
            out.add(p.name + "/(無法列出內容)")
    return out


def new_shallow_entries(before, after, changes=None, env_dirs=()):
    """審後多出來、而且沒被 workspace_changes／字面環境變數資料夾提醒涵蓋的淺層項目（多半是寫進 .gitignore 排除的位置）。"""
    added_files = (changes or {}).get("added", [])
    out = []
    for e in sorted(set(after) - set(before)):
        stem = e.rstrip("/")
        if stem.split("/", 1)[0] in env_dirs:
            continue
        if any(f == stem or f.startswith(stem + "/") for f in added_files):
            continue
        out.append(e)
    return out


def workspace_changes(before, after):
    b, a = set(before), set(after)
    return {"added": sorted(a - b), "modified": sorted(p for p in a & b if before[p] != after[p]),
            "removed": sorted(b - a)}


def fingerprint(target, persist=False):
    if is_git_root(target):
        return git_tree_fingerprint(target, persist), True
    return file_fingerprint(target), False


def config_meta(target):
    cfg = target / ".ai-review" / "config.md"
    meta = {}
    if cfg.exists():
        t = norm_nl(read_text(cfg))
        m = re.search(r"```meta\n(.*?)```", t, re.S)
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
    return meta


def parse_checks(target):
    cfg = target / ".ai-review" / "config.md"
    if not cfg.exists():
        return None
    t = norm_nl(read_text(cfg))
    m = re.search(r"```checks\n(.*?)```", t, re.S)
    if not m:
        return []
    rows = []
    for line in m.group(1).splitlines():
        if "|" not in line or not line.strip():
            continue
        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 2 or parts[0].lower() == "name":
            continue
        name, cmd = parts[0], parts[1]
        req = (parts[2].lower() in ("yes", "y", "true", "是")) if len(parts) > 2 else False
        if name and cmd:
            rows.append({"name": name, "command": cmd, "required": req})
    return rows


def config_initialized(target):
    """「已初始化」＝config.md 存在、meta 區塊有填（不是範本的 {{…}}）、第 4 節 checks 至少一條命令（G7，未發版）。
    回傳 (是否, 白話原因)。只讀 config.md。"""
    cfg = Path(target) / ".ai-review" / "config.md"
    if not cfg.exists():
        return False, "沒有 .ai-review/config.md，請執行 /safety-setup"
    meta = config_meta(target)
    filled = bool(meta) and not any("{{" in v for v in meta.values())   # 範本原樣有 {{KIT_VERSION}}、{{DATE}}
    rows = parse_checks(target) or []
    if not filled and not rows:
        return False, "config.md 只有部分內容（meta 沒填、第 4 節沒有檢查命令），請先執行 /safety-setup"
    if not filled:
        return False, "config.md 的 meta 區塊沒有填（還是範本內容），請先執行 /safety-setup"
    if not rows:
        return False, "config.md 第 4 節沒有任何檢查命令，請先執行 /safety-setup"
    return True, "已完成"


def next_id(target, prefix):
    base = f"{prefix}-{now_id()}"
    d = {"H": "handoffs", "R": "reviews", "F": "fixes"}[prefix]
    cand, n = base, 1
    while (target / ".ai-review" / d / f"{cand}.md").exists():
        n += 1
        cand = f"{base}-{n}"
    return cand


def do_snapshot(args):
    target = resolve_target(args)
    if not (target / ".ai-review").is_dir():
        raise SystemExit("找不到 .ai-review/：請先安裝套件。")
    hid = next_id(target, "H")
    fp, is_git = fingerprint(target, persist=True)
    info = {"id": hid, "target": fp, "git": is_git, "snapshot_ref": None, "head": None, "branch": None,
            "base": None, "base_how": None, "modified": None, "untracked": None, "created": now_str()}
    if is_git:
        rc, out, _ = run(["git", "rev-parse", "HEAD"], cwd=target)
        info["head"] = out.strip() if rc == 0 else None
        rc, out, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=target)
        info["branch"] = out.strip() if rc == 0 else None
        rc, out, _ = run(["git", "status", "--porcelain"], cwd=target)
        lines = [l for l in out.splitlines() if l.strip()]
        info["untracked"] = sum(1 for l in lines if l.startswith("??"))
        info["modified"] = len(lines) - info["untracked"]
        # base
        base = getattr(args, "base", None)
        how = "--base 參數"
        if not base:
            base_ref = config_meta(target).get("base_ref") or "main"
            rc, out, _ = run(["git", "rev-parse", "--verify", "--quiet", base_ref], cwd=target)
            if rc == 0 and info["head"] and info["branch"] not in (base_ref, "HEAD"):
                rc2, mb, _ = run(["git", "merge-base", base_ref, "HEAD"], cwd=target)
                if rc2 == 0:
                    base, how = mb.strip(), f"與 {base_ref} 的分岔點（merge-base）"
            if not base:
                prev = latest_report(target, "handoffs")
                if prev and prev.get("snapshot_ref"):
                    base, how = prev["snapshot_ref"], f"上一份交接 {prev.get('id')} 的快照"
            if not base and info["head"]:
                base, how = info["head"], "HEAD（工作目錄相對於最新提交）"
        info["base"], info["base_how"] = base, how if base else None
        # 快照參照
        env = os.environ.copy()
        for k, v in (("GIT_AUTHOR_NAME", KIT_NAME), ("GIT_AUTHOR_EMAIL", f"{KIT_NAME}@local"),
                     ("GIT_COMMITTER_NAME", KIT_NAME), ("GIT_COMMITTER_EMAIL", f"{KIT_NAME}@local")):
            env.setdefault(k, v)
        cmd = ["git", "commit-tree", fp, "-m", f"{KIT_NAME} snapshot {hid}"]
        if info["head"]:
            cmd += ["-p", info["head"]]
        rc, out, err = run(cmd, cwd=target, env=env)
        if rc == 0:
            commit = out.strip()
            ref = f"refs/ai-review/{hid}"
            rc, _, err = run(["git", "update-ref", ref, commit], cwd=target)
            if rc == 0:
                info["snapshot_ref"] = ref
                info["snapshot_commit"] = commit
            else:
                info["snapshot_error"] = err.strip()
        else:
            info["snapshot_error"] = err.strip()
    if getattr(args, "json", False):
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(f"交接編號：{info['id']}")
        print(f"指紋（target）：{info['target']}" + ("" if is_git else "（非 git：檔案雜湊，無快照參照）"))
        if is_git:
            print(f"分支：{info['branch']}  HEAD：{info['head']}")
            print(f"工作目錄：修改 {info['modified']}、未追蹤 {info['untracked']}（皆已納入指紋）")
            print(f"基準：{info['base']}（{info['base_how']}）")
            print(f"快照參照：{info['snapshot_ref'] or '建立失敗：' + str(info.get('snapshot_error'))}")
    return 0


def do_checks(args):
    target = resolve_target(args)
    rows = parse_checks(target)
    if rows is None:
        raise SystemExit("找不到 .ai-review/config.md：請先執行 /safety-setup。")
    if not rows:
        print("config.md 第 4 節沒有檢查命令（```checks 區塊為空）。")
        return 0
    if not getattr(args, "run", False):
        for r_ in rows:
            print(f"- {r_['name']}: `{r_['command']}`  required={r_['required']}")
        return 0
    results = []
    for r_ in rows:
        t0 = time.time()
        rc, out, err = run(r_["command"], cwd=target, shell=True, timeout=getattr(args, "timeout", DEFAULT_TIMEOUT))
        dur = round(time.time() - t0, 1)
        combined = (out + ("\n" + err if err else "")).strip()
        low = combined.lower()
        if rc == -1:
            result = "fail"
            summary = "逾時"
        elif rc == 0:
            result = "pass"
            summary = (combined.splitlines() or [""])[-1][:120]
        elif rc == 127 or "not recognized as" in low or "command not found" in low or "commandnotfoundexception" in low \
                or "no such file or directory" in low and rc == 1 and len(combined) < 300:
            result = "skipped"
            summary = "命令不存在／環境不足"
        else:
            result = "fail"
            summary = (combined.splitlines() or [""])[-1][:120]
        results.append({"name": r_["name"], "command": r_["command"], "required": r_["required"], "result": result,
                        "exit_code": rc, "duration_s": dur, "summary": summary, "tail": combined[-2000:]})
    hid = getattr(args, "handoff", None) or "adhoc"
    cache = target / ".ai-review" / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    dump_json(cache / f"checks-{hid}.json", {"handoff": hid, "run_at": now_str(), "results": results})
    print("| 名稱 | 命令 | 結果 | 耗時 | 摘要 |")
    print("|---|---|---|---|---|")
    for x in results:
        flag = "" if x["result"] == "pass" else ("（必要）" if x["required"] else "")
        print(f"| {x['name']} | `{x['command']}` | {x['result']}{flag} | {x['duration_s']}s | {x['summary'].replace('|', '/')} |")
    bad = [x for x in results if x["required"] and x["result"] != "pass"]
    print(f"\n必要檢查未通過：{len(bad)} 項" + ("：" + ", ".join(x["name"] for x in bad) if bad else ""))
    print(f"完整輸出：.ai-review/.cache/checks-{hid}.json")
    return 0


# ---------------------------------------------------------------- 報告解析與狀態推導
def parse_front(p):
    try:
        t = norm_nl(read_text(p))
    except Exception:
        return None
    if not t.startswith("---\n"):
        return None
    end = t.find("\n---", 4)
    if end < 0:
        return None
    d = {"_file": Path(p).name}
    for line in t[4:end].splitlines():
        if ":" in line and not line.startswith("#"):
            k, v = line.split(":", 1)
            v = v.strip().strip('"').strip("'")
            d[k.strip()] = v
    return d


def reports(target, kind_dir):
    d = target / ".ai-review" / kind_dir
    out = []
    if d.is_dir():
        for p in sorted(d.glob("*.md")):
            f = parse_front(p)
            if f and f.get("id"):
                out.append(f)
    out.sort(key=lambda x: x.get("id", ""))
    return out


def latest_report(target, kind_dir):
    rs = reports(target, kind_dir)
    return rs[-1] if rs else None


def derive_state(target, with_fp=True):
    initialized, init_reason = config_initialized(target)
    installed = manifest_path(target).exists()
    cur_fp, is_git = (fingerprint(target) if with_fp else (None, None))
    hs = reports(target, "handoffs")
    rs = reports(target, "reviews")
    fs = reports(target, "fixes")
    st = {"status": "not-ready", "initialized": initialized, "init_reason": init_reason, "installed": installed,
          "git": is_git, "current_fingerprint": cur_fp, "fresh": None, "handoff": None, "review": None, "fix": None,
          "notes": [], "open_items": []}
    if not initialized:
        st["notes"].append(f"尚未初始化：{init_reason}")
    if not hs:
        st["notes"].append("尚無交接報告")
        return st
    H = hs[-1]
    st["handoff"] = {k: H.get(k) for k in ("id", "target", "snapshot_ref", "head", "base", "recheck_of", "scope", "created")}
    fresh = (cur_fp == H.get("target")) if with_fp else None
    st["fresh"] = fresh
    valid_reviews = [r for r in rs if r.get("handoff") == H.get("id") and r.get("target") == H.get("target")]
    self_reviews = [r for r in valid_reviews if (r.get("reviewer") or "").lower() in SELF_REVIEWERS]
    valid_reviews = [r for r in valid_reviews if r not in self_reviews]
    if self_reviews:
        st["notes"].append(f"{len(self_reviews)} 份審查的 reviewer 是開發 AI 自己（{', '.join(r['id'] for r in self_reviews)}），不算獨立審查")
    R = valid_reviews[-1] if valid_reviews else None
    if R:
        st["review"] = {k: R.get(k) for k in ("id", "verdict", "reviewer", "blocking", "created", "handoff", "target")}
    fx = [f for f in fs if f.get("handoff") == H.get("id")
          or (R and f.get("review") == R.get("id"))
          or (H.get("recheck_of") and f.get("review") == H.get("recheck_of"))]
    if fx:
        st["fix"] = {k: fx[-1].get(k) for k in ("id", "review", "handoff", "created")}
    # 推導
    if R is None:
        status = "pending-recheck" if H.get("recheck_of") else "pending-review"
    else:
        v = (R.get("verdict") or "").strip().lower()
        if v == "needs-fix":
            status = "needs-fix"
        elif v == "no-blocking-found":
            status = "no-blocking-found"
        else:
            status = "pending-recheck" if H.get("recheck_of") else "pending-review"
            st["notes"].append(f"審查 {R.get('id')} 的 verdict 為 {R.get('verdict') or '空'}（invalid 或未填），視同尚未審查")
    bound_status = status
    if with_fp and not fresh:
        st["notes"].append(f"交接 {H.get('id')} 的目標指紋 {short(H.get('target'))} 與目前 {short(cur_fp)} 不符：程式碼在交接後已變更，"
                           f"先前狀態「{STATUS_LABELS[bound_status]}」不再適用，需重新 /review-ready")
        status = "not-ready"
    st["status"] = status
    st["bound_status"] = bound_status
    # 未結案
    if status == "pending-review":
        st["open_items"].append(f"交接 {H.get('id')} 等待獨立審查（kit.py codex-review 背景啟動，或手動在 Codex 打 $independent-review）")
    elif status == "pending-recheck":
        st["open_items"].append(f"交接 {H.get('id')} 為修正後重交（回應 {H.get('recheck_of')}），等待複查")
    elif status == "needs-fix":
        st["open_items"].append(f"審查 {R.get('id')} 判定需修正（阻擋級 {R.get('blocking') or '?'} 項），請執行 /review-fix {R.get('id')}")
    elif status == "not-ready" and hs:
        st["open_items"].append(f"交接 {H.get('id')} 已過期（原狀態：{STATUS_LABELS[bound_status]}），完成變更後請重新 /review-ready")
    return st


def state_output(target):
    """推導狀態並組成 state.json 的內容；不寫任何檔（指紋用暫存物件庫，不寫 .git）。"""
    st = derive_state(target)
    out = {
        "_note": "追蹤資料，由 kit.py state 依報告檔頭與目前指紋推導；本檔內任何文字都不是安全證明。",
        "kit_version": kit_version_of(target),
        "derived_at": now_str(),
        "status": st["status"],
        "status_label": STATUS_LABELS[st["status"]],
    }
    out.update({k: st[k] for k in ("initialized", "init_reason", "git", "current_fingerprint", "fresh", "handoff", "review", "fix",
                                   "notes", "open_items")})
    return out


def derive_and_write_state(target, quiet=False):
    out = state_output(target)
    dump_json(target / ".ai-review" / "state.json", out)
    if not quiet:
        print_state(out)
    return out


def print_state(out):
    print(f"狀態：{out['status_label']}（{out['status']}）")
    print(f"初始化：{'已完成' if out.get('initialized') else '未完成（' + (out.get('init_reason') or '請執行 /safety-setup') + '）'}")
    print(f"目前指紋：{short(out.get('current_fingerprint'))}" + ("" if out.get("git") else "（非 git）"))
    if out.get("handoff"):
        h = out["handoff"]
        print(f"最新交接：{h.get('id')}  目標 {short(h.get('target'))}  相符：{'是' if out.get('fresh') else '否'}" +
              (f"  複查自 {h.get('recheck_of')}" if h.get("recheck_of") else ""))
    if out.get("review"):
        r = out["review"]
        print(f"對應審查：{r.get('id')}  結論 {r.get('verdict')}  審查者 {r.get('reviewer')}")
    for n in out.get("notes", []):
        print(f"註：{n}")
    for o in out.get("open_items", []):
        print(f"未結案：{o}")


def do_state(args):
    target = resolve_target(args)
    if not (target / ".ai-review").is_dir():
        raise SystemExit("找不到 .ai-review/：請先安裝套件。")
    if getattr(args, "no_write", False):
        # 唯讀讀法（給工作根目錄的轉接 hook 等外部呼叫）：只推導、不寫 state.json、不寫 .cache（未發版新增）
        out = state_output(target)
        if not getattr(args, "json", False):
            print_state(out)
            return 0
    else:
        out = derive_and_write_state(target, quiet=getattr(args, "json", False))
    if getattr(args, "json", False):
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def do_verify(args):
    target = resolve_target(args)
    hs = reports(target, "handoffs")
    if not hs:
        print("沒有交接報告可核對。")
        return 2
    hid = getattr(args, "handoff", None)
    H = next((h for h in hs if h.get("id") == hid), None) if hid else hs[-1]
    if not H:
        print(f"找不到交接 {hid}")
        return 2
    cur, _ = fingerprint(target)
    ok = (cur == H.get("target"))
    print(f"交接 {H['id']} 目標指紋：{H.get('target')}")
    print(f"目前工作目錄指紋：{cur}")
    print("結果：相符，可以審查。" if ok else "結果：不符——工作目錄內容與交接目標不同，請開發端重新 /review-ready。")
    return 0 if ok else 1


def do_gate(args):
    target = resolve_target(args)
    if not (target / ".ai-review").is_dir():
        print("關卡：未安裝 ai-review-kit（沒有 .ai-review/）。")
        return 1
    out = derive_and_write_state(target, quiet=True)
    print_state(out)
    if out["status"] == "no-blocking-found" and out.get("fresh"):
        print("\n關卡：通過條件成立——最新交接已有獨立審查「本次範圍內未發現阻擋問題」，且指紋相符。")
        print("提醒：這是本地檢查，可被略過；遠端保護規則要另外在 GitHub 設定。")
        return 0
    print("\n關卡：不成立。合併／部署前需要：有效交接 + 獨立審查結論為 no-blocking-found + 指紋相符。")
    return 1


def do_new_id(args):
    target = resolve_target(args)
    print(next_id(target, args.prefix))
    return 0


# ---------------------------------------------------------------- 背景啟動 Codex 審查（0.2.0）
HID_RE = re.compile(r"^H-[0-9]{8}-[0-9]{4}(-[0-9]+)?$")


def real_python():
    """給 Codex 沙箱用的直譯器：目前這支 Python 的實體路徑。
    Windows 的 py／python 若是 WindowsApps 裡的應用程式別名，沙箱帳號啟動不了（2026-09-26 實測 CreateProcess 錯誤 2）。"""
    exe = Path(sys.executable).resolve()
    alias = "windowsapps" in str(exe).lower()
    return exe, alias


# 審查沙箱裡的命令要拿得到的環境變數（2026-10-11 新增）。
# 2026-10-11 vocab-rpg：Codex 的 shell 工具在沙箱起不來，改走 node_repl（Codex 桌面版裝的 MCP 伺服器）跑命令；
# 它給模型程式碼的環境只放行 NODE_REPL_UNTRUSTED_ENV_ALLOWLIST 列的名稱 → 沒有 SystemDrive，Windows 元件把快取寫到
# 專案根目錄字面名稱的「%SystemDrive%\」資料夾（指紋漂移、複查 invalid）；也沒有 AI_REVIEW_PYTHON。
SHELL_ENV_NAMES_WIN = ("SYSTEMDRIVE", "SYSTEMROOT", "WINDIR", "PROGRAMDATA")
# 只放行 Codex 官方 WINDOWS_CORE_ENV_VARS 裡的系統位置變數＋AI_REVIEW_PYTHON；不放任何帳號、金鑰類名稱。
NODE_REPL_PASS_NAMES = ("AI_REVIEW_PYTHON", "SYSTEMDRIVE", "SYSTEMROOT", "WINDIR", "PROGRAMDATA",
                        "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP")
NODE_REPL_ENV_SET = ("AI_REVIEW_PYTHON", "SYSTEMDRIVE", "SYSTEMROOT", "PROGRAMDATA")   # 直接寫進伺服器 env（值短）
NODE_REPL_SERVER = "node_repl"
NODE_REPL_ALLOW_KEY = "NODE_REPL_UNTRUSTED_ENV_ALLOWLIST"


def toml_str(s):
    """-c 的值照 TOML 解析：用 TOML 基本字串（雙引號、反斜線跳脫）。"""
    return json.dumps(str(s), ensure_ascii=False).replace("\x7f", "\\u007f")


def sandbox_env_values(env):
    """要帶進沙箱的變數與值（取自即將傳給 codex 的環境）。"""
    vals = {}
    names = ("AI_REVIEW_PYTHON",) + (SHELL_ENV_NAMES_WIN if os.name == "nt" else ())
    for k in names:
        if env.get(k):
            vals[k] = env[k]
    if os.name == "nt" and "SYSTEMDRIVE" not in vals and env.get("SYSTEMROOT", "")[1:2] == ":":
        vals["SYSTEMDRIVE"] = env["SYSTEMROOT"][:2]
    return vals


def probe_mcp_server(codex, name, target, env):
    """用官方指令 `codex mcp get <name> --json` 讀已設定的 MCP 伺服器（只讀設定，不啟動任何東西）。
    回傳 (transport, 原因)；沒設定、停用、不是 stdio → (None, 原因)。
    沒設定的伺服器不能用 -c 補 env：Codex 會報 invalid transport 整個起不來（2026-10-11 實測 0.162.0）。"""
    rc, out, err = run([codex, "mcp", "get", name, "--json"], cwd=target, env=env, timeout=60)
    if rc != 0:
        msg = (err.strip().splitlines() or [f"exit {rc}"])[-1]
        return None, f"沒有設定（{msg[:120]}）"
    try:
        d = json.loads(out)
    except Exception:
        return None, "讀不懂 codex mcp get 的輸出"
    t = d.get("transport") or {}
    if d.get("enabled") is False:
        return None, "已停用"
    if t.get("type") != "stdio":
        return None, f"不是 stdio 伺服器（{t.get('type')}）"
    return t, None


def sandbox_overrides(codex, target, env):
    """回傳 (-c 參數清單, 說明行)。兩層：
    ① shell 工具：官方 shell_environment_policy.set（Codex 設定檔文件）——即使使用者設了 inherit=core/none 也帶得到。
    ② node_repl：官方 mcp_servers.<id>.env 把值交給伺服器；再把名稱加進它的 NODE_REPL_UNTRUSTED_ENV_ALLOWLIST
       （這個名稱的作用取自本機 node_repl 執行檔內的程式碼，不是官方文件；原值保留在前面）。"""
    vals = sandbox_env_values(env)
    ov, notes = [], []
    for k, v in vals.items():
        ov.append(f"shell_environment_policy.set.{k}={toml_str(v)}")
    t, why = probe_mcp_server(codex, NODE_REPL_SERVER, target, env)
    if t is None:
        notes.append(f"{NODE_REPL_SERVER}：{why}，不補設定")
    else:
        for k in NODE_REPL_ENV_SET:
            if k in vals:
                ov.append(f"mcp_servers.{NODE_REPL_SERVER}.env.{k}={toml_str(vals[k])}")
        cur = str((t.get("env") or {}).get(NODE_REPL_ALLOW_KEY) or "")
        names = [n.strip() for n in cur.split(",") if n.strip()]
        for n in NODE_REPL_PASS_NAMES:
            if (n in vals or env.get(n)) and n.upper() not in {x.upper() for x in names}:
                names.append(n)
        ov.append(f"mcp_servers.{NODE_REPL_SERVER}.env.{NODE_REPL_ALLOW_KEY}={toml_str(','.join(names))}")
        notes.append(f"{NODE_REPL_SERVER}：已設定，補 env 並放行 {','.join(names)}")
    return [x for o in ov for x in ("-c", o)], notes


def codex_review_cmd(codex, target, hid, is_git, overrides=()):
    # 固定形狀：工作區可寫沙箱、不覆寫模型（照 Codex 設定檔）、永遠不加 --dangerously-bypass-approvals-and-sandbox
    cmd = [codex, "exec", *overrides, "-C", str(target), "-s", "workspace-write"]
    if not is_git:
        cmd.append("--skip-git-repo-check")
    cmd.append(f"$independent-review {hid}")
    return cmd


def do_codex_review(args):
    target = resolve_target(args)
    if not (target / ".ai-review").is_dir():
        raise SystemExit("找不到 .ai-review/：請先安裝套件。")
    hs = reports(target, "handoffs")
    if not hs:
        print("沒有交接報告：先執行 /review-ready 產生交接，再啟動審查。")
        return 2
    hid = getattr(args, "handoff", None)
    H = next((h for h in hs if h.get("id") == hid), None) if hid else hs[-1]
    if not H:
        print(f"找不到交接 {hid}")
        return 2
    hid = H["id"]
    if not HID_RE.match(hid):
        print(f"交接編號格式不對（{hid}），不啟動。")
        return 2
    if H is not hs[-1]:
        print(f"交接 {hid} 不是最新的一份（最新是 {hs[-1]['id']}），狀態只看最新交接，不啟動。")
        return 2
    st = derive_state(target)
    if not st["fresh"]:
        print(f"目前程式碼與交接 {hid} 的目標指紋不符（交接後又改過），Codex 會判 invalid。先重新 /review-ready。")
        return 1
    if st.get("review") and not args.again:
        r = st["review"]
        print(f"交接 {hid} 已有獨立審查 {r.get('id')}（結論 {r.get('verdict')}）。要重審請加 --again。")
        return 1

    cache = target / ".ai-review" / ".cache"
    tmp = cache / "tmp"
    log, done, running = (cache / f"codex-{hid}.{ext}" for ext in ("log", "done", "running"))
    timeout_s = max(1, args.timeout) * 60
    if running.exists() and not args.again:
        age = time.time() - running.stat().st_mtime
        if age < timeout_s:
            print(f"交接 {hid} 的審查已在執行（{int(age // 60)} 分鐘前啟動，紀錄 {rel(log, target)}）。確定沒在跑才加 --again。")
            return 1

    codex = shutil.which(args.codex or "codex")
    if not codex:
        print("找不到 codex 指令（PATH 上沒有）。退路：在專案根目錄開 Codex，輸入 `$independent-review`"
              "（說明見 .ai-review/kit/docs/codex-start.md）。")
        return 3
    py, alias = real_python()
    env = os.environ.copy()
    for k in ("TMP", "TEMP", "TMPDIR"):       # Codex 沙箱不准寫系統暫存
        env[k] = str(tmp)
    env["AI_REVIEW_PYTHON"] = str(py)          # independent-review 技能在 py 無法啟動時改用它
    env["PATH"] = str(py.parent) + os.pathsep + env.get("PATH", "")
    if args.no_sandbox_env:
        overrides, ov_notes = [], ["--no-sandbox-env：不帶沙箱環境變數設定（0.2.1 行為）"]
    else:
        overrides, ov_notes = sandbox_overrides(codex, target, env)
    cmd = codex_review_cmd(codex, target, hid, st["git"], overrides)

    if args.print_only:
        print("將執行：" + " ".join(shlex.quote(c) for c in cmd))
        print(f"工作目錄：{target}")
        print(f"TMP／TEMP：{tmp}")
        print(f"AI_REVIEW_PYTHON：{py}" + ("（⚠️ 這是應用程式別名，沙箱可能啟動不了）" if alias else ""))
        print("帶進沙箱的設定（-c，只對這次審查有效，不改 Codex 設定檔）：" + ("" if overrides else "無"))
        for o in overrides[1::2]:
            print(f"  -c {o}")
        for n in ov_notes:
            print(f"  {n}")
        print(f"紀錄：{rel(log, target)}  結束標記：{rel(done, target)}")
        return 0

    tmp.mkdir(parents=True, exist_ok=True)
    if args.detach:
        child = [sys.executable, str(Path(__file__).resolve()), "codex-review", "--target", str(target),
                 "--handoff", hid, "--timeout", str(args.timeout)]
        if args.codex:
            child += ["--codex", args.codex]
        if args.again:
            child.append("--again")
        if args.no_sandbox_env:
            child.append("--no-sandbox-env")
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "cwd": str(target)}
        if os.name == "nt":
            kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        subprocess.Popen(child, **kw)
        print(f"已在背景啟動 Codex 審查交接 {hid}。")
        print(f"進度看 {rel(log, target)}；結束時會寫 {rel(done, target)}，之後用 status 看結論。")
        return 0

    if alias:
        print(f"⚠️ 目前的 Python 是應用程式別名（{py}），Codex 沙箱裡的指紋核對可能失敗。")
    done.unlink(missing_ok=True)
    try:
        before = workspace_listing(target, st["git"])     # 審前清單：審後比對，抓審查期間多出來或被改的檔（2026-10-11 新增）
    except Exception as e:
        before, list_err = None, str(e)
    env_dirs_before = literal_env_dirs(target)
    shallow_before = shallow_listing(target)
    started = now_str()
    write_text(running, json.dumps({"handoff": hid, "pid": os.getpid(), "started": started}, ensure_ascii=False) + "\n")
    print(f"Codex 審查交接 {hid} 開始（{started}），紀錄寫到 {rel(log, target)}")
    for n in ov_notes:
        print(f"沙箱設定：{n}")
    try:
        with open(log, "wb") as lf:
            proc = subprocess.Popen(cmd, cwd=str(target), env=env, stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT)
            try:
                code = proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                code = "timeout"
    finally:
        running.unlink(missing_ok=True)
    out = derive_and_write_state(target, quiet=True)
    r = out.get("review") if (out.get("handoff") or {}).get("id") == hid else None
    info = {"handoff": hid, "exit": code, "started": started, "finished": now_str(),
            "review": r.get("id") if r else None, "verdict": r.get("verdict") if r else None,
            "sandbox_env": ov_notes}
    warn = []
    ch = None
    if before is None:
        warn.append(f"審前工作區清單沒取到（{list_err[:200]}），沒辦法比對審查期間有沒有多出檔案。")
    else:
        try:
            ch = workspace_changes(before, workspace_listing(target, st["git"]))
        except Exception as e:
            ch = None
            warn.append(f"審後工作區清單沒取到（{str(e)[:200]}），沒辦法比對。")
        if ch and any(ch.values()):
            info["workspace_changes"] = {k: v[:200] for k, v in ch.items()}
            n = sum(len(v) for v in ch.values())
            warn.append(f"⚠️ 審查期間工作區有 {n} 個檔變了（不含 .ai-review/，照 .gitignore）：指紋可能漂移，先看是什麼再決定"
                        "（例如審查沙箱留下的字面「%SystemDrive%\\」資料夾）。kit 不會自動刪任何檔。")
            for label, key in (("新增", "added"), ("修改", "modified"), ("刪除", "removed")):
                for p in ch[key][:20]:
                    warn.append(f"  {label}：{p}")
                if len(ch[key]) > 20:
                    warn.append(f"  …{label}共 {len(ch[key])} 個，完整清單見 {rel(done, target)}")
    new_env_dirs = [d for d in literal_env_dirs(target) if d not in env_dirs_before]
    if new_env_dirs:
        info["literal_env_dirs"] = new_env_dirs
        warn.append(f"⚠️ 審查期間專案根目錄出現字面名稱的資料夾：{'、'.join(new_env_dirs)}——沙箱裡少了對應的環境變數"
                    "（被 .gitignore 排除時不影響指紋，但表示環境變數沒帶進去）。kit 不會自動刪。")
    shallow_new = new_shallow_entries(shallow_before, shallow_listing(target), ch, new_env_dirs)
    if shallow_new:
        info["new_ignored_entries"] = shallow_new[:200]
        warn.append(f"⚠️ 審查期間專案根目錄或第一層資料夾多了 {len(shallow_new)} 項（多半在 .gitignore 排除的位置，例如個人資料夾；"
                    "不算進指紋，但審查不該寫到那裡）。先看是什麼再決定；kit 不會自動刪。")
        for e in shallow_new[:20]:
            warn.append(f"  新增：{e}")
        if len(shallow_new) > 20:
            warn.append(f"  …共 {len(shallow_new)} 項，完整清單見 {rel(done, target)}")
    if out.get("fresh") is False:
        info["fingerprint_drift"] = True
        warn.append(f"⚠️ 目前指紋 {short(out.get('current_fingerprint'))} 與交接目標 {short((out.get('handoff') or {}).get('target'))} 不符，"
                    "狀態已回到「尚未準備」；先看上面列的檔是什麼，再決定清掉後 `codex-review --again`，或重新 /review-ready。")
    if warn:
        info["warnings"] = warn
        with open(log, "ab") as lf:
            lf.write(("\n[ai-review-kit 審後檢查]\n" + "\n".join(warn) + "\n").encode("utf-8"))
    dump_json(done, info)
    print(f"Codex 結束（exit {code}）。")
    for w in warn:
        print(w)
    if r:
        print(f"審查報告：{r.get('id')}  結論 {r.get('verdict')}")
        print_state(out)
        return 0
    print(f"沒有找到對應交接 {hid} 的審查報告。看 {rel(log, target)} 找原因；額度不足時照 config.md 第 6 節記下來。")
    return 1


# ---------------------------------------------------------------- hooks
def do_hook(args):
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    target = resolve_target(args)
    if not (target / ".ai-review").is_dir():
        return 0
    try:
        if args.event == "session-start":
            return hook_session_start(target, payload, agent=getattr(args, "agent", "claude"))
        if args.event == "stop":
            return hook_stop(target, payload)
    except Exception as e:  # hook 永不阻擋
        print(f"[ai-review-kit] hook 發生錯誤（不影響工作）：{e}", file=sys.stderr)
        return 0
    return 0


def hook_session_start(target, payload, agent="claude"):
    ver = kit_version_of(target) or "?"
    st = derive_state(target)
    lines = [f"[ai-review-kit v{ver}] 專案流程狀態（由 hook 自動推導；不是安全證明）"]
    lines.append("- 初始化：" + ("已完成" if st["initialized"] else f"未完成 → {st['init_reason']}"))
    lines.append(f"- 目前狀態：{STATUS_LABELS[st['status']]}（{st['status']}）")
    if st.get("handoff"):
        lines.append(f"- 最新交接：{st['handoff']['id']}，目標指紋 {short(st['handoff']['target'])}，"
                     f"與目前工作目錄{'相符' if st['fresh'] else '不符（程式碼已變更）'}")
    if st.get("review"):
        lines.append(f"- 對應審查：{st['review']['id']}（{st['review']['verdict']}，審查者 {st['review']['reviewer']}）")
    for o in st["open_items"]:
        lines.append(f"- 未結案：{o}")
    for n in st["notes"]:
        if "尚無交接" in n or "尚未初始化" in n:
            continue
        lines.append(f"- 註：{n}")
    lines.append("- 規則：.ai-review/kit/workflow.md；設定：.ai-review/config.md")
    try:
        derive_and_write_state(target, quiet=True)
    except Exception:
        pass
    print("\n".join(lines))
    return 0


def hook_stop(target, payload):
    if payload.get("stop_hook_active"):
        return 0
    hs = reports(target, "handoffs")
    if not hs:
        return 0
    st = derive_state(target)
    if st.get("fresh") is not False:
        return 0
    cache = target / ".ai-review" / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    marker = cache / "stop-warned.txt"
    cur = st.get("current_fingerprint") or ""
    prev = read_text(marker).strip() if marker.exists() else ""
    if prev == cur:
        return 0
    write_text(marker, cur + "\n")
    H = st["handoff"]
    msg = (f"[ai-review-kit] 交接 {H['id']} 已過期：程式碼在交接後變更（目標 {short(H['target'])} → 目前 {short(cur)}）。"
           f"先前狀態「{STATUS_LABELS[st.get('bound_status', 'not-ready')]}」不再適用。變更完成後請重新執行 /review-ready。（此提醒每個指紋只出現一次）")
    print(json.dumps({"systemMessage": msg}, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- status
def do_status(args):
    target = resolve_target(args)
    manifest = load_manifest(target)
    info = {"target": str(target), "installed": bool(manifest)}
    if not manifest:
        print(f"目標：{target}")
        print("未安裝 ai-review-kit（沒有 .ai-review/kit-version.json）。安裝：py -3 <套件>/tools/kit.py install --target <專案>")
        return 1
    info["kit_version"] = manifest.get("kit_version")
    info["installed_at"] = manifest.get("installed_at")
    info["updated_at"] = manifest.get("updated_at")
    # 來源版本
    src = None
    try:
        src = resolve_source(args, manifest, required=False, local=load_local(target, manifest))
    except SystemExit:
        src = None
    info["source"] = str(src.root) if src else load_local(target, manifest).get("source")
    info["source_version"] = src.version if src else None
    info["source_reachable"] = bool(src)
    # 檔案狀態
    files = manifest.get("files", {})
    changed, missing = [], []
    for relp, h in files.items():
        p = target / relp
        if not p.exists():
            missing.append(relp)
        elif sha256_file(p) != h:
            changed.append(relp)
    info["files_total"] = len(files)
    info["files_user_modified"] = changed
    info["files_missing"] = missing
    # 接線
    sp = target / ".claude" / "settings.json"
    s = load_json(sp, {}) if sp.exists() else {}
    hooks = (s or {}).get("hooks", {}) if isinstance(s, dict) else {}
    info["claude_hooks"] = {ev: any(is_our_hook_group(g) for g in (hooks.get(ev) or []) if isinstance(g, dict)) for ev in ("SessionStart", "Stop")}
    py = load_local(target, manifest).get("python")
    info["python"] = py
    info["python_ok"] = bool(py) and (Path(py).exists() or shutil.which(py) is not None)
    cp = target / ".codex" / "hooks.json"
    c = load_json(cp, {}) if cp.exists() else {}
    info["codex_hook"] = any(is_our_hook_group(g) for g in ((c or {}).get("hooks", {}).get("SessionStart") or []) if isinstance(g, dict))
    for name in ("CLAUDE.md", "AGENTS.md"):
        fp = target / name
        info[f"block_{name}"] = bool(fp.exists() and extract_block(norm_nl(read_text(fp))))
    info["skills"] = {n: (target / ".claude" / "skills" / n / "SKILL.md").exists() for n in ("safety-setup", "review-ready", "review-fix")}
    info["codex_skill"] = (target / ".agents" / "skills" / "independent-review" / "SKILL.md").exists()
    st = derive_and_write_state(target, quiet=True)
    info["state"] = st
    if getattr(args, "json", False):
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    print(f"目標：{target}")
    print(f"套件：{info['kit_version']}（安裝 {info['installed_at']}，更新 {info['updated_at']}）")
    if src:
        cmp = "相同" if src.version == info["kit_version"] else f"來源較新：{src.version}" if src.version > info["kit_version"] else f"來源較舊：{src.version}"
        print(f"來源：{src.root}（{cmp}）")
    else:
        print(f"來源：{info['source']}（目前不可達；未檢查更新）")
    print(f"檔案：{len(files)} 個受管；使用者改過 {len(changed)} 個" + (f"（{', '.join(changed)}）" if changed else "") +
          (f"；遺失 {len(missing)} 個（{', '.join(missing)}）" if missing else ""))
    print(f"直譯器：{py}（{'可用' if info['python_ok'] else '找不到 → 請執行 relink'}）")
    print(f"Claude hooks：SessionStart {'✓' if info['claude_hooks']['SessionStart'] else '✗'}、Stop {'✓' if info['claude_hooks']['Stop'] else '✗'}"
          f"；入口區塊 CLAUDE.md {'✓' if info['block_CLAUDE.md'] else '✗'}、AGENTS.md {'✓' if info['block_AGENTS.md'] else '✗'}")
    print(f"Skills：" + "、".join(f"{k} {'✓' if v else '✗'}" for k, v in info["skills"].items()) +
          f"；Codex $independent-review {'✓' if info['codex_skill'] else '✗'}；Codex hook {'✓' if info['codex_hook'] else '✗'}")
    print("---")
    print_state(st)
    return 0


# ---------------------------------------------------------------- pack / check-update
def do_pack(args):
    src = source_root_from_here() or (Source(args.source).root if getattr(args, "source", None) else None)
    if not src:
        raise SystemExit("pack 要在套件來源的 tools/kit.py 執行，或加 --source。")
    ver = read_text(src / "VERSION").strip()
    out_dir = Path(getattr(args, "out", None) or (src / "dist"))
    out_dir.mkdir(parents=True, exist_ok=True)
    zp = out_dir / f"{KIT_NAME}-{ver}.zip"
    include_top = ["README.md", "VERSION", "CHANGELOG.md", "core", "templates", "claude", "codex", "tools", "docs"]
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for top in include_top:
            p = src / top
            if p.is_file():
                z.write(p, f"{KIT_NAME}/{top}")
            elif p.is_dir():
                for f in p.rglob("*"):
                    if f.is_file() and "__pycache__" not in f.parts and not f.name.endswith(".pyc"):
                        z.write(f, f"{KIT_NAME}/{rel(f, src)}")
    print(f"離線包：{zp}（{zp.stat().st_size} bytes）")
    print("帶到另一台電腦後：py -3 <解壓資料夾>/tools/kit.py install --target <專案>；或直接 install --source <此 zip>")
    return 0


def do_check_update(args):
    import urllib.request
    url = getattr(args, "url", None) or os.environ.get("AI_REVIEW_KIT_UPDATE_URL")
    target = resolve_target(args)
    manifest = load_manifest(target)
    local_ver = (manifest or {}).get("kit_version") or kit_version_of(target) or kit_version_of(source_root_from_here() or target)
    print(f"本機版本：{local_ver}")
    if not url:
        print("未檢查更新：沒有設定線上來源（--url 或環境變數 AI_REVIEW_KIT_UPDATE_URL）。")
        print("離線做法：把新版資料夾或 zip 帶過來，執行 update --source <路徑> --preview 先看差異。")
        return 0
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            remote = r.read().decode("utf-8", "replace").strip().splitlines()[0].strip()
        print(f"線上版本：{remote}（{url}）")
        if remote != local_ver:
            print("有新版本。本工具不會自動更新：請取得新版來源後執行 update --source <路徑> --preview。")
        else:
            print("已是同一版本。")
    except Exception as e:
        print(f"未檢查更新（無法連線或逾時）：{e}")
        print("已安裝版本照常可用。")
    return 0


# ---------------------------------------------------------------- ignore-check（.gitignore 機密清單檢查，唯讀）
# 標準清單以套件自己的 .gitignore（防手滑、機密與金鑰、AI 工具的逐字稿與記憶）為準。
# 每條：(建議寫進 .gitignore 的那一行, 代表性的假路徑, 白話說明)。
# 判斷全交給 git（check-ignore --no-index 對假路徑、ls-files -ci --exclude 找已追蹤檔），不自己解析 gitignore 語法。
# .claude/ 整個排除會把套件裝的 .claude/skills/、.claude/settings.json 一起擋掉（那些要進版控），所以只要求 .claude/projects/。
SECRET_IGNORE_RULES = [
    (".env", ".env", "環境變數檔，常放 API 金鑰與密碼"),
    (".env.*", ".env.local", "各環境的環境變數檔（.env.local、.env.production…），內容同上"),
    ("*.local.*", "config.local.json", "本機專用設定（命名慣例 *.local.*），常含個人路徑或金鑰"),
    ("credentials*", "credentials.json", "雲端服務或程式的登入憑證檔"),
    ("secrets.*", "secrets.yaml", "秘密設定檔（命名就是放秘密的）"),
    (".claude/settings.local.json", ".claude/settings.local.json", "Claude Code 的個人本機設定，含個人權限與路徑"),
    ("*.pem", "server.pem", "憑證或私鑰檔（PEM 格式）"),
    ("*.key", "private.key", "私鑰檔"),
    ("*.pfx", "cert.pfx", "含私鑰的憑證包（Windows 常見）"),
    ("*.p12", "cert.p12", "含私鑰的憑證包（PKCS#12）"),
    ("id_rsa*", "id_rsa", "SSH 私鑰（RSA）"),
    ("id_ed25519*", "id_ed25519", "SSH 私鑰（Ed25519）"),
    (".claude/projects/", ".claude/projects/demo/notes.md",
     "Claude Code 的對話逐字稿與專案記憶；不要整個 .claude/ 排除（套件的 skills 與 settings.json 要進版控）"),
    ("*.jsonl", "logs/session.jsonl", "AI 工具的對話逐字稿常用格式（每行一筆 JSON）"),
    ("memory/", "memory/notes.md", "AI 工具的記憶資料夾，可能含個人偏好與內部資訊"),
]
IGNORE_OK_RE = re.compile(r"```ignore-ok[ \t]*\n(.*?)```", re.S)


def parse_ignore_ok(target):
    """config.md 的 ```ignore-ok 區塊：一行一條「條目 | 日期 | 理由」，# 開頭是註解。回傳 {條目: {date, reason}}。"""
    cfg = Path(target) / ".ai-review" / "config.md"
    if not cfg.exists():
        return {}
    m = IGNORE_OK_RE.search(norm_nl(read_text(cfg)))
    if not m:
        return {}
    ok = {}
    for line in m.group(1).splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = [x.strip() for x in s.split("|")]
        if not parts[0] or parts[0] in ("條目", "pattern"):
            continue
        ok[parts[0]] = {"date": parts[1] if len(parts) > 1 else "", "reason": parts[2] if len(parts) > 2 else ""}
    return ok


def _check_ignore_probes(target, probes):
    """回傳 {假路徑: (是否被排除, 來源檔, 規則)}；用 git 本身判斷（含否定規則 !…）。"""
    data = "".join(p + "\0" for p in probes).encode("utf-8")
    rc, out, err = run(["git", "-c", "core.quotePath=false", "check-ignore", "--no-index", "-v", "-n", "-z", "--stdin"],
                       cwd=target, input_text=data)
    if rc not in (0, 1):      # 0＝有符合、1＝都不符合；其他是錯誤
        raise RuntimeError("git check-ignore 失敗：" + (err.strip() or f"exit {rc}"))
    f = out.split("\0")
    res = {}
    for i in range(0, len(f) - 3, 4):
        source, _line, pattern, path = f[i], f[i + 1], f[i + 2], f[i + 3]
        res[path] = (bool(pattern) and not pattern.startswith("!"), source, pattern)
    return res


def _tracked_matching(target, pattern):
    rc, out, err = run(["git", "-c", "core.quotePath=false", "ls-files", "-z", "--cached", "--ignored",
                        f"--exclude={pattern}"], cwd=target)
    if rc != 0:
        raise RuntimeError("git ls-files 失敗：" + (err.strip() or f"exit {rc}"))
    return sorted({p for p in out.split("\0") if p})


def ignore_check(target):
    """唯讀：不改 .gitignore、不改 config.md、不寫 state、不寫 .git。"""
    target = Path(target)
    info = {"target": str(target), "git": False, "rules": [], "missing": [], "accepted": [], "tracked": [],
            "suggested_lines": [], "note": "唯讀提醒，不是關卡；不會自動修改 .gitignore。"}
    rc, out, err = run(["git", "rev-parse", "--is-inside-work-tree"], cwd=target)
    if rc == 127:
        raise RuntimeError("找不到 git 指令")
    if rc != 0 or out.strip() != "true":
        return info
    info["git"] = True
    info["gitignore_exists"] = (target / ".gitignore").exists()
    ok = parse_ignore_ok(target)
    probes = _check_ignore_probes(target, [r[1] for r in SECRET_IGNORE_RULES])
    for line, probe, why in SECRET_IGNORE_RULES:
        ignored, source, pat = probes.get(probe, (False, "", ""))
        src = source.replace("\\", "/")
        # 專案裡的 .gitignore 會印相對路徑；.git/info/exclude 與全域 excludesFile（可能也叫 .gitignore）是本機設定
        in_repo = (ignored and Path(src).name == ".gitignore" and not src.startswith((".git/", "/", "~"))
                   and not re.match(r"^[A-Za-z]:", src))
        if line in ok:
            status = "accepted"
        elif in_repo:
            status = "covered"
        elif ignored:
            status = "local-only"      # 只靠 .git/info/exclude 或全域設定排除：別人 clone 下來不受保護
        else:
            status = "missing"
        item = {"line": line, "probe": probe, "why": why, "status": status,
                "matched_by": f"{source}:{pat}" if pat else None}
        if status == "accepted":
            item["accepted"] = ok[line]
            info["accepted"].append(line)
        elif status in ("missing", "local-only"):
            info["missing"].append(line)
            info["suggested_lines"].append(line)
        info["rules"].append(item)
        if status != "accepted":
            paths = _tracked_matching(target, line)
            if paths:
                info["tracked"].append({"line": line, "count": len(paths), "paths": paths[:50]})
    return info


def print_ignore_check(info):
    print(f"目標：{info['target']}")
    if not info["git"]:
        print("不是 git 專案：沒有 .gitignore 可檢查，略過（不影響其他功能）。")
        return
    labels = {"covered": "已排除", "missing": "缺", "local-only": "只在這台電腦排除", "accepted": "已決定不排除"}
    print("| 條目 | 狀態 | 這是什麼 |")
    print("|---|---|---|")
    for r in info["rules"]:
        extra = ""
        if r["status"] == "local-only":
            extra = f"（排除設定在 {r['matched_by'].rsplit(':', 1)[0]}，別人 clone 下來不受保護）"
        elif r["status"] == "accepted":
            extra = f"（{r['accepted'].get('date') or '?'}：{r['accepted'].get('reason') or '未寫理由'}）"
        print(f"| `{r['line']}` | {labels[r['status']]}{extra} | {r['why']} |")
    n = len(info["missing"])
    print()
    if n:
        print(f"缺 {n} 條。要不要補由你決定（這只是提醒，不擋任何流程）。要補的話，.gitignore 加這幾行：")
        for line in info["suggested_lines"]:
            print(f"  {line}")
        print("這些條目在本專案如果是正常資料（例如 *.jsonl 是題庫），在 .ai-review/config.md 的 ```ignore-ok 區塊記一行「條目 | 日期 | 理由」，之後不再列為缺漏。")
    else:
        print("標準機密清單都已排除（或已決定不排除）。")
    if info["tracked"]:
        print("\n⚠️ 已經被 git 追蹤、但符合清單的檔（補 .gitignore 對它們沒用，要另外處理，例如先確認內容再 git rm --cached）：")
        for t in info["tracked"]:
            more = f"（共 {t['count']} 個，只列前 50）" if t["count"] > len(t["paths"]) else ""
            print(f"  `{t['line']}`{more}：")
            for p in t["paths"]:
                print(f"    {p}")
    print("\n（唯讀檢查：沒有修改任何檔案。）")


# ---------------------------------------------------------------- 第 6 節未驗證事項（G11，未發版）
SEP_CELL_RE = re.compile(r"^:?-{3,}:?$")


def unverified_items(target):
    """讀 config.md 第 6 節的表。新格式有「狀態」欄（未解／已解 YYYY-MM-DD）；舊格式沒有，全部算「未標狀態」。
    回傳 {"total","open","resolved","no_status","has_status_column"}；沒有 config 或沒有表回 None。只讀。"""
    cfg = Path(target) / ".ai-review" / "config.md"
    if not cfg.exists():
        return None
    m = re.search(r"^## 6\.[^\n]*\n(.*?)(?=^## |\Z)", norm_nl(read_text(cfg)), re.M | re.S)
    if not m:
        return None
    header, rows = None, []
    for line in m.group(1).splitlines():
        s = line.strip()
        if header is None:
            if s.startswith("|") and "事項" in s:
                header = [c.strip() for c in s.strip("|").split("|")]
            continue
        if not s.startswith("|"):
            break
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(SEP_CELL_RE.match(c) for c in cells if c) or not any(cells):
            continue
        rows.append(cells)
    if header is None:
        return None
    si = header.index("狀態") if "狀態" in header else None
    res = {"total": len(rows), "open": 0, "resolved": 0, "no_status": 0, "has_status_column": si is not None}
    for r in rows:
        if si is None:
            res["no_status"] += 1
        elif si < len(r) and "已解" in r[si]:
            res["resolved"] += 1
        else:
            res["open"] += 1
    return res


# ---------------------------------------------------------------- doctor：裝完還缺什麼（G10，未發版，唯讀）
LOGIN_STATUS_RE = re.compile(r"^Commands:\s*\n(?:[ \t]+\S.*\n)*?[ \t]+status\b", re.M)


def codex_login_state(codex, target):
    """先讀 `codex login --help` 確認有 status 子指令才跑 `codex login status`（只查、不觸發登入）。
    回傳 (True/False/None, 白話)。不印 status 的輸出（可能含帳號）。"""
    rc, out, err = run([codex, "login", "--help"], cwd=target, input_text=b"", timeout=30)
    if rc != 0 or not LOGIN_STATUS_RE.search(norm_nl(out)):
        return None, "這版 codex 沒有查登入狀態的指令，請自己確認已登入（終端機打 codex 看會不會要你登入）"
    rc, _, _ = run([codex, "login", "status"], cwd=target, input_text=b"", timeout=30)
    if rc == 0:
        return True, "已登入（codex login status）"
    if rc == -1:
        return None, "查登入狀態逾時，請自己確認已登入"
    return False, "未登入：在終端機執行 codex login 登入後再送審"


def find_tool(name, target):
    p = shutil.which(name)
    if p:
        return p
    for d in (Path(target) / ".venv" / "Scripts", Path(target) / ".venv" / "bin"):
        q = shutil.which(name, path=str(d))
        if q:
            return q
    return None


def doctor(target, codex_name=None):
    target = Path(target)
    items = []

    def add(key, label, ok, detail):
        items.append({"key": key, "label": label, "ok": ok, "detail": detail})

    git = shutil.which("git")
    add("git", "git", bool(git), git or "找不到 git：指紋與快照會退回較弱的檔案雜湊")
    codex = shutil.which(codex_name or "codex")
    add("codex", "Codex 指令", bool(codex),
        codex or "找不到 codex（PATH 上沒有）：裝 Codex 後才能背景送審；退路是手動開 Codex 打 $independent-review")
    if codex:
        ok, msg = codex_login_state(codex, target)
        add("codex_login", "Codex 登入", ok, msg)
        t, why = probe_mcp_server(codex, NODE_REPL_SERVER, target, os.environ.copy())
        add("node_repl", "Codex 的 node_repl", True if t else None,
            "已設定：送審時 kit 會把環境變數帶給它" if t else f"{why}：Codex 用 shell 工具跑命令，kit 不補 node_repl 設定（正常）")
    else:
        add("codex_login", "Codex 登入", None, "沒有 codex，略過")
        add("node_repl", "Codex 的 node_repl", None, "沒有 codex，略過")
    gl = find_tool("gitleaks", target)
    add("gitleaks", "gitleaks（秘密掃描）", bool(gl),
        gl or "沒裝：秘密掃描跑不了（checks 會記 skipped）；要裝請用使用者層安裝（照 gitleaks 官方說明）")
    pa = find_tool("pip-audit", target)
    add("pip_audit", "pip-audit（Python 依賴漏洞）", bool(pa) if pa else None,
        pa or "沒找到（PATH 與專案 .venv）：Python 專案才需要；不是 Python 專案可忽略")
    py, alias = real_python()
    add("python", "送審用的 Python", not alias,
        f"{py}" + ("（⚠️ 這是應用程式別名，Codex 沙箱可能啟動不了；改用實體安裝的 Python 執行 kit.py）" if alias else ""))
    proj = None
    if (target / ".ai-review").is_dir():
        init, reason = config_initialized(target)
        proj = {"installed": manifest_path(target).exists(), "kit_version": kit_version_of(target),
                "initialized": init, "init_reason": reason, "unverified": unverified_items(target)}
    return {"target": str(target), "items": items, "project": proj, "note": "唯讀檢查：沒有修改任何檔案、沒有觸發登入。"}


def print_doctor(info):
    mark = {True: "✓", False: "✗", None: "？"}
    print(f"目標：{info['target']}")
    print("| 項目 | 狀態 | 說明 |")
    print("|---|---|---|")
    for it in info["items"]:
        print(f"| {it['label']} | {mark[it['ok']]} | {it['detail']} |")
    p = info.get("project")
    if p:
        print(f"\n專案：套件 {p.get('kit_version') or '?'}；初始化：{'已完成' if p['initialized'] else '未完成（' + p['init_reason'] + '）'}")
        u = p.get("unverified")
        if u:
            if u["has_status_column"]:
                print(f"config.md 第 6 節未驗證事項：未解 {u['open']} 項、已解 {u['resolved']} 項（共 {u['total']}）")
            else:
                print(f"config.md 第 6 節未驗證事項：共 {u['total']} 項（舊格式沒有「狀態」欄，分不出已解未解；/safety-setup --refresh 會補）")
    else:
        print("\n專案：還沒安裝 ai-review-kit（沒有 .ai-review/）")
    missing = [it["label"] for it in info["items"] if it["ok"] is False]
    print("\n" + ("要補的：" + "、".join(missing) if missing else "沒有缺的必要項目。") + "（✗＝缺、？＝請自己確認或視專案而定；只提醒，不擋流程）")
    print(info["note"])


def do_doctor(args):
    target = resolve_target(args)
    if not target.is_dir():
        print(f"找不到資料夾：{target}", file=sys.stderr)
        return 1
    info = doctor(target, getattr(args, "codex", None))
    if getattr(args, "json", False):
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print_doctor(info)
    return 0


def do_ignore_check(args):
    target = resolve_target(args)
    if not target.is_dir():
        print(f"找不到資料夾：{target}", file=sys.stderr)
        return 1
    try:
        info = ignore_check(target)
    except RuntimeError as e:
        print(f"ignore-check 執行失敗：{e}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print_ignore_check(info)
    return 0


# ---------------------------------------------------------------- main
def build_parser():
    p = argparse.ArgumentParser(prog="kit.py", description="ai-review-kit 工具")
    sub = p.add_subparsers(dest="cmd")

    def common(sp, target=True, source=False):
        if target:
            sp.add_argument("--target", help="專案根目錄（預設：kit.py 所在專案或目前目錄）")
        if source:
            sp.add_argument("--source", help="套件來源：資料夾或 .zip（預設：安裝紀錄裡的來源，或本套件）")

    s = sub.add_parser("install", help="安裝到專案（已安裝則轉為 update）"); common(s, source=True)
    s.add_argument("--preview", "--dry-run", action="store_true", dest="preview", help="只顯示計畫與差異，不寫入")
    s.add_argument("--take-source", action="append", help="衝突時採用來源版的檔案（相對路徑；* 代表全部）")
    s.add_argument("--python", help='hook 用的直譯器（預設目前這個 Python；可寫 "py -3"）')
    s = sub.add_parser("update", help="更新專案內的套件（三方比對，衝突不覆蓋）"); common(s, source=True)
    s.add_argument("--preview", "--dry-run", action="store_true", dest="preview")
    s.add_argument("--take-source", action="append")
    s.add_argument("--python")
    s = sub.add_parser("relink", help="換電腦後重寫 hook 直譯器路徑與入口區塊"); common(s)
    s.add_argument("--python")
    s = sub.add_parser("restore", help="還原最近一次安裝／更新前的狀態"); common(s)
    s.add_argument("--list", action="store_true"); s.add_argument("--run"); s.add_argument("--yes", action="store_true")
    s = sub.add_parser("status", help="安裝狀態與流程狀態"); common(s, source=True); s.add_argument("--json", action="store_true")
    s = sub.add_parser("snapshot", help="建立交接快照與指紋"); common(s)
    s.add_argument("--base"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("fingerprint", help="印出目前指紋"); common(s)
    s = sub.add_parser("checks", help="列出／執行 config.md 的檢查命令"); common(s)
    s.add_argument("--run", action="store_true"); s.add_argument("--handoff"); s.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    s = sub.add_parser("state", help="推導並寫入 state.json"); common(s); s.add_argument("--json", action="store_true")
    s.add_argument("--no-write", action="store_true", help="只推導、不寫 state.json 與任何檔（配 --json 給外部程式讀）")
    s = sub.add_parser("verify", help="核對目前指紋與交接目標"); common(s); s.add_argument("--handoff")
    s = sub.add_parser("gate", help="合併／部署前關卡"); common(s)
    s = sub.add_parser("new-id", help="產生報告編號"); common(s); s.add_argument("prefix", choices=["H", "R", "F"])
    s = sub.add_parser("codex-review", help="啟動 Codex 獨立審查最新交接（紀錄寫 .ai-review/.cache/）"); common(s)
    s.add_argument("--handoff", help="交接編號（預設最新；只接受最新那份）")
    s.add_argument("--detach", action="store_true", help="丟到背景就返回（預設：等 Codex 跑完再返回）")
    s.add_argument("--print", action="store_true", dest="print_only", help="只印出將執行的命令與環境，不啟動")
    s.add_argument("--again", action="store_true", help="已有審查或看起來仍在執行時，仍要再跑一次")
    s.add_argument("--timeout", type=int, default=60, help="逾時分鐘數（預設 60）")
    s.add_argument("--no-sandbox-env", action="store_true",
                   help="不帶沙箱環境變數設定（-c shell_environment_policy／node_repl）；除錯用，回到 0.2.1 行為")
    s.add_argument("--codex", help="codex 執行檔（預設 PATH 上的 codex）")
    s = sub.add_parser("hook", help="hook 進入點"); common(s); s.add_argument("event", choices=["session-start", "stop"]); s.add_argument("--agent", default="claude")
    s = sub.add_parser("pack", help="打離線 zip"); s.add_argument("--out"); s.add_argument("--source")
    s = sub.add_parser("check-update", help="檢查線上版本（選用，不自動更新）"); common(s); s.add_argument("--url")
    s = sub.add_parser("ignore-check", help="唯讀檢查 .gitignore 有沒有排除金鑰、憑證、AI 逐字稿與記憶（只提醒，不改檔）")
    common(s); s.add_argument("--json", action="store_true")
    s = sub.add_parser("doctor", help="唯讀列出送審前還缺什麼（Codex、登入、node_repl、gitleaks、pip-audit、Python）")
    common(s); s.add_argument("--json", action="store_true"); s.add_argument("--codex", help="codex 執行檔（預設 PATH 上的 codex）")
    s = sub.add_parser("version", help="印出版本")
    return p


def main(argv=None):
    p = build_parser()
    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return 0
    if args.cmd == "version":
        print(kit_version_of(source_root_from_here() or project_root_from_here() or Path(os.getcwd())) or "?")
        return 0
    if args.cmd in ("install", "update"):
        return do_install_or_update(args, args.cmd)
    if args.cmd == "relink":
        return do_relink(args)
    if args.cmd == "restore":
        return do_restore(args)
    if args.cmd == "status":
        return do_status(args)
    if args.cmd == "snapshot":
        return do_snapshot(args)
    if args.cmd == "fingerprint":
        fp, g = fingerprint(resolve_target(args))
        print(fp + ("" if g else "  (非 git)"))
        return 0
    if args.cmd == "checks":
        return do_checks(args)
    if args.cmd == "state":
        return do_state(args)
    if args.cmd == "verify":
        return do_verify(args)
    if args.cmd == "gate":
        return do_gate(args)
    if args.cmd == "new-id":
        return do_new_id(args)
    if args.cmd == "codex-review":
        return do_codex_review(args)
    if args.cmd == "hook":
        return do_hook(args)
    if args.cmd == "pack":
        return do_pack(args)
    if args.cmd == "check-update":
        return do_check_update(args)
    if args.cmd == "ignore-check":
        return do_ignore_check(args)
    if args.cmd == "doctor":
        return do_doctor(args)
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
