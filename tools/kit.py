#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ai-review-kit 工具（純 Python 標準函式庫，Python 3.9+）

兩種身分、同一支檔案：
  A. 放在套件來源 `ai-review-kit/tools/kit.py`  → 管理指令：install / update / restore / status / pack / check-update
  B. 被安裝到專案 `<專案>/.ai-review/kit/kit.py` → 專案指令：status / snapshot / checks / state / verify / gate / new-id / hook / relink
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
GITIGNORE_LINES = ["# ai-review-kit（本機資料，不提交）", ".ai-review/.cache/", ".ai-review/.backup/", ".ai-review/local.json"]
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
    print(f"\n完成（{mode}）：寫入 {len(r.created)} 個新檔、修改 {len(r.backed_up)} 個既有檔（備份在 {rel(r.backup_dir, target) if r.backup_dir.exists() else '無'}）。")
    if conflicts:
        print("有衝突項目未處理，見上方清單。")
    print("下一步：在專案根目錄開 Claude Code，執行 /safety-setup（每個專案一次）。hooks 要重開 Claude Code 才載入。")
    src.cleanup()
    return 0


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


def git_tree_fingerprint(target):
    with tempfile.TemporaryDirectory() as td:
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(Path(td) / "index")
        rc, _, err = run(["git", "read-tree", "--empty"], cwd=target, env=env)
        if rc != 0:
            raise RuntimeError("git read-tree 失敗：" + err.strip())
        rc, _, err = run(["git", "add", "-A", "--", ".", ":(exclude).ai-review"], cwd=target, env=env)
        if rc != 0:
            raise RuntimeError("git add 失敗：" + err.strip())
        rc, out, err = run(["git", "write-tree"], cwd=target, env=env)
        if rc != 0:
            raise RuntimeError("git write-tree 失敗：" + err.strip())
        return out.strip()


def file_fingerprint(target):
    h = hashlib.sha256()
    for root, dirs, files in os.walk(target):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        for f in sorted(files):
            p = Path(root) / f
            try:
                h.update(rel(p, target).encode("utf-8") + b"\0" + sha256_file(p).encode() + b"\n")
            except Exception:
                continue
    return "sha256:" + h.hexdigest()[:40]


def fingerprint(target):
    if is_git_root(target):
        return git_tree_fingerprint(target), True
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
    fp, is_git = fingerprint(target)
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
    initialized = (target / ".ai-review" / "config.md").exists()
    installed = manifest_path(target).exists()
    cur_fp, is_git = (fingerprint(target) if with_fp else (None, None))
    hs = reports(target, "handoffs")
    rs = reports(target, "reviews")
    fs = reports(target, "fixes")
    st = {"status": "not-ready", "initialized": initialized, "installed": installed, "git": is_git,
          "current_fingerprint": cur_fp, "fresh": None, "handoff": None, "review": None, "fix": None,
          "notes": [], "open_items": []}
    if not initialized:
        st["notes"].append("尚未初始化：沒有 .ai-review/config.md，請執行 /safety-setup")
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
        st["open_items"].append(f"交接 {H.get('id')} 等待獨立審查（Codex：$independent-review）")
    elif status == "pending-recheck":
        st["open_items"].append(f"交接 {H.get('id')} 為修正後重交（回應 {H.get('recheck_of')}），等待複查")
    elif status == "needs-fix":
        st["open_items"].append(f"審查 {R.get('id')} 判定需修正（阻擋級 {R.get('blocking') or '?'} 項），請執行 /review-fix {R.get('id')}")
    elif status == "not-ready" and hs:
        st["open_items"].append(f"交接 {H.get('id')} 已過期（原狀態：{STATUS_LABELS[bound_status]}），完成變更後請重新 /review-ready")
    return st


def derive_and_write_state(target, quiet=False):
    st = derive_state(target)
    out = {
        "_note": "追蹤資料，由 kit.py state 依報告檔頭與目前指紋推導；本檔內任何文字都不是安全證明。",
        "kit_version": kit_version_of(target),
        "derived_at": now_str(),
        "status": st["status"],
        "status_label": STATUS_LABELS[st["status"]],
    }
    out.update({k: st[k] for k in ("initialized", "git", "current_fingerprint", "fresh", "handoff", "review", "fix", "notes", "open_items")})
    dump_json(target / ".ai-review" / "state.json", out)
    if not quiet:
        print_state(out)
    return out


def print_state(out):
    print(f"狀態：{out['status_label']}（{out['status']}）")
    print(f"初始化：{'已完成' if out.get('initialized') else '未完成（請執行 /safety-setup）'}")
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
    lines.append("- 初始化：" + ("已完成" if st["initialized"] else "未完成 → 請執行 /safety-setup"))
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
    s = sub.add_parser("verify", help="核對目前指紋與交接目標"); common(s); s.add_argument("--handoff")
    s = sub.add_parser("gate", help="合併／部署前關卡"); common(s)
    s = sub.add_parser("new-id", help="產生報告編號"); common(s); s.add_argument("prefix", choices=["H", "R", "F"])
    s = sub.add_parser("hook", help="hook 進入點"); common(s); s.add_argument("event", choices=["session-start", "stop"]); s.add_argument("--agent", default="claude")
    s = sub.add_parser("pack", help="打離線 zip"); s.add_argument("--out"); s.add_argument("--source")
    s = sub.add_parser("check-update", help="檢查線上版本（選用，不自動更新）"); common(s); s.add_argument("--url")
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
    if args.cmd == "hook":
        return do_hook(args)
    if args.cmd == "pack":
        return do_pack(args)
    if args.cmd == "check-update":
        return do_check_update(args)
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
