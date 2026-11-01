# ai-review-kit（審印匣）— AI 開發檢查與獨立審查流程套件

[English](README.md)

> 中文代號「審印匣」：審查（審）綁在程式碼指紋（印）上，整套裝在一個可以帶著走的匣子裡。對 AI 說「裝審印匣到 <專案>」就是執行下面的 install。

> 給「用 AI 寫程式、自己能驗收功能、但看不出漏洞」的人：讓開發 AI（Claude Code）交接、讓另開的審查員獨立審查（預設是隔離的 Claude 子代理，報告標「非 Codex 審查」；大件與發版前用 Codex），狀態綁在明確版本上，程式一改舊結果就失效。
> 通用套件只有方法、範本與工具；**不含任何專案程式碼、漏洞細節、內部路徑或機密**。

版本：見 `VERSION`；變更：`CHANGELOG.md`。

## 一頁看懂

```
你                    Claude Code（開發 AI）              審查員（Claude 在背景啟動）
│ /safety-setup ───→ 盤點專案，寫 .ai-review/config.md
│ 開發、驗收功能
│ /review-ready ───→ 釘版本（指紋＋git 快照）
│                    跑 config.md 的檢查、照實記錄
│                    寫交接 H-xxx.md → 狀態「待獨立審查」
│                    選審查員：
│                      預設：kit.py claude-review --begin，
│                            派 independent-reviewer 子代理 ──→ 核對指紋、讀 diff 與完整程式碼
│                      大件（> big_change_files）或 --codex：
│                            kit.py codex-review（背景）────→ 同上，在 Codex 沙箱裡
│                    ←──────── 跑完通知，回報結論 ────── 寫審查 R-xxx.md（needs-fix / no-blocking-found）
│                    （Claude 路線：kit.py claude-review --end 收尾、推導狀態）
│ /review-fix R-xxx → 逐項修、寫 F-xxx.md、重新交接 → 狀態「待複查」→ 再背景啟動審查員複查
│ 合併前：py -3 .ai-review/kit/kit.py gate
│ 發版前（有要求時）：py -3 .ai-review/kit/kit.py gate --require-reviewer codex
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
│  ├ review-spec.md         獨立審查規範（審查員必讀）
│  └ fix-spec.md            修正規範（review-fix）
├ templates/       config.md、handoff.md、review.md、fix.md、entry-claude.md、entry-agents.md
├ claude/skills/   safety-setup、review-ready、review-fix（Claude Code Skills）
├ claude/agents/   independent-reviewer（隔離 Claude 審查員子代理，裝到專案 .claude/agents/）
├ codex/skills/    independent-review（Codex Skill，裝到專案 .agents/skills/）
├ tools/kit.py     安裝／更新／狀態／還原／打包 ＋ 專案內的快照／檢查／狀態／關卡／hook
├ tools/tests/     自動化驗證（暫存專案，383 個檢查點）
└ docs/            codex-start.md（讓 Codex 接手）、daily-usage.md（日常）、offline-setup.md（帶到不能連 GitHub 的電腦）
```

## 安裝（專案層級）

需求：Python 3.9+（純標準函式庫）、git（非 git 專案也能用，能力較弱）。Windows 用 `py -3`，macOS／Linux 用 `python3`。

```
py -3 <套件路徑>/tools/kit.py install --target <專案根目錄>
```

