# AI 開發檢查與獨立審查流程（總覽）

> 本檔是流程的唯一規範。Claude 的 `CLAUDE.md`、Codex 的 `AGENTS.md` 只放入口規則，細節都在這裡。
> 套件版本見同資料夾的 `VERSION`。

## 0. 三句話

1. 開發 AI（通常是 Claude Code）做完**一個能獨立理解的變更**後，執行「交接」：把被審內容釘死成一個版本指紋、跑完檢查、寫成交接報告。
2. **另一個審查員**讀真正的 diff 與程式碼，寫獨立審查報告：預設是**隔離的 Claude 子代理**（`independent-reviewer`：另開、不帶開發脈絡、不讀 CLAUDE.md 與記憶、與開發 AI 不同模型、受守門 hook 限制；報告標「非 Codex 審查」）；**大件（改動檔數超過 `big_change_files`）與發版前用 Codex**（`kit.py codex-review` 在背景啟動，或使用者手動開 Codex）。兩條路線都由 `/review-ready` 選。開發 AI 的自查永遠不算獨立審查。
3. 狀態不是誰宣告的，是由「交接／審查／修正」三種報告加上目前程式碼的指紋**推導**出來的。程式碼一變，舊結果就失效。

## 1. 角色

| 角色 | 做什麼 | 不做什麼 |
|---|---|---|
| 開發 AI（Claude Code） | 實作、跑檢查、寫交接報告、選審查員並在背景啟動審查（派隔離 Claude 審查員或啟動 Codex）、依審查報告修正 | 不宣告「獨立審查通過」、不改審查報告、不用一般子代理冒充審查員 |
| 審查 AI：預設隔離 Claude（`independent-reviewer` 子代理，`reviewer: claude-isolated`）；發版前與大件用 Codex（`reviewer: codex`） | 讀 diff 與完整相關程式碼、寫審查報告 | 預設不改實作；隔離 Claude 只能寫 `.ai-review/reviews/R-*.md`（守門 hook 擋其他寫入與白名單外指令） |
| 使用者 | 驗收功能、決定要不要修與要不要合併（Codex 退路時自己開 Codex） | 不需要自己看懂漏洞 |

## 2. 專案裡的檔案

```
<專案>/
├ CLAUDE.md                  入口規則（管理區塊，安裝工具維護）
├ AGENTS.md                  入口規則（同上，給 Codex）
├ .ai-review/                本流程的專案資料（要 commit，除了 .cache、.backup、local.json、state.json）
│  ├ kit/                    通用規範與工具的副本（本檔在此；kit.py 也在此）
│  ├ config.md               專案專屬設定：風險、既有檢查、檢查命令、關卡規則（/safety-setup 產生）
│  ├ state.json              本機推導的狀態，不提交（追蹤資料，不是安全證明；gate 與 CI 都現場推導，不讀提交的版本）
│  ├ handoffs/H-*.md         交接報告（開發 AI 寫）
│  ├ reviews/R-*.md          獨立審查報告（審查 AI 寫）
│  ├ fixes/F-*.md            修正報告（開發 AI 寫）
│  ├ kit-version.json        安裝紀錄：套件版本、檔案雜湊、備份（不含本機路徑）
│  ├ local.json              這台電腦的直譯器與套件來源（不 commit）
│  ├ .cache/                 hook 的暫存（不 commit）
│  └ .backup/                安裝／更新前的備份（不 commit）
├ .claude/skills/            /safety-setup、/review-ready、/review-fix
├ .claude/agents/            independent-reviewer.md（隔離 Claude 審查員；第一次裝好要重開 Claude Code 才載入）
├ .claude/settings.json      hooks（SessionStart、Stop 兩個提醒）
├ .agents/skills/            Codex 用的 $independent-review
└ .codex/hooks.json          Codex 的 SessionStart 提醒（選用）
```

## 3. 狀態（五種）

| 狀態 | 代碼 | 意思 |
|---|---|---|
| 尚未準備 | `not-ready` | 沒有交接，或交接後程式碼又變了（舊結果全部失效） |
| 待獨立審查 | `pending-review` | 有有效交接，還沒有對應的獨立審查 |
| 需修正 | `needs-fix` | 獨立審查找到阻擋級問題 |
| 待複查 | `pending-recheck` | 已依審查修正並重新交接，等第二次審查 |
| 本次範圍內未發現阻擋問題 | `no-blocking-found` | 獨立審查在**這個指紋**的範圍內沒找到阻擋問題 |

推導規則（`kit.py state` 就是照這個算）：

