# ai-review-kit（審印匣）— AI 開發檢查與獨立審查流程套件

[English](README.md)

> 中文代號「審印匣」：審查（審）綁在程式碼指紋（印）上，整套裝在一個可以帶著走的匣子裡。對 AI 說「裝審印匣到 <專案>」就是執行下面的 install。

> 給「用 AI 寫程式、自己能驗收功能、但看不出漏洞」的人：讓開發 AI（Claude Code）交接、讓另一個 AI（Codex）獨立審查，狀態綁在明確版本上，程式一改舊結果就失效。
> 通用套件只有方法、範本與工具；**不含任何專案程式碼、漏洞細節、內部路徑或機密**。

版本：見 `VERSION`；變更：`CHANGELOG.md`。

## 一頁看懂

```
你                    Claude Code（開發 AI）              Codex（審查 AI，Claude 在背景啟動）
│ /safety-setup ───→ 盤點專案，寫 .ai-review/config.md
│ 開發、驗收功能
│ /review-ready ───→ 釘版本（指紋＋git 快照）
│                    跑 config.md 的檢查、照實記錄
│                    寫交接 H-xxx.md → 狀態「待獨立審查」
│                    kit.py codex-review（背景）─────────→ 核對指紋、讀 diff 與完整程式碼
│                    ←──────── 跑完通知，回報結論 ────── 寫審查 R-xxx.md（needs-fix / no-blocking-found）
│ /review-fix R-xxx → 逐項修、寫 F-xxx.md、重新交接 → 狀態「待複查」→ 再背景啟動 Codex 複查
│ 合併前：py -3 .ai-review/kit/kit.py gate
```

五種狀態：尚未準備 → 待獨立審查 → 需修正 → 待複查 → 本次範圍內未發現阻擋問題。全部由報告檔頭＋目前程式碼指紋**推導**，不是誰宣告的。細節：`core/workflow.md`。

## 套件內容

```
ai-review-kit/
├ README.md、VERSION、CHANGELOG.md
├ core/            通用規範（工具中立的 Markdown）
│  ├ workflow.md            總覽、狀態推導、版本綁定、硬規則
│  ├ security-checklist.md  對應 OWASP ASVS 5.0.0 的檢查清單與設計檢查六題
│  ├ handoff-spec.md        交接規範（review-ready）
│  ├ review-spec.md         獨立審查規範（Codex 必讀）
│  └ fix-spec.md            修正規範（review-fix）
├ templates/       config.md、handoff.md、review.md、fix.md、entry-claude.md、entry-agents.md
├ claude/skills/   safety-setup、review-ready、review-fix（Claude Code Skills）
├ codex/skills/    independent-review（Codex Skill，裝到專案 .agents/skills/）
├ tools/kit.py     安裝／更新／狀態／還原／打包 ＋ 專案內的快照／檢查／狀態／關卡／hook
├ tools/tests/     自動化驗證（暫存專案，169 個檢查點）
└ docs/            codex-start.md（讓 Codex 接手）、daily-usage.md（日常）、offline-setup.md（帶到不能連 GitHub 的電腦）
```

## 安裝（專案層級）

需求：Python 3.9+（純標準函式庫）、git（非 git 專案也能用，能力較弱）。Windows 用 `py -3`，macOS／Linux 用 `python3`。

```
py -3 <套件路徑>/tools/kit.py install --target <專案根目錄>
```

安裝會：
- 複製規範、範本、工具到 `<專案>/.ai-review/kit/`（專案自帶副本，換電腦不依賴中央路徑）
- 放 Skills 到 `.claude/skills/`（Claude）與 `.agents/skills/`（Codex）
- 在 `CLAUDE.md`、`AGENTS.md` **附加**一個管理區塊（`<!-- ai-review-kit:begin … end -->`），區塊外的內容不動
- 在 `.claude/settings.json` 合併兩個 hook（SessionStart、Stop），其他設定不動；`.codex/hooks.json` 加一個 SessionStart（Codex 端需在 `/hooks` 信任後才會跑）
- `.gitignore` 加 `.ai-review/.cache/`、`.ai-review/.backup/`、`.ai-review/local.json`、`.ai-review/state.json`（已有的行不重複加）。舊版裝過、`state.json` 還在版控的專案，install／update 會提醒你自己跑 `git rm --cached .ai-review/state.json` 再存一個版本；kit 不自己動版控
- 記錄到 `.ai-review/kit-version.json`（進版控，不含本機路徑）；這台電腦的直譯器與套件來源記在 `.ai-review/local.json`（不進版控）；改動前的檔案備份到 `.ai-review/.backup/<時間>/`

