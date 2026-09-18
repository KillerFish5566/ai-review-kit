# AI 開發檢查與獨立審查流程（總覽）

> 本檔是流程的唯一規範。Claude 的 `CLAUDE.md`、Codex 的 `AGENTS.md` 只放入口規則，細節都在這裡。
> 套件版本見同資料夾的 `VERSION`。

## 0. 三句話

1. 開發 AI（通常是 Claude Code）做完**一個能獨立理解的變更**後，執行「交接」：把被審內容釘死成一個版本指紋、跑完檢查、寫成交接報告。
2. **另一個 AI**（Codex，由使用者手動啟動）讀真正的 diff 與程式碼，寫獨立審查報告。開發 AI 的自查永遠不算獨立審查。
3. 狀態不是誰宣告的，是由「交接／審查／修正」三種報告加上目前程式碼的指紋**推導**出來的。程式碼一變，舊結果就失效。

## 1. 角色

| 角色 | 做什麼 | 不做什麼 |
|---|---|---|
| 開發 AI（Claude Code） | 實作、跑檢查、寫交接報告、依審查報告修正 | 不宣告「獨立審查通過」 |
| 審查 AI（Codex） | 讀 diff 與完整相關程式碼、寫審查報告 | 預設不改實作 |
| 使用者 | 驗收功能、啟動 Codex、決定要不要合併 | 不需要自己看懂漏洞 |

## 2. 專案裡的檔案

```
<專案>/
├ CLAUDE.md                  入口規則（管理區塊，安裝工具維護）
├ AGENTS.md                  入口規則（同上，給 Codex）
├ .ai-review/                本流程的專案資料（要 commit，除了 .cache 與 .backup）
│  ├ kit/                    通用規範與工具的副本（本檔在此；kit.py 也在此）
│  ├ config.md               專案專屬設定：風險、既有檢查、檢查命令、關卡規則（/safety-setup 產生）
│  ├ state.json              推導出來的狀態（追蹤資料，不是安全證明）
│  ├ handoffs/H-*.md         交接報告（開發 AI 寫）
│  ├ reviews/R-*.md          獨立審查報告（審查 AI 寫）
│  ├ fixes/F-*.md            修正報告（開發 AI 寫）
│  ├ kit-version.json        安裝紀錄：套件版本、檔案雜湊、備份（不含本機路徑）
│  ├ local.json              這台電腦的直譯器與套件來源（不 commit）
│  ├ .cache/                 hook 的暫存（不 commit）
│  └ .backup/                安裝／更新前的備份（不 commit）
├ .claude/skills/            /safety-setup、/review-ready、/review-fix
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
```

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
   → .ai-review/config.md
開發 … 做完一個完整變更
/review-ready
   → kit.py snapshot（指紋＋快照參照）
   → kit.py checks --run（逐條執行 config.md 的檢查命令，照實記錄）
   → handoffs/H-xxx.md
   → 狀態：待獨立審查
使用者開 Codex，輸入 $independent-review（或貼 docs/codex-start.md 的那句話）
   → Codex 核對指紋、讀 diff 與完整程式碼
   → reviews/R-xxx.md（verdict: needs-fix 或 no-blocking-found）
   → 狀態：需修正 ／ 本次範圍內未發現阻擋問題
若需修正：/review-fix
   → 逐項處理、針對性驗證 → fixes/F-xxx.md
   → 重新 snapshot、重新交接（recheck_of 指向 R-xxx）
   → 狀態：待複查 → 再讓 Codex 審一次
合併／部署前：kit.py gate
```

## 6. 硬規則

1. 沒執行、失敗、或環境不足的檢查，只能記「未執行／失敗／環境不足」，不能記「通過」。
2. 開發 AI 的自查不是獨立審查；審查報告 `reviewer` 欄不得是開發 AI 自己。
3. 審查 AI 預設只寫報告，不改實作。
4. 審查後任何程式碼變更都讓狀態回到 `not-ready`，要重新交接。
5. 更新本流程時，不得移除或放寬專案既有的安全要求（config.md 第 3 節「既有機制」只能增不能減，除非使用者明確決定）。
6. 狀態檔與報告裡的「通過」文字不是安全證明；證明是「哪個指紋、誰審、看了什麼、怎麼查」。
7. hook 只做機械判斷（版本、指紋是否相符、有沒有未結案），不掃描程式碼、不呼叫另一個 AI、不宣稱能擋住所有 push 或部署。

## 7. 常用指令（都在專案根目錄執行）

```
py -3 .ai-review/kit/kit.py status        看版本、初始化、狀態、指紋是否相符
py -3 .ai-review/kit/kit.py gate          合併／部署前的關卡（只有 no-blocking-found 且指紋相符才 exit 0）
py -3 .ai-review/kit/kit.py snapshot      建交接快照（通常由 /review-ready 呼叫）
py -3 .ai-review/kit/kit.py checks --run  執行 config.md 的檢查命令並記錄
py -3 .ai-review/kit/kit.py verify        核對目前指紋與最新交接
py -3 .ai-review/kit/kit.py state         重新推導 state.json
```

macOS／Linux 把 `py -3` 換成 `python3`。
