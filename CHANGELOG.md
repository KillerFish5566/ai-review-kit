# 變更紀錄

版本規則：patch＝修 bug 不改行為；minor＝加功能且舊專案資料相容；major＝專案資料需轉換或使用方式改變。
每次發版：改 `VERSION`、在這裡加一段、`kit.py pack` 重打離線包。

## 0.3.0 — 2026-10-11

修正：Codex 審查時沙箱裡的命令拿不到 `SystemDrive`、`AI_REVIEW_PYTHON` 等環境變數（2026-10-11 vocab-rpg 與秘書兩個專案都發生）。Windows 元件因此把快取寫到專案根目錄一個字面名稱的 `%SystemDrive%\` 資料夾（約 1 MB），指紋漂移、複查判 invalid（vocab-rpg R-20261011-1136）；`py` 與 gitleaks 也起不來。舊專案資料相容，`update` 即可。

- 根因（查證見 T-0047 結果檔）：該機 Codex 的 shell 工具在沙箱起不來（`setup refresh had errors`），Codex 改用 node_repl 工具（Codex 桌面版裝的 MCP 伺服器）跑命令；MCP 伺服器只拿到 Codex 的預設環境變數清單，node_repl 再只把 `NODE_REPL_UNTRUSTED_ENV_ALLOWLIST` 列的名稱交給模型程式碼 → 沒有 `SystemDrive`、沒有 `AI_REVIEW_PYTHON`。
- `codex-review` 啟動時用 `-c` 把變數帶進沙箱（只對這次審查有效，不改 Codex 設定檔）：
  - shell 工具：`shell_environment_policy.set.<名稱>`（官方設定）——`AI_REVIEW_PYTHON`，Windows 另加 `SYSTEMDRIVE`、`SYSTEMROOT`、`WINDIR`、`PROGRAMDATA`。
  - node_repl（先用 `codex mcp get node_repl --json` 確認有設定才補；沒設定的伺服器硬補會讓 Codex 報 invalid transport 起不來）：`mcp_servers.node_repl.env.<名稱>`（官方設定）＋把名稱加進它的放行名單（原值保留在前；只放行系統位置變數與 `AI_REVIEW_PYTHON`，不放帳號或金鑰類）。放行名單的作用取自本機 node_repl 執行檔內的程式碼，不是官方文件，Codex 改版可能失效。
  - `--print` 列出帶進去的全部 `-c` 與 node_repl 狀態；`--no-sandbox-env` 可退回不帶設定。
- 審後比對：`codex-review` 審前審後各取一次工作區清單（與指紋同一套收檔規則），審查期間多出、改掉或刪掉的檔會印警告，寫進 `.done`（`workspace_changes`、`fingerprint_drift`、`warnings`）與紀錄檔末尾。專案根目錄新出現字面名稱的 `%變數%` 資料夾（即使被 `.gitignore` 排除）也會提醒（`literal_env_dirs`）。**不自動刪任何檔**。
- `$independent-review` 與 `review-spec.md`：`AI_REVIEW_PYTHON` 改寫成「會帶進沙箱」（原寫「一定有」，實際 node_repl 路徑拿不到）；`py` 也起不來時用專案虛擬環境的直譯器並寫進限制；暫存檔不准留在專案資料夾；指紋不符時先看 `git status --porcelain` 有沒有審查期間才出現的檔並寫進報告。
- `workflow.md`、README、`daily-usage.md` 同步。
- 指紋演算法與值不變（只把收檔步驟抽成共用函式）。
- 測試 92 → 106 項（T19 命令帶 `-c` 設定且是合法 TOML、node_repl 有無設定兩種、`--no-sandbox-env`；T20 審查期間多出檔案會警告、寫進 `.done` 與紀錄、不刪；T20b 被忽略的字面資料夾仍提醒但不算指紋漂移）。

## 0.2.1 — 2026-10-04

修正：Codex 每次審查都先用 `py` 失敗一次才改用 `AI_REVIEW_PYTHON`（vocab-rpg 09-27～09-28 的 17 次背景審查次次如此；結果正確，只是多一步）。

- `$independent-review` 與 `review-spec.md` 改為「`AI_REVIEW_PYTHON` 有值就直接用，沒有才用 `py -3`」；`review-spec.md` 原本沒提這個退路。
- 只改說明文字，`kit.py` 行為不變。

## 0.2.0 — 2026-09-26

新功能：交接後由開發 AI 在背景啟動 Codex 獨立審查（第二台電腦 2026-09-24 提出、09-26 定案）。舊專案資料相容，`update` 即可。

- 新指令 `kit.py codex-review`：對最新交接執行 `codex exec -C <專案> -s workspace-write "$independent-review <H-id>"`。
  - TMP／TEMP 指到 `.ai-review/.cache/tmp`（Codex 沙箱不准寫系統暫存）。
  - 環境變數 `AI_REVIEW_PYTHON` 帶實體直譯器路徑：Windows 的 `py` 是 WindowsApps 應用程式別名，Codex 沙箱帳號啟動不了（實測 CreateProcess 錯誤 2）。
  - 模型照 Codex 設定檔（不加 `-m`）；永遠不用 `--dangerously-bypass-approvals-and-sandbox`。
  - 紀錄寫 `.ai-review/.cache/codex-<H-id>.log`，結束寫 `.done`（exit、審查編號、結論），執行中有 `.running` 標記防重複啟動。
  - 預設等 Codex 跑完才返回（給 Claude Code 背景執行、結束自動通知）；`--detach` 丟背景立刻返回；`--print` 只看命令；找不到 codex 時 exit 3 並提示手動退路。
  - 拒絕：交接後程式又改過、不是最新交接、已有獨立審查（`--again` 才重跑）。
- 指紋計算改成新物件寫進暫存物件庫（原物件庫只讀），Codex 沙箱不准寫 `.git` 也能核對指紋；不必再給 Codex `.git` 的寫入權。`snapshot` 照舊寫進專案 git 以建立快照參照。指紋值不變。
- `/review-ready` 最後兩步改為背景啟動審查與收結果；`/review-fix`、`$independent-review`（沙箱內直譯器退路）、`workflow.md`、`handoff-spec.md`、README、`daily-usage.md`、`codex-start.md`（改為退路）同步。
- 測試 81 → 92 項（T17 指紋不寫物件庫、T18 用假 codex 驗證命令形狀／環境變數／紀錄／拒絕條件）。

## 0.1.2 — 2026-09-26

修正：`install／update --preview` 漏列設定與紀錄檔（第二台電腦 2026-09-21 回報）。

- 預覽原本只列套件檔與入口區塊（20 項），實裝另外會寫 `.claude/settings.json`（SessionStart、Stop hook）、`.codex/hooks.json`、`.gitignore`、三個 `.gitkeep` 與 `kit-version.json`／`local.json`／`state.json`。現在另起一張「設定與紀錄檔」表全部列出，兩個 hook 設定檔附安裝前後差異。
- 這些檔的內容改為在預覽前就算好，實裝照同一份內容寫入，預覽與實裝不會對不上。
- 測試 78 → 81 項（新增 T16：預覽不寫檔、實裝寫入的每個檔都出現在預覽、hook 差異有顯示）。

## 0.1.1 — 2026-09-19

修正：安裝後進版控的檔案會帶出本機路徑（含 Windows 使用者名稱）。

- 直譯器與套件來源路徑改存 `.ai-review/local.json`（自動加進 `.gitignore`），`kit-version.json` 不再記這兩項。
- hook 預設直譯器改用 PATH 上的通用命令（Windows `py -3`、其他 `python3`），不再寫 `sys.executable` 的絕對路徑；`--python` 指定的值照用，路徑在使用者資料夾內會提出警告。
- Claude Code hook 的 kit.py 路徑改寫 `${CLAUDE_PROJECT_DIR}/.ai-review/kit/kit.py`（實測 exec 形式會展開），不再寫專案的絕對路徑。
- 從 0.1.0 升級：舊欄位自動搬走；0.1.0 自動記下的絕對直譯器路徑不沿用，改用通用命令。
- 從 zip 安裝時記住的來源改為 zip 檔本身（原本記到會被清掉的暫存資料夾）。
- `.gitignore` 補新行時接在既有區段後面，不再重複標題。
- 測試 67 → 78 項（T12 補一項、新增 T13～T15）。

## 0.1.0 — 2026-09-18

第一版。

- 核心規範五份（`core/`）：總覽與狀態推導、安全檢查清單（對應 OWASP ASVS 5.0.0）、交接規範、獨立審查規範、修正規範。
- 範本七份（`templates/`）：專案設定、交接／審查／修正報告、Claude 與 Codex 入口區塊。
- Claude Code Skills 三個：`/safety-setup`、`/review-ready`、`/review-fix`。
- Codex Skill 一個：`$independent-review`。
- 工具 `tools/kit.py`（純 Python 標準函式庫）：install／update／status／restore／pack／check-update，以及專案內的 snapshot／checks／state／verify／gate／hook。
- hooks：Claude Code 的 SessionStart（顯示版本、初始化、狀態、未結案）與 Stop（交接過期提醒，每個指紋只提醒一次，永不阻擋）；Codex 的 SessionStart（同內容，未實測）。
- 狀態由報告檔頭與程式碼指紋推導，`.ai-review/` 不計入指紋，所以寫報告不會讓狀態過期。