```
沒有 config.md 或沒有任何交接           → not-ready
最新交接 H 的 target ≠ 目前指紋          → not-ready（註明：H 已過期）
H 沒有對應審查（審查的 target 必須 = H.target）
    H 是修正後重交（recheck_of 有值）     → pending-recheck
    否則                                  → pending-review
最新對應審查 R 的 verdict = needs-fix    → needs-fix
R.verdict = no-blocking-found            → no-blocking-found
R.reviewer 是開發 AI 自己（self/claude） → 不算，視同沒有審查
R.reviewer = claude-isolated              → 算獨立審查；status、state 與 SessionStart 提醒在結論後加「（非 Codex 審查）」
```

狀態只看 `reviewer` 與 `verdict`；`reviewer_model`、`reviewer_isolation` 是給人看的紀錄。發版前要求 Codex 審查的專案另用 `kit.py gate --require-reviewer codex` 把關（見第 7 節）。同一份交接有多份審查時照編號後者為準，例外：**較弱的審查員不能推翻較強審查員的「需修正」**——Codex 判 `needs-fix` 之後，隔離 Claude 的結論不取代它（狀態維持需修正並註明；重審請用 Codex 或修正後重新交接）。同種審查員重審照舊後者為準，Codex 可以取代隔離 Claude。`gate` 會印出這份交接的審查歷程。

## 4. 版本綁定（為什麼不會「永遠過期」也不會「沿用舊結果」）

- **指紋（fingerprint）**＝目前工作目錄內容的 git tree 雜湊，**不含 `.ai-review/`**。
  - 含未提交與未追蹤（但不含 .gitignore 排除的）檔案，所以沒有東西被靜默排除。
  - 交接時另外建一個 git 參照 `refs/ai-review/<交接編號>` 指向這個內容的快照，事後可以 `git diff` 回去看。這個參照不會被 push。
  - 排除 `.ai-review/` 的原因：審查報告、修正報告本身是「審查產物」，不是「被審內容」；寫報告不能讓狀態過期。
- 非 git 專案：指紋改用檔案內容雜湊，沒有快照參照，能力較弱（會在報告裡標明）。
- 每份交接、審查、修正報告的開頭都寫死 `target: <指紋>`。審查報告的 target 對不上交接的 target，就不算數。

## 5. 一次完整循環

```
/safety-setup（每個專案一次）
   → kit.py ignore-check（唯讀：.gitignore 少排除的機密條目記進第 6 節，要不要補由使用者決定）
   → .ai-review/config.md
開發 … 做完一個完整變更
/review-ready
   → kit.py snapshot（指紋＋快照參照）
   → kit.py checks --run（逐條執行 config.md 的檢查命令，照實記錄）
   → handoffs/H-xxx.md
   → 狀態：待獨立審查
   → 選審查員：改動檔數 > big_change_files（沒填當 10）或帶 --codex → Codex；否則隔離 Claude（--claude 強制）
隔離 Claude 路線（預設）：
   → kit.py claude-review --begin <H>（登記開審、記審前工作目錄）
   → 派 independent-reviewer 子代理（與開發 AI 不同模型、背景執行、守門 hook 限制）
   → 審查員核對指紋、讀 diff 與完整程式碼 → reviews/R-xxx.md（reviewer: claude-isolated）
   → kit.py claude-review --end <H> --model <別名>（審後比對、寫紀錄、推導狀態）
Codex 路線（大件、發版前）：
   → 開發 AI 背景執行 kit.py codex-review（退路：使用者開 Codex，輸入 $independent-review，見 docs/codex-start.md）
   → Codex（工作區沙箱）核對指紋、讀 diff 與完整程式碼 → reviews/R-xxx.md（reviewer: codex）
   → 狀態：需修正 ／ 本次範圍內未發現阻擋問題（隔離 Claude 審的加註「非 Codex 審查」）
若需修正：/review-fix
   → 逐項處理、針對性驗證 → fixes/F-xxx.md
   → 重新 snapshot、重新交接（recheck_of 指向 R-xxx）
   → 狀態：待複查 → 再審一次（/review-ready 的最後幾步，同樣依大小選審查員）
合併／部署前：kit.py gate（發版前要求 Codex 的專案：kit.py gate --require-reviewer codex）
```

## 6. 硬規則

