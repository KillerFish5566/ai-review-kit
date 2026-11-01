# 日常使用（一頁）

## 你要記的只有這些

| 時機 | 在哪裡 | 打什麼 |
|---|---|---|
| 新專案第一次 | Claude Code | `/safety-setup` |
| 一個完整變更做完 | Claude Code | `/review-ready`（可加一句範圍描述） |
| 要獨立審查 | 不用做事 | `/review-ready` 最後會自己選審查員並在背景啟動，跑完回報（見下面「兩種審查員」） |
| 這次要送 Codex（發版前） | Claude Code | `/review-ready --codex`（想自己開：終端機 `codex` → `$independent-review`） |
| 審查說要修 | Claude Code | `/review-fix R-編號` |
| 修完要複查 | 不用做事 | `/review-fix` 會重新交接並在背景啟動複查 |
| 合併／部署前 | 終端機 | `py -3 .ai-review/kit/kit.py gate`（發版前要求 Codex 審查：`gate --require-reviewer codex`） |
| 不確定現在什麼狀態 | 終端機 | `py -3 .ai-review/kit/kit.py status` |

在**專案資料夾直接開** Claude Code 時，開頭會自動出現一段 `[ai-review-kit vX]` 狀態（初始化、狀態、未結案）。看到「已過期」就代表要重新 `/review-ready`。

- 開場狀態與收工提醒（hook）只有在專案資料夾直接開 Claude Code 才會跑；從上層資料夾開的對話不會自動提醒，要自己跑 `py -3 .ai-review/kit/kit.py state` 或 `/review-ready`。
- 審查紀錄跟著 git 分支走，換分支後看到的是那個分支的狀態（不是審查不見了）。
- 裝完或換電腦，想知道還缺什麼（審查員定義、Codex、登入、gitleaks…）：`py -3 .ai-review/kit/kit.py doctor`。
- **第一次裝好（或更新後多了審查員定義）要重開 Claude Code**：審查員子代理定義放在 `.claude/agents/`，Claude Code 開啟時才載入。
- **隔離 Claude 審查員的守門要生效，三件事**（kit 查不到的部分 `doctor` 會提醒）：①專案資料夾在 Claude Code 開過一次並**接受信任**（沒信任時守門 hook 會被略過、不報錯）；②Claude Code 2.1.271 以上；③Claude Code 開在專案根目錄。另外這台要找得到 `py`（守門 hook 用它；沒有 `py` 見下面「常見狀況」）。

## 兩種審查員

| 審查員 | 什麼時候用 | 報告 `reviewer` | 誰啟動 |
|---|---|---|---|
| 隔離 Claude（`independent-reviewer` 子代理） | 預設 | `claude-isolated`，狀態後面加「（非 Codex 審查）」 | `/review-ready` 派子代理，模型與開發 AI 不同（開發是 opus 就派 fable，否則派 opus） |
| Codex | 大件（改動檔數超過 `config.md` 第 5 節 `big_change_files`，沒填當 10）、發版前、或你帶 `--codex` | `codex` | `/review-ready` 背景跑 `kit.py codex-review`；退路你自己開 Codex |