然後先跑 `py -3 .ai-review/kit/kit.py doctor` 看還缺什麼（Codex 有沒有裝、有沒有登入、gitleaks 等），再在專案根目錄開 Claude Code（hooks 要重開才載入），執行 `/safety-setup`。

其他指令：

| 指令 | 用途 |
|---|---|
| `install --preview` | 只看會動哪些檔案與差異（含 hook、設定檔、`.gitignore`、紀錄檔），不寫入 |
| `update --source <資料夾或 zip> [--preview]` | 更新；三方比對（安裝時／目前／新來源），使用者改過的保留，兩邊都改的列為衝突不覆蓋，`--take-source <路徑>` 才採用來源 |
| `status` | 套件版本、來源版本、使用者改過哪些檔、hooks／Skills／入口是否就位、目前流程狀態（會重寫 `state.json`） |
| `state --json --no-write` | 只推導狀態、印 JSON，**不寫任何檔**（不寫 `state.json`、不寫 `.cache/`）；給工作根目錄的轉接 hook 等外部程式讀。欄位含 `status`、`status_label`、`initialized`、`init_reason`、`fresh`、`handoff`、`review`、`open_items`。舊版 kit 沒有這個旗標，argparse 會回 **exit 2**，呼叫端可拿 exit 2 當「舊版、略過」 |
| `doctor [--json]` | 唯讀列出送審前還缺什麼：git、Codex 在不在 PATH、有沒有登入（先確認這版 codex 有 `login status` 才查，只查不登入、不印帳號；沒有就請你自己確認）、node_repl 有沒有設定、gitleaks／pip-audit（含專案 `.venv`）、送審會用哪個實體 Python；已安裝專案另列初始化狀態與 `config.md` 第 6 節未解幾項。只提醒，exit 0 |
| `restore --yes` | 還原最近一次安裝／更新前的狀態（先列清單）；可逐次往前還原 |
| `relink [--python "py -3"]` | 換電腦後重寫 hook 的直譯器、重建 `local.json` |
| `codex-review [--detach] [--print]` | 在專案裡執行：用工作區沙箱啟動 Codex 審查最新交接，紀錄寫 `.ai-review/.cache/codex-<H>.log`，結束寫 `.done`；找不到 codex 時 exit 3 並提示手動退路。用 `-c` 把 `AI_REVIEW_PYTHON`、`SystemDrive` 等環境變數帶進沙箱（只對這次有效，不改 Codex 設定檔；`--print` 列出全部）；審完比對工作區，審查期間多出或被改的檔會警告並寫進 `.done`，不自動刪 |
| `ignore-check [--json]` | 唯讀檢查 `.gitignore` 有沒有排除標準機密清單（`.env`、金鑰與憑證、`.claude/projects/` 對話逐字稿、`*.jsonl`、`memory/` 等 15 條），每條用多個代表路徑（典型檔名、萬用字元的其他變體、子資料夾裡的同名檔）交給 git 判斷，只排除一部分的列「只排除了一部分」並舉例；並列出已被 git 追蹤、但符合清單的檔（只列路徑、不印內容）。`/safety-setup` 盤點時會跑，缺的記進 `config.md` 第 6 節。只提醒、不是關卡，**不會改 `.gitignore`**；缺漏也 exit 0。本專案是正常資料的條目（例如題庫 `*.jsonl`）在 `config.md` 的 ```` ```ignore-ok ```` 區塊記「條目 \| 日期 \| 理由」，之後不再列為缺漏 |
| `pack` | 打離線 zip 到 `dist/` |
| `check-update --url <VERSION 檔網址>` | 只查版本號，不自動更新；沒網路就如實說「未檢查更新」 |

## 日常只要記住

| 時機 | 做什麼 |
|---|---|
| 新專案一次 | `/safety-setup` |
| 一個變更做完 | `/review-ready` |
| 要獨立審查 | 不用做事：`/review-ready` 最後會在背景啟動 Codex，跑完回報。想自己開就說一聲（`docs/codex-start.md`） |
| 審查說要修 | `/review-fix R-編號` |
| 合併／部署前 | `py -3 .ai-review/kit/kit.py gate` |
| 想看狀態 | `py -3 .ai-review/kit/kit.py status` |
| 裝完或換電腦，想知道還缺什麼 | `py -3 .ai-review/kit/kit.py doctor` |

## 更新套件（跨電腦）

- 中央版本放在你自己的地方（例如這個資料夾的 git repo、或 `pack` 出來的 zip）。
- 每個專案記錄自己用的版本（`.ai-review/kit-version.json`）。
- 更新一律 `update --source … --preview` 先看，再 `update --source …`。不會覆寫整個 `.claude/` 或 `.codex/`，不會碰登入資訊、對話紀錄、金鑰、專案資料。
- 不能連 GitHub 的電腦：帶 zip 過去，`install --source <zip>`；工具不會上傳任何東西。見 `docs/offline-setup.md`。

## 限制（誠實版）

- hook 只做機械判斷（版本、指紋是否相符、有沒有未結案）。它不掃描程式碼、不呼叫另一個 AI、不能擋住 push 或部署。
- 開場狀態與收工提醒（hook）只有在**專案資料夾直接開 Claude Code** 才會跑（hook 寫在專案自己的 `.claude/settings.json`）；從上層資料夾開的對話不會自動提醒，要自己跑 `kit.py state` 或 `/review-ready`。
- 審查紀錄（`.ai-review/handoffs`、`reviews`、`fixes`）跟著 git 分支走：換分支後看到的是那個分支的狀態，不是審查不見了。
- `gate` 是本地檢查，可以被略過。要強制，得在 GitHub 設 branch protection 並讓 CI 跑 gate（`templates/ci/github-actions-gate.yml` 是範例，尚未在真實 repo 驗證）。
- 狀態檔與報告裡的「通過」文字不是安全證明；證明是「哪個指紋、誰審、看了什麼、怎麼查」。
- 非 git 專案沒有快照參照，指紋改用檔案雜湊。
- Codex 的 `$independent-review` Skill 已在實際專案用 `codex exec` 背景跑過多輪（2026-09-25 起）；Codex 端的 SessionStart hook 仍未驗證。自動化測試用假的 codex 驗證命令形狀與紀錄，不會真的呼叫 Codex。
- 手動開 Codex 只在專案根目錄開：在使用者資料夾或上層資料夾開過，Windows 版沙箱群組可能對整個資料夾樹留下「可修改」權限並記進信任清單，關掉後仍在（2026-10-11 實測；細節與收回方式見 `docs/codex-start.md`）。`codex-review` 一律 `-C <專案>`，不受影響。
- `codex-review` 依賴本機的 Codex 登入與額度；額度不足時不會有審查報告，要照 `config.md` 第 6 節記下哪份交接尚未審。
- Windows 上 Codex 的 shell 工具起不來時（沙箱「setup refresh had errors」），Codex 會改用 node_repl 工具跑命令；kit 對 node_repl 補的放行名單（`NODE_REPL_UNTRUSTED_ENV_ALLOWLIST`）取自本機 node_repl 執行檔內的程式碼，不是官方文件，Codex 改版可能失效。失效時審後比對會警告；`--no-sandbox-env` 可退回不帶設定。
- Windows 上 Codex 沙箱裡 gitleaks 可能起不來（啟動被拒，spawn EPERM；2026-10-12 實測，用完整路徑也一樣）。這時審查 AI 沒有自己的機密掃描結果，只有開發端交接時跑的那一次；審查報告會註明「沒有獨立機密掃描」。
- 指紋在 CI 與本機可能因 CRLF 正規化設定不同而不一致（`core.autocrlf` 混用時）；遇到就以本機為準並在 CI 停用 gate。

## 驗證

```
py -3 tools/tests/test_kit.py
```
在暫存資料夾建立多個測試專案，覆蓋：新專案安裝、既有 CLAUDE.md／AGENTS.md／settings.json 保留、重複安裝不重複插入、預覽列出實裝會寫的每一個檔、指紋不寫進專案 git 物件庫、`codex-review` 的命令形狀／環境／拒絕條件／帶進沙箱的 `-c` 設定／審後多出檔案的警告（假 codex）、更新衝突不覆蓋、還原、程式變更使審查過期、hook 不迴圈不重複、檢查命令結果分明、離線 zip 安裝、非 git 專案、無網路時的 check-update、`ignore-check`（全缺／全有／部分缺／否定規則／只在本機排除／已追蹤檔只列路徑／標記不排除後不再列／唯讀／非 git）、「已初始化」要 meta＋檢查命令、審後看得到 .gitignore 排除位置多出的東西、`state --no-write` 不寫任何檔、第 6 節狀態欄新舊格式、`doctor`（假 codex／假 PATH，不觸發登入、唯讀）、`state.json` 不進版控（只提醒、不動 index）。測試資料夾不會自動刪除。