1. 沒執行、失敗、或環境不足的檢查，只能記「未執行／失敗／環境不足」，不能記「通過」。
2. 開發 AI 的自查不是獨立審查；審查報告 `reviewer` 欄不得是開發 AI 本身所在的對話或程序。另開、不帶開發脈絡、不讀 CLAUDE.md 與記憶、與開發 AI 不同模型、受守門 hook 限制的 Claude 子代理（`independent-reviewer`，`reviewer: claude-isolated`）算獨立審查，報告與狀態標「非 Codex 審查」；一般子代理不算。
3. 審查 AI 預設只寫報告，不改實作。
4. 審查後任何程式碼變更都讓狀態回到 `not-ready`，要重新交接。
5. 更新本流程時，不得移除或放寬專案既有的安全要求（config.md 第 3 節「既有機制」只能增不能減，除非使用者明確決定）。
6. 狀態檔與報告裡的「通過」文字不是安全證明；證明是「哪個指紋、誰審、看了什麼、怎麼查」。
7. hook 只做機械判斷（版本、指紋是否相符、有沒有未結案），不掃描程式碼、不呼叫另一個 AI、不宣稱能擋住所有 push 或部署。

## 7. 常用指令（都在專案根目錄執行）

```
py -3 .ai-review/kit/kit.py status        看版本、初始化、狀態、指紋是否相符
py -3 .ai-review/kit/kit.py gate          合併／部署前的關卡（只有 no-blocking-found 且指紋相符才 exit 0）；
                                          另外用本機紀錄核對（不限 --require-reviewer）：最新有效審查是隔離 Claude、
                                          而收尾紀錄（.cache/claude-<H>.done）記守門心跳 0 筆 → 不成立（加 --allow-no-guard
                                          才放行並印提醒）；本機沒有 .done（換電腦、CI）→ 不擋，印「守門有沒有生效無法核對」；
                                          報告出現在隔離 Claude 審查員的守門寫檔紀錄、檔頭卻不是 claude-isolated＝冒充，一律擋
py -3 .ai-review/kit/kit.py gate --require-reviewer codex
                                          發版前關卡：另外要求最新有效審查是 Codex 審的（隔離 Claude 審的 exit 1），
                                          並用本機紀錄核對檔頭：有 codex-review 的執行紀錄（.cache/codex-<H>.done）
                                          就要指向這份報告；沒有（手動開 Codex 審）時，這份報告出現在隔離 Claude
                                          審查員的守門寫檔紀錄（.cache/claude-*.guard.jsonl）＝冒充 Codex，擋；
                                          否則依檔頭採信並印提示（守門沒生效時分辨不出）。
                                          .cache 不進版控，所以這是本機關卡（CI 不要帶這個參數）
py -3 .ai-review/kit/kit.py snapshot      建交接快照（通常由 /review-ready 呼叫）
py -3 .ai-review/kit/kit.py checks --run  執行 config.md 的檢查命令並記錄（子程序的 PYTHONIOENCODING 沒設才補 utf-8、
                                          已設照原值，補了會印一行；Windows 主控台是 cp1252／cp950 時，Python 寫的
                                          檢查印 ✓ 或 emoji 才不會崩。審查員直接跑 config 第 4 節的命令（不經 kit）時
                                          不受這條保護）
py -3 .ai-review/kit/kit.py verify        核對目前指紋與最新交接
py -3 .ai-review/kit/kit.py state         重新推導 state.json（加 --json --no-write：只印、不寫任何檔）
py -3 .ai-review/kit/kit.py doctor        送審前還缺什麼（審查員定義、倉庫外定義是否同步、Codex、登入、gitleaks…；唯讀）
py -3 .ai-review/kit/kit.py ignore-check  .gitignore 有沒有排除機密與 AI 逐字稿（唯讀）
py -3 .ai-review/kit/kit.py codex-review  啟動 Codex 審查最新交接（等跑完；--detach 丟背景、--print 只看命令）
py -3 .ai-review/kit/kit.py claude-review --begin <H-id> [--again]
                                          隔離 Claude 審查開審：檢查能不能審、寫 .cache/claude-<H>.running（審前工作區清單、
                                          審前報告清單）、清空守門心跳 .cache/claude-<H>.guard.jsonl、印派工的四行 prompt；
                                          倉庫外定義不同步時印 ⚠️（不擋）並在 .running／.done 記 agent_stale: true
py -3 .ai-review/kit/kit.py claude-review --end <H-id> --model <別名>
                                          收尾：只收這次新寫的 reviewer: claude-isolated 報告（沒有 → exit 1）；審查開始前就有的
                                          報告被改／刪、或新報告 reviewer 不對 → 警告並 exit 1；守門心跳 0 筆 → 顯眼警告、
                                          狀態標「守門未生效」；審後比對、寫 .cache/claude-<H>.done（含 guard_calls）、推導狀態；
                                          可能被附進審查員對話的 CLAUDE.md 清單非空 → .done 加 nested、claude_md_exposure，
                                          isolation 的 omitClaudeMd 改標 omitClaudeMd:startup-only，畫面印一行提醒
                                          （兩者加 --print：只印會做什麼，不寫檔）
py -3 .ai-review/kit/kit.py reviewer-agent --session-root <對話資料夾> [--python python3] [--out <檔>]
                                          巢狀專案用：印出改好 hook 路徑的審查員定義（--out 才寫檔）；
                                          沒有 py 的電腦加 --python python3（--session-root 填專案本身）
py -3 .ai-review/kit/kit.py hook review-guard
                                          守門 hook 進入點（審查員子代理每次用工具前自動執行，不用手動跑）
```