- 隔離 Claude 審查員是另開的：不帶開發對話的脈絡、不讀 CLAUDE.md 與記憶、走你的 Claude 訂閱額度。一般子代理不算審查員，Claude 也不准拿來冒充。
- **守門 hook**：審查員每次用工具前都會先過 `kit.py hook review-guard`，只准新寫 `.ai-review/reviews/R-*.md`（審查開始前就有的報告不准改）、只准跑 git 唯讀指令、kit.py 的 verify／new-id R／state --no-write／checks --run，以及 `config.md` 第 4 節登記的檢查命令原文。被擋的事審查員會寫進報告的「沒做的事」。審查員第一步會先試一條該被擋的指令（`echo guard-canary`），沒被擋就停止審查、回報「守門未生效」。
- **守門的限制**：它只管 Claude 的工具層。檢查命令啟動的程式（例如 Python 子程序）自己寫檔它看不到，這部分靠審查結束時的審前審後比對抓（印警告、寫進紀錄，不自動刪）。git 設定（例如 `core.fsmonitor`）也可能讓唯讀 git 指令叫外部程式，審查員改不到這些設定。
- 要求發版前一定要 Codex 審過：`config.md` 第 5 節寫「發版前 gate 需 Codex 審查：是」，發版前跑 `py -3 .ai-review/kit/kit.py gate --require-reviewer codex`，最新審查不是 Codex 審的就不放行。報告檔頭可能是假的，所以它另外用本機紀錄核對：`codex-review` 送審的要有執行紀錄指向那份報告；手動開 Codex 審的（額度不夠或找不到 codex 時的正式退路）沒有這個紀錄，只要那份報告不是隔離 Claude 審查員寫的（守門的寫檔紀錄裡沒有它）就依檔頭採信，並印一行「未見 codex-review 執行紀錄」提醒你（守門沒生效時分辨不出）。紀錄在 `.ai-review/.cache/`、不進版控，所以這是**本機關卡**：CI 上不要帶這個參數。
- 一般 `gate`（不帶參數）對隔離 Claude 審的報告也用同一處的本機紀錄核對：收尾時守門心跳 0 筆（守門沒生效）、或這台電腦開過這份交接的審查卻沒有這份報告的收尾紀錄（還沒 `claude-review --end`，或用 `--begin --again` 重派後沒收尾）→ 不放行，你確定接受這份審查才加 `--allow-no-guard`；隔離 Claude 審查員寫的報告檔頭卻寫別的審查者（冒充）一律不放行。重派不會清掉這些紀錄。換電腦或 CI 上整台都沒有紀錄時只印提醒、不擋。
- 同一份交接 Codex 判了「需修正」之後，隔離 Claude 再審判「未發現阻擋問題」**不會**蓋掉它：狀態維持需修正，要重審請用 Codex，或修正後重新交接。`gate` 會印出這份交接的審查歷程。
- 不想等它自己選：`/review-ready --claude` 強制隔離 Claude；`/review-ready --codex` 強制 Codex。

## 巢狀專案（對話不是在專案資料夾開的）

例如對話開在放很多專案的上層資料夾，專案在它底下。這時：
- 專案內的審查員定義**不會被載入**（Claude Code 只從對話開啟的資料夾往上找 `.claude/agents/`），`/review-ready` 會說找不到審查員，讓你選：改走 Codex、或在專案資料夾直接開對話。
- 想在上層資料夾也能用隔離 Claude 審查：`py -3 <專案>/.ai-review/kit/kit.py reviewer-agent --session-root <對話開啟的資料夾>` 會印出改好路徑的審查員定義（加 `--out <檔>` 才寫檔），放到對話資料夾的 `.claude/agents/independent-reviewer.md`，重開 Claude Code。同一個對話資料夾只能放一份，它的守門路徑只對應一個專案；底下有好幾個專案時，只有那一個能在這裡用隔離 Claude 審查，其他的在自己的專案資料夾開對話。

## 狀態怎麼讀

| 看到 | 意思 | 你做什麼 |
|---|---|---|
| 尚未準備 | 沒交接，或交接後程式又改了 | 做完再 `/review-ready` |
| 待獨立審查 | 交接好了，審查員在背景審或還沒啟動 | 等回報；沒在跑就請 Claude 再跑一次 `/review-ready` 的審查步驟 |
| 需修正 | 審查員找到阻擋級問題 | `/review-fix` |
| 待複查 | 修好重交了 | 等複查回報 |
| 本次範圍內未發現阻擋問題 | 這個版本審查員沒找到阻擋問題；後面有「（非 Codex 審查）」＝隔離 Claude 審的 | 可以合併（`gate` 會確認指紋還相符；隔離 Claude 審的另核對守門有生效、有收尾紀錄）；發版前要求 Codex 的專案要再送一次 Codex |

## 哪些檔要 commit

- 要：`.ai-review/`（除了 `.cache/`、`.backup/`、`local.json`、`state.json`，已在 .gitignore）、`.claude/skills/`、`.claude/agents/`、`.claude/settings.json`、`.agents/`、`.codex/hooks.json`、`CLAUDE.md`、`AGENTS.md`
- 不要：`.ai-review/.cache/`、`.ai-review/.backup/`、`.ai-review/local.json`、`.ai-review/state.json`（本機推導，每次看狀態都會變）、任何 `.env`、金鑰。舊專案的 `state.json` 如果已經在版控，跑 `git rm --cached .ai-review/state.json` 再存一個版本（檔案會留在電腦上）