安裝會：
- 複製規範、範本、工具到 `<專案>/.ai-review/kit/`（專案自帶副本，換電腦不依賴中央路徑）
- 放 Skills 到 `.claude/skills/`（Claude）與 `.agents/skills/`（Codex），審查員子代理定義放到 `.claude/agents/independent-reviewer.md`
- 在 `CLAUDE.md`、`AGENTS.md` **附加**一個管理區塊（`<!-- ai-review-kit:begin … end -->`），區塊外的內容不動
- 在 `.claude/settings.json` 合併兩個 hook（SessionStart、Stop），其他設定不動；`.codex/hooks.json` 加一個 SessionStart（Codex 端需在 `/hooks` 信任後才會跑）
- `.gitignore` 加 `.ai-review/.cache/`、`.ai-review/.backup/`、`.ai-review/local.json`、`.ai-review/state.json`（已有的行不重複加）。舊版裝過、`state.json` 還在版控的專案，install／update 會提醒你自己跑 `git rm --cached .ai-review/state.json` 再存一個版本；kit 不自己動版控
- 記錄到 `.ai-review/kit-version.json`（進版控，不含本機路徑）；這台電腦的直譯器與套件來源記在 `.ai-review/local.json`（不進版控）；改動前的檔案備份到 `.ai-review/.backup/<時間>/`

然後先跑 `py -3 .ai-review/kit/kit.py doctor` 看還缺什麼（審查員定義、Codex 有沒有裝、有沒有登入、gitleaks 等），再**重開 Claude Code**、在專案根目錄開（hooks 與子代理定義都是開啟時才載入），執行 `/safety-setup`。

其他指令：