macOS／Linux 把 `py -3` 換成 `python3`。

**守門 hook（review-guard）**：裝在 `independent-reviewer` 子代理定義的 `hooks.PreToolUse`（加 `onFailure: block`），只對審查員生效，擋下時 exit 2 並印白話原因。
- **生效前提**（kit 查不到的部分要自己確認，`kit.py doctor` 會提醒）：
  - 專案資料夾要在 Claude Code 開過一次並**接受信任**：沒信任時 Claude Code 會略過子代理定義裡的 hooks、不報錯，審查員完全不受限（2026-11-01 實測）。
  - Claude Code **2.1.271 以上**（`omitClaudeMd` 要這版；舊版默默忽略，審查員會讀 CLAUDE.md）。`omitClaudeMd` 只略過開場載入的 CLAUDE.md：審查員讀到子資料夾（巢狀時含專案本身）的檔時，那層的 CLAUDE.md 仍會附進審查員對話（Claude Code 官方文件寫明的行為），kit 會在 `.done` 記下（`claude_md_exposure`），審查員定義也規定只當資料、寫進報告限制。
  - 找得到 hook 寫的直譯器（預設 `py`）：找不到時 hook 起不來、工具照跑。沒有 `py` 的電腦用 `reviewer-agent --python python3` 產生改好的定義，或手動把 `command` 改成 `python3`、`args` 拿掉 `"-3"`。
  - Claude Code **開在專案根目錄**（或 `reviewer-agent --session-root` 指定的上層資料夾）：開在專案的子資料夾時 hook 路徑找不到 kit.py，審查員的工具全被擋（安全但不能用）。