`refs/ai-review/*` 快照參照只存在本機 git，不會被 push（正常 push 不帶這些 ref）。

## 換電腦（同一個專案 clone 到另一台）

```
py -3 .ai-review/kit/kit.py relink
```
只重寫 hook 裡的 Python 路徑。之後重開 Claude Code。

## 常見狀況

- **hook 開頭沒出現**：hooks 是啟動時載入，改完設定要重開 Claude Code；`status` 看接線是否就位；Python 路徑不對就 `relink`。
- **Codex 不認得 `$independent-review`**：確認在專案根目錄啟動、`.agents/skills/independent-review/SKILL.md` 存在；不行就貼 `codex-start.md` 那句話。
- **Codex 背景審查沒有產生報告**：看 `.ai-review/.cache/codex-<H-編號>.log`（常見：額度不足、登入過期）。額度不足就在 `config.md` 第 6 節記下哪份交接尚未審，恢復後再跑 `py -3 .ai-review/kit/kit.py codex-review`，或這次改用 `/review-ready --claude`。
- **隔離 Claude 審查員沒有產生報告**：`claude-review --end` 會說「這次沒有新的審查報告」（審查開始前就有的報告不算）；看審查員子代理的最後回報（被守門擋下、寫不了檔時它會說明）。它把報告放在回報裡時，Claude 會原樣轉給你，不會代改。
- **審查員回報「守門未生效，停止審查」，或結束時出現「⚠️⚠️ 守門 hook 沒有執行紀錄」**：這次審查沒有守門保護。常見原因：專案資料夾還沒在 Claude Code 接受信任、這台找不到 `py`、Claude Code 開在別的資料夾。跑 `py -3 .ai-review/kit/kit.py doctor` 看「審查員子代理」那一列；在專案根目錄開一次 Claude Code 接受信任，再 `/review-ready` 重派（或改送 Codex）。審查內容照收，但狀態會標「（非 Codex 審查；守門未生效）」。
- **這台沒有 `py`**（macOS／Linux）：`python3 .ai-review/kit/kit.py reviewer-agent --session-root <專案> --python python3 --out <專案>/.claude/agents/independent-reviewer.md --force`，重開 Claude Code。之後 `update` 會把這個檔列為你改過的檔（不覆蓋）。
- **結束時說「審查報告區在審查期間有不該出現的變動」（exit 1）**：審查開始前就有的報告被改或被刪，或新報告的 `reviewer` 不是 `claude-isolated`。這次結果先不要採信；照它列的檔名人工核對（kit 不會自動還原或刪），處理後重審。
- **`/review-ready` 說找不到 `independent-reviewer`**：剛裝完沒重開 Claude Code，或是巢狀專案（見上面「巢狀專案」）。Claude 不會改用一般子代理冒充。
- **審查結束時出現「⚠️ 審查期間工作區有 N 個檔變了」**：審查期間專案裡多了或改了檔（Codex 常見的是字面名稱的 `%SystemDrive%\` 資料夾＝沙箱少了環境變數時 Windows 留下的快取；隔離 Claude 則可能是檢查命令自己寫的檔），指紋可能因此對不上、審查判 invalid。先看清單上是什麼：是垃圾就清掉後重審（Codex：`codex-review --again`；隔離 Claude：`claude-review --begin <H-編號> --again` 再派審查員）；是真的改動就重新 `/review-ready`。kit 不會自動刪任何檔。
- **Codex 沙箱唯讀寫不了報告**（手動用 `--sandbox read-only` 時）：它會把報告印出來，你存到 `.ai-review/reviews/R-編號.md`，回 Claude Code 跑 `py -3 .ai-review/kit/kit.py state`。
- **`/safety-setup` 說 `.gitignore` 少排除幾種機密檔**：這是提醒，不擋流程，套件沒有動你的 `.gitignore`。要補就跟 Claude 說「補 .gitignore」，它會先給你看要加哪幾行；某條在這個專案是正常資料（例如題庫 `*.jsonl`），就記進 `config.md` 的 ```` ```ignore-ok ```` 區塊。隨時可以自己查：`py -3 .ai-review/kit/kit.py ignore-check`。
- **想看某次審的是哪個版本**：交接檔頭的 `snapshot_ref`，`git diff <base>..refs/ai-review/H-xxx`。
