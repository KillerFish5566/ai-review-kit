# 變更紀錄

版本規則：patch＝修 bug 不改行為；minor＝加功能且舊專案資料相容；major＝專案資料需轉換或使用方式改變。
每次發版：改 `VERSION`、在這裡加一段、`kit.py pack` 重打離線包。

## 未發版

修正：`ignore-check` 單一探針漏判（Codex 審查 R-20261011-1654-1，medium）。`.gitignore` 只寫 `credentials.*` 時，`credentials*` 會被判成「已排除」，但 `credentials-prod.json` 其實沒被排除——因為每條只用一個代表路徑（`credentials.json`）問 git。舊專案資料相容。

- 每條標準條目改用多個代表路徑：規則字面最典型的檔、萬用字元展開的其他變體、放在子資料夾的同名檔（抓只寫在根目錄的錨定寫法 `/memory/`）。例：`credentials*` → `credentials`、`credentials.json`、`credentials-prod.json`、`credentials_backup.yml`、`sub/credentials.txt`。每個代表路徑都會被標準那一行本身排除，照建議補上後一定判「已排除」。仍然只交給 git 判斷（一次 `check-ignore --no-index --stdin`），不在磁碟建假檔。
- 判定：全部被專案 `.gitignore` 排除 → `covered`；全部沒排除 → `missing`；有的排除、有的完全沒排除 → 新狀態 **`partial`**（白話「只排除了一部分」，舉出沒排除的例子），和 `missing` 一樣算進 `missing` 與 `suggested_lines`（建議補的仍是標準那一行）；全部都有排除、但其中有只靠本機設定（`.git/info/exclude`、全域）→ `local-only`；`accepted` 照舊。
- `--json` 每條多 `probes`（每個代表路徑的 `path`、`ignored`、`in_repo`、`matched_by`）、`uncovered_probes`、`local_only_probes`；舊欄位 `probe`（第一個代表路徑）、`matched_by`（第一個有符合的規則）保留。
- 行為變化：以前判 `missing` 的條目，現在可能判 `partial`（例如 `*.jsonl` 加了 `!session.jsonl`）；以前判 `covered` 的，現在可能判 `partial`（例如只寫 `credentials.*`、或錨定寫法 `/memory/`）。`/safety-setup` 對 `partial` 的寫法同 `missing`，事項後面加沒排除的例子。
- 測試 161 → 169 項（T28：只寫 `credentials.*` 判 partial 並列出 `credentials-prod.json`、寫 `credentials*` 判 covered、錨定 `/memory/` 判 partial、`credentials*`＋`!credentials-prod.json` 判 partial、`--json` 新欄位與舊欄位相容、白話輸出舉例）；T21 的否定規則題期望值由 missing 改為 partial（理由同上）。

## 0.4.0 — 2026-10-11

新功能：`.gitignore` 機密清單檢查（10-11 推送前連續三個倉庫的推送檢查表都卡在「.gitignore 沒排除金鑰、憑證、對話紀錄、記憶」，每次人工補）。只提醒、不改使用者專案的 `.gitignore`；`install` 也不塞清單（那是使用者專案的版控設定，超出審查套件範圍）。舊專案資料相容。