- **確認有生效**：審查員第 0 步先跑 `echo guard-canary`，應被擋；沒被擋就不審、回報「守門未生效，停止審查」。守門每次被呼叫都在 `.ai-review/.cache/claude-<H>.guard.jsonl` 記一行（時間、工具名、放行／擋下、`nested`（hook 環境變數 `CLAUDE_PROJECT_DIR` 有值且不是專案根＝true，只記布林）；放行的寫檔另記 R 檔名；不記指令、檔案內容與路徑）；`claude-review --end` 看到 0 筆就顯眼警告，`.done` 的 `isolation` 寫 `subagent;omitClaudeMd;no-memory;guard-not-observed`，狀態標「（非 Codex 審查；守門未生效）」。
- 寫檔（Edit／Write）只准 `.ai-review/reviews/R-*.md`，而且要先有開審紀錄（`claude-review --begin` 寫的 `.running`；沒有就擋所有寫入）：Write 只能建還不存在的檔，Edit 只能改審查開始後新寫的報告（審查開始前就有的報告不准改）。
- 指令（Bash）只准：`git [-C <專案>] diff|show|log|status|ls-files|rev-parse|cat-file …`；`py -3`（Windows）或 `python3` 執行本專案 `.ai-review/kit/kit.py` 的 `verify`、`new-id R`（只准 R）、`state --no-write`（只有 state 可帶 `--json`）、`checks --run`（都可加 `--target <專案>`）；`config.md` 第 4 節登記的檢查命令**逐字相同**（多一個參數就擋）。不准 `&&`、`;`、`|`、`>`、`<`、反引號、`$(`、換行等串接與轉向。路徑一律用雙引號或正斜線（反斜線沒加引號會被 bash 吃掉）。
- 子代理交最後回報的工具（`SubagentHandback`）放行；其他白名單外的工具一律擋。
- 審查員跑 `checks --run` 不帶 `--handoff`（帶了會蓋掉開發端交接時的檢查紀錄，守門也會擋）。
- **限制**：守門只管 Claude 的工具層。白名單內的程式（例如檢查命令啟動的 Python 子程序）自己開檔寫檔它看不到，這部分靠 `claude-review --end` 的審前審後比對抓出來（印警告、寫進 `.done`，不自動刪）。git 的設定（例如 `core.fsmonitor`、`gpg.program`）也可能讓唯讀的 git 指令叫外部程式；審查員改不到 git 設定（`-c`、環境變數、設定檔都擋），會執行簽章程式的 `--show-signature` 也擋。
- **巢狀專案**：子代理定義只從「對話開啟的資料夾」往上找 `.claude/agents/`，hook 路徑裡的 `${CLAUDE_PROJECT_DIR}` 也是對話資料夾。對話開在專案的上層資料夾時，專案內的審查員定義不會被載入；用 `reviewer-agent --session-root <對話資料夾>` 產生改好路徑的定義，放到對話資料夾的 `.claude/agents/`（同一個對話資料夾只能放一份 `independent-reviewer`）。新放的定義要重開 Claude Code 才載入。
  - 巢狀時 `omitClaudeMd` 略過的是對話資料夾的 CLAUDE.md；審查員一讀專案裡的檔，**專案本身的 CLAUDE.md**（與子資料夾的）就會被附進對話。`claude-review --end` 會算「可能被附進來的 CLAUDE.md」（巢狀時專案根那份＋子資料夾裡的；不含 `.ai-review/`、`.git/` 與指紋略過的資料夾），記在 `.done` 的 `claude_md_exposure`，`isolation` 標 `omitClaudeMd:startup-only`。
  - 放在對話資料夾的那份定義不在倉庫、不受指紋綁定、`kit update` 不會更新它。`doctor`、`kit update`、`claude-review --begin` 會從專案的上層一路往上找 `<上層>/.claude/agents/independent-reviewer.md`，用專案內版本重算應有內容比對：不同步時 `doctor` 列 ✗、`update` 與 `--begin` 印 ⚠️（`--begin` 另在 `.running`／`.done` 記 `agent_stale: true`），都附修法指令 `kit.py reviewer-agent --target <專案> --session-root <上層> --out <那份檔> --force`，跑完重開 Claude Code。kit 不自己寫專案外的檔（那可能是使用者的設定資料夾）。

`codex-review` 的固定做法：`codex exec -C <專案> <沙箱權限> "$independent-review <H-id>"`；沙箱權限：使用者的 Codex 設定檔（`CODEX_HOME` 或 `~/.codex/config.toml`）最上層有 `default_permissions`（權限設定檔，可設禁止讀取清單）→ 帶 `-c default_permissions="<名稱>"`、**不帶 `-s`**（帶了 `-s` Codex 就改走舊式設定、權限設定檔整組不生效）；沒有 → `-s workspace-write`；`--permissions <名稱>` 可指定，名稱含 danger 一律拒絕；用了哪一種印在畫面並寫進 `.done` 的 `permissions`；TMP／TEMP 指 `.ai-review/.cache/tmp`（Codex 沙箱不准寫系統暫存）；環境變數 `AI_REVIEW_PYTHON` 給沙箱用的實體直譯器（Windows 的 `py` 是應用程式別名，沙箱啟動不了）；這個變數與 `SystemDrive`、`SystemRoot` 等用 `-c` 帶進沙箱：shell 工具走官方的 `shell_environment_policy.set`，Codex 改用 node_repl 工具時走 `mcp_servers.node_repl.env` 並加進它的放行名單（只對這次審查有效，不改 Codex 設定檔；少了 `SystemDrive` 時 Windows 元件會在專案根目錄建字面名稱的 `%SystemDrive%\` 資料夾，打壞指紋）；不加 `-m`（模型照 Codex 設定檔）、永遠不用 `--dangerously-bypass-approvals-and-sandbox`；紀錄寫 `.ai-review/.cache/codex-<H-id>.log`，結束寫 `.done`（exit、審查編號、結論）；審前審後比對工作區（與指紋同一套收檔規則），審查期間多出、改掉或刪掉的檔會印警告並寫進 `.done`（`workspace_changes`、`fingerprint_drift`）與紀錄；另外比對專案根目錄與第一層資料夾的清單（**包括 .gitignore 排除的**，`.ai-review/.cache/` 除外），多出來的寫進 `new_ignored_entries` 並警告（不算指紋）；**不自動刪**——先看是什麼再決定。指紋計算的新物件寫在暫存物件庫，所以 Codex 不需要 `.git` 的寫入權。