| 指令 | 用途 |
|---|---|
| `install --preview` | 只看會動哪些檔案與差異（含 hook、設定檔、`.gitignore`、紀錄檔），不寫入 |
| `update --source <資料夾或 zip> [--preview]` | 更新；三方比對（安裝時／目前／新來源），使用者改過的保留，兩邊都改的列為衝突不覆蓋，`--take-source <路徑>` 才採用來源 |
| `status` | 套件版本、來源版本、使用者改過哪些檔、hooks／Skills／入口是否就位、目前流程狀態（會重寫 `state.json`） |
| `state --json --no-write` | 只推導狀態、印 JSON，**不寫任何檔**（不寫 `state.json`、不寫 `.cache/`）；給工作根目錄的轉接 hook 等外部程式讀。欄位含 `status`、`status_label`、`initialized`、`init_reason`、`fresh`、`handoff`、`review`、`open_items`。舊版 kit 沒有這個旗標，argparse 會回 **exit 2**，呼叫端可拿 exit 2 當「舊版、略過」 |
| `doctor [--json]` | 唯讀列出送審前還缺什麼：git、Codex 在不在 PATH、有沒有登入（先確認這版 codex 有 `login status` 才查，只查不登入、不印帳號；沒有就請你自己確認）、node_repl 有沒有設定、gitleaks／pip-audit（含專案 `.venv`）、送審會用哪個實體 Python、審查員子代理（定義檔、守門 hook 的 `py` 找不找得到、`claude --version` 是否 ≥ 2.1.271）；已安裝專案另列初始化狀態與 `config.md` 第 6 節未解幾項。只提醒，exit 0 |
| `restore --yes` | 還原最近一次安裝／更新前的狀態（先列清單）；可逐次往前還原 |
| `relink [--python "py -3"]` | 換電腦後重寫 hook 的直譯器、重建 `local.json` |
| `codex-review [--detach] [--print] [--permissions <名稱>]` | 在專案裡執行：用沙箱啟動 Codex 審查最新交接（Codex 設定檔有 `default_permissions` 權限設定檔就用它、不帶 `-s`，禁止讀取清單才會生效；沒有就 `-s workspace-write`），紀錄寫 `.ai-review/.cache/codex-<H>.log`，結束寫 `.done`；找不到 codex 時 exit 3 並提示手動退路。用 `-c` 把 `AI_REVIEW_PYTHON`、`SystemDrive` 等環境變數帶進沙箱（只對這次有效，不改 Codex 設定檔；`--print` 列出全部）；審完比對工作區，審查期間多出或被改的檔會警告並寫進 `.done`，不自動刪 |
| `claude-review --begin <H> [--again]`／`claude-review --end <H> --model <別名>` | 隔離 Claude 路線（`/review-ready` 會用）。`--begin` 檢查這份交接能不能審、記下審前工作區與審前報告清單（`.ai-review/.cache/claude-<H>.running`）、清空守門心跳紀錄、印派工的四行 prompt（路徑一律正斜線）；`--end` 只收這次新寫的 `reviewer: claude-isolated` 報告（沒有就 exit 1）、審查開始前就有的報告被改刪或新報告 reviewer 不對就警告並 exit 1、守門心跳 0 筆就顯眼警告（狀態標「守門未生效」）、審前審後比對、寫 `.ai-review/.cache/claude-<H>.done`（含 `reviewer_model`、`guard_calls`）並推導狀態。加 `--print` 只印會做什麼、不寫檔 |
| `gate --require-reviewer codex` | 同 `gate`，另外要求最新有效審查是 Codex 審的（隔離 Claude 審的 exit 1），並用本機紀錄核對檔頭：有 `codex-review` 的執行紀錄（`.ai-review/.cache/codex-<H>.done`）就要指向這份報告；沒有（手動開 Codex 審）時，這份報告若出現在隔離 Claude 審查員的守門寫檔紀錄裡＝冒充 Codex，擋；否則依檔頭採信並印提示（守門沒生效時分辨不出）。`.cache` 不進版控，所以是本機關卡（CI 不要帶）；給發版前要 Codex 把關的專案 |
| `reviewer-agent --session-root <資料夾> [--python python3] [--out <檔>]` | 巢狀專案用：印出 hook 路徑改成「從對話開啟的資料夾指到本專案」的審查員定義；沒有 `py` 的電腦加 `--python python3` 換掉守門 hook 的直譯器；`--out` 才寫檔 |
| `hook review-guard` | 審查員的守門 hook（審查員子代理每次用工具前自動執行，不用手動跑） |
| `ignore-check [--json]` | 唯讀檢查 `.gitignore` 有沒有排除標準機密清單（`.env`、金鑰與憑證、`.claude/projects/` 對話逐字稿、`*.jsonl`、`memory/` 等 15 條），每條用多個代表路徑（典型檔名、萬用字元的其他變體、子資料夾裡的同名檔）交給 git 判斷，只排除一部分的列「只排除了一部分」並舉例；並列出已被 git 追蹤、但符合清單的檔（只列路徑、不印內容）。`/safety-setup` 盤點時會跑，缺的記進 `config.md` 第 6 節。只提醒、不是關卡，**不會改 `.gitignore`**；缺漏也 exit 0。本專案是正常資料的條目（例如題庫 `*.jsonl`）在 `config.md` 的 ```` ```ignore-ok ```` 區塊記「條目 \| 日期 \| 理由」，之後不再列為缺漏 |
| `pack` | 打離線 zip 到 `dist/` |
| `check-update --url <VERSION 檔網址>` | 只查版本號，不自動更新；沒網路就如實說「未檢查更新」 |

## 日常只要記住

| 時機 | 做什麼 |
|---|---|
| 新專案一次 | `/safety-setup` |
| 一個變更做完 | `/review-ready` |
| 要獨立審查 | 不用做事：`/review-ready` 最後會自己選審查員、在背景啟動，跑完回報 |
| 這次要送 Codex（例如發版前） | `/review-ready --codex`。想自己開 Codex 見 `docs/codex-start.md` |
| 審查說要修 | `/review-fix R-編號` |
| 合併／部署前 | `py -3 .ai-review/kit/kit.py gate`（發版前有要求時：`gate --require-reviewer codex`） |
| 想看狀態 | `py -3 .ai-review/kit/kit.py status` |
| 裝完或換電腦，想知道還缺什麼 | `py -3 .ai-review/kit/kit.py doctor` |

## 兩種審查員

| 審查員 | 什麼時候 | 報告 `reviewer` | 怎麼啟動 |
|---|---|---|---|
| 隔離 Claude（`independent-reviewer` 子代理） | 預設 | `claude-isolated`，狀態後面加「（非 Codex 審查）」 | `/review-ready` 跑 `claude-review --begin`、派子代理（模型與開發 AI 不同：開發是 opus 就派 fable，否則派 opus）、再跑 `claude-review --end` |
| Codex | 大件（改動檔數超過 `config.md` 第 5 節 `big_change_files`，預設 10）、發版前、或帶 `--codex` | `codex` | `/review-ready` 背景跑 `kit.py codex-review`；或你自己開 Codex |

- 隔離審查員是另開的：不帶開發脈絡、不讀 CLAUDE.md、沒有記憶、與開發 AI 不同模型，走你的 Claude 訂閱額度。一般子代理不算審查員，skill 也規定 Claude 不准拿來冒充。
- **守門 hook（`review-guard`）**：審查員定義讓它每次用工具前先跑 `kit.py hook review-guard`（hook 設 `onFailure: block`）。只准新寫 `.ai-review/reviews/R-*.md`（要先有 `claude-review --begin` 的開審紀錄；Write 只能建新檔、審查開始前就有的報告不准改）；指令只准 git 唯讀（`diff`、`show`、`log`、`status`、`ls-files`、`rev-parse`、`cat-file`；會執行簽章程式的 `--show-signature` 擋）、`kit.py` 的 `verify`／`new-id R`／`state --no-write`（只有 state 可帶 `--json`）／`checks --run`（用 `py -3`〔Windows〕或 `python3` 執行），以及 `config.md` 第 4 節的檢查命令原文（逐字相同）；串接與轉向（`&&`、`;`、`|`、`>`、`<`、反引號、`$(`、換行）一律擋；路徑一律用雙引號或正斜線。子代理交回報的 `SubagentHandback` 放行。被擋的事審查員會寫進報告的「沒做的事」。
- **守門要生效的前提**：①專案資料夾在 Claude Code 開過一次並**接受信任**——沒信任時 Claude Code 會略過子代理定義裡的 hooks、不報錯（2026-11-01 實測）；②Claude Code **2.1.271 以上**（`omitClaudeMd` 要這版，舊版默默忽略）；③找得到 hook 的直譯器 `py`（沒有就用 `reviewer-agent --python python3`）；④Claude Code **開在專案根目錄**（開在子資料夾時守門找不到 kit.py，審查員的工具全被擋）。`doctor` 會查 ②③、提醒 ①④。
- **怎麼知道守門有生效**：審查員第 0 步先跑 `echo guard-canary`（應被擋），沒被擋就停止審查、回報「守門未生效」；守門每次被呼叫都記一行心跳（`.ai-review/.cache/claude-<H>.guard.jsonl`：時間、工具名、放行／擋下，放行的寫檔另記 R 檔名），`claude-review --end` 看到 0 筆就顯眼警告、狀態標「（非 Codex 審查；守門未生效）」。
- **守門管不到的**：它只管 Claude 的工具層。放行的程式（例如檢查命令啟動的 Python 子程序）自己寫檔，守門看不到；這部分靠 `claude-review --end` 的審前審後比對事後抓出來（印警告、寫進紀錄，不自動刪）。git 設定（例如 `core.fsmonitor`）也可能讓唯讀 git 指令叫外部程式，審查員改不到這些設定。
- 要求發版前一定要 Codex 審：`config.md` 第 5 節寫「發版前 gate 需 Codex 審查：是」，發版前跑 `gate --require-reviewer codex`（本機關卡；`codex-review` 送審或手動開 Codex 審都可以，隔離 Claude 審查員冒充 Codex 寫的報告會被守門紀錄認出來）。
- 同一份交接 Codex 判「需修正」之後，隔離 Claude 的「未發現阻擋問題」不會蓋掉它（較弱的審查員不能推翻）；重審請用 Codex 或修正後重新交接。`gate` 會印審查歷程。
- `/review-ready --claude` 強制走隔離 Claude，`--codex` 強制送 Codex。

### 巢狀專案

Claude Code 只從「對話開啟的資料夾」往上找 `.claude/agents/`，hook 裡的 `${CLAUDE_PROJECT_DIR}` 也是那個資料夾。對話開在專案的上層資料夾時，專案內的審查員定義**不會被載入**，`/review-ready` 會讓你選退路（改送 Codex，或在專案資料夾開對話）。想在上層資料夾也用隔離審查員：跑 `kit.py reviewer-agent --session-root <上層資料夾>`，把印出的定義放到 `<上層資料夾>/.claude/agents/independent-reviewer.md`，重開 Claude Code。同一個資料夾只能放一份，所以一個上層資料夾底下只有一個巢狀專案能這樣用。

## 更新套件（跨電腦）

- 中央版本放在你自己的地方（例如這個資料夾的 git repo、或 `pack` 出來的 zip）。
- 每個專案記錄自己用的版本（`.ai-review/kit-version.json`）。
- 更新一律 `update --source … --preview` 先看，再 `update --source …`。不會覆寫整個 `.claude/` 或 `.codex/`，不會碰登入資訊、對話紀錄、金鑰、專案資料。
- 不能連 GitHub 的電腦：帶 zip 過去，`install --source <zip>`；工具不會上傳任何東西。見 `docs/offline-setup.md`。

## 限制（誠實版）

- hook 只做機械判斷（版本、指紋是否相符、有沒有未結案、審查員的白名單）。它不掃描程式碼、不呼叫另一個 AI、不能擋住 push 或部署。
- 隔離 Claude 審查員換了模型、不帶開發脈絡，但終究還是 Claude，守門也只管 Claude 自己的工具層（見「兩種審查員」）。報告與狀態標「非 Codex 審查」讓你分得出來；大件與發版前用 Codex。
- 審查員子代理定義是 Claude Code 開啟時載入：第一次安裝、或更新後才多出這個檔，要重開 Claude Code。巢狀專案不用 `reviewer-agent` 就完全找不到它。
- `omitClaudeMd` 只略過開場載入的 CLAUDE.md：審查員讀到子資料夾（巢狀時含專案本身）的檔時，那層的 CLAUDE.md 仍會附進審查員對話；kit 會在 `.done` 記下是哪幾份（`claude_md_exposure`）。
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
- Windows 上用 Codex 權限設定檔（mxc 沙箱，Codex 0.162.1，2026-10-18 實測）：禁止清單只擋「讀檔案內容」，不擋「列出資料夾」——被禁的資料夾裡有哪些檔名、子資料夾名，審查 AI 仍看得到。
- 指紋在 CI 與本機可能因 CRLF 正規化設定不同而不一致（`core.autocrlf` 混用時）；遇到就以本機為準並在 CI 停用 gate。

## 驗證

```
py -3 tools/tests/test_kit.py
```
在暫存資料夾建立多個測試專案，覆蓋：新專案安裝、既有 CLAUDE.md／AGENTS.md／settings.json 保留、重複安裝不重複插入、預覽列出實裝會寫的每一個檔、指紋不寫進專案 git 物件庫、`codex-review` 的命令形狀／環境／拒絕條件／帶進沙箱的 `-c` 設定／權限設定檔（有 `default_permissions` 時不帶 `-s`、拒絕 danger 類名稱）／審後多出檔案的警告（假 codex）、更新衝突不覆蓋、還原、程式變更使審查過期、hook 不迴圈不重複、檢查命令結果分明、離線 zip 安裝、非 git 專案、無網路時的 check-update、`ignore-check`（全缺／全有／部分缺／否定規則／只在本機排除／已追蹤檔只列路徑／標記不排除後不再列／唯讀／非 git）、「已初始化」要 meta＋檢查命令、審後看得到 .gitignore 排除位置多出的東西、`state --no-write` 不寫任何檔、第 6 節狀態欄新舊格式、`doctor`（假 codex／假 PATH，不觸發登入、唯讀）、`state.json` 不進版控（只提醒、不動 index）。測試資料夾不會自動刪除。