- `kit.py ignore-check [--json]`：唯讀。內建 15 條標準清單（以套件自己的 `.gitignore` 為準：`.env`、`.env.*`、`*.local.*`、`credentials*`、`secrets.*`、`.claude/settings.local.json`、`*.pem`、`*.key`、`*.pfx`、`*.p12`、`id_rsa*`、`id_ed25519*`、`.claude/projects/`、`*.jsonl`、`memory/`），每條附白話說明。
  - 判斷交給 git：每條造一個代表性的假路徑跑 `git check-ignore --no-index`（含否定規則 `!…`）；已追蹤的符合檔用 `git ls-files --cached --ignored --exclude=<條目>`，**只列路徑、不讀不印內容**。
  - 只靠 `.git/info/exclude` 或全域排除設定擋住的，列「只在這台電腦排除」，也算要補（別人 clone 下來不受保護）。
  - 清單要求的是 `.claude/projects/`，不是整個 `.claude/`：套件裝的 `.claude/skills/`、`.claude/settings.json` 要進版控。
  - 本專案是正常資料的條目（例如題庫 `*.jsonl`）：在 `config.md` 第 6 節的 ```` ```ignore-ok ```` 區塊記「條目 | 日期 | 理由」，之後改列「已決定不排除」，已追蹤清單也不再列它。
  - 缺漏 exit 0（提醒，不是關卡；不影響 `gate` 與狀態）；資料夾不存在、git 執行失敗才非 0；不是 git 專案印說明、exit 0。不寫 state、不改任何檔、不影響指紋。
- `/safety-setup`：盤點第 1 步改跑 `ignore-check`；缺的條目與已追蹤的符合檔逐條寫進 `config.md` 第 6 節（`--refresh` 不重複加）；回報時加一句白話提醒，並把「要不要補 `.gitignore`」列進「你需要決定的事」。明寫不自動改 `.gitignore`、不自動 `git rm --cached`。
- `templates/config.md`：第 6 節加 ```` ```ignore-ok ```` 區塊與說明。已安裝專案的 `config.md` 是專案專屬，`update` 不動它；`/safety-setup --refresh` 會照範本補上區塊。
- README、`workflow.md`、`security-checklist.md`、`daily-usage.md` 同步。
- 「已初始化」改嚴：`config.md` 存在**且** meta 區塊有填（不是範本的 `{{…}}`）**且**第 4 節至少一條檢查命令。之前只要有 config.md 就算，秘書專案因此在還沒做 `/safety-setup` 時就送審（T-0048 盤點 G7）。不符時 `state`／`status`／開場 hook 印白話原因（例：「config.md 只有部分內容…，請先執行 /safety-setup」），state.json 多一個 `init_reason`。`/review-ready` 前置改成看 `state --json` 的 `initialized`，沒完成就停下請使用者先跑 `/safety-setup`；`/safety-setup` 寫明第 4 節至少一條。vocab-rpg、秘書現有 config 判斷結果仍是已初始化（唯讀驗證）。
- 審後比對補盲點（G5）：`codex-review` 審前審後另外比對「專案根目錄與第一層資料夾清單（**包括 .gitignore 排除的**）」，審查期間多出來、又沒被 `workspace_changes`／字面環境變數資料夾涵蓋的，寫進 `.done` 的 `new_ignored_entries` 並印警告。`.ai-review/.cache/` 底下是預期變動，不列。只警告、不算指紋、不刪任何檔。（例：審查把暫存寫進被排除的個人資料夾 `data/review-…`，以前看不到。）
- 秘密掃描範例加 `--redact`（G9）：`safety-setup` 與 `security-checklist.md` 改成 `gitleaks detect --no-banner --redact`，掃到金鑰時原文不會進 `.cache/checks-*.json` 與會 commit 的交接報告。已安裝專案的 config.md 第 4 節不會被自動改，要自己補。
- `kit.py doctor [--json]`（G10）：唯讀列出送審前還缺什麼——git、Codex 在不在 PATH、Codex 登入（先讀 `codex login --help` 確認有 `status` 子指令才跑 `codex login status`，只看 exit code、不印輸出（可能含帳號）、不觸發登入；沒有就請使用者自己確認）、node_repl 有沒有設定（沿用 `codex mcp get node_repl --json`）、gitleaks／pip-audit（PATH 與專案 `.venv`）、送審會用哪個實體 Python；已安裝專案另列初始化狀態與第 6 節未解幾項。缺的只提示，exit 0。install 結尾改成「先跑 doctor 看還缺什麼，再開 Claude Code 跑 /safety-setup」。
- 第 6 節「未驗證事項」加「狀態」欄（G11）：範本表格多一欄（`未解`／`已解 YYYY-MM-DD`），已解不刪列。`/safety-setup --refresh` 會補欄、逐列標狀態、把 meta 的 `kit_version` 更新成目前版本。kit 讀第 6 節（`doctor` 用）相容舊格式：沒有狀態欄的舊表全部算「未標狀態」，不猜已解。
- `state --no-write`（配 `--json`）：只推導、印 JSON，**不寫任何檔**（state.json、.cache 都不寫），給工作根目錄的轉接 hook 讀（使用者 Q158 選了使用者層轉接 hook）。舊版 kit 沒有這個旗標，argparse 回 exit 2，呼叫端可當「舊版、略過」。
- `state.json` 不進版控（使用者 Q159 甲）：install／update 的 `.gitignore` 區段多一行 `.ai-review/state.json`（照既有逐行去重，手動加過的不重複）。專案裡 `state.json` 仍被 git 追蹤時，install／update 結尾提醒自己跑 `git rm --cached .ai-review/state.json` 再存一個版本；**kit 不自己動版控**。`gate` 與 CI 範例都是現場推導狀態，不依賴提交的 state.json。
- 文件誠實化（G13、G2）：README「限制」與 `daily-usage.md` 寫明「開場狀態與收工提醒只有在專案資料夾直接開 Claude Code 才會跑」「審查紀錄跟著 git 分支走，換分支看到的是那個分支的狀態」。`workflow.md` 把 state.json 標成本機推導、不提交，常用指令加 `doctor`、`ignore-check`、`state --no-write`。
- 測試 106 → 161 項：T21 ignore-check 18 項（全缺、全有、部分缺、否定規則、只在本機排除、已追蹤檔只列路徑不印內容、標記不排除後不再列、唯讀、非 git、`--json` 欄位、失敗才非 0）；T22 已初始化判斷 6 項；T23 排除位置多出東西 4 項；T24 `state --no-write` 5 項（含 .ai-review 每個檔位元組不變、不認得旗標 exit 2）；T25 第 6 節新舊格式 4 項；T26 doctor 12 項（假 codex 已登入／未登入／沒有 status 子指令／沒 node_repl、假 PATH、不印帳號、不走登入流程、唯讀）；T27 state.json 不進版控 6 項（新裝有該行、已有不重複、舊專案補行、仍被追蹤只提醒、index 位元組不變）。

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
