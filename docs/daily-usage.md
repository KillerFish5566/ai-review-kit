# 日常使用（一頁）

## 你要記的只有這些

| 時機 | 在哪裡 | 打什麼 |
|---|---|---|
| 新專案第一次 | Claude Code | `/safety-setup` |
| 一個完整變更做完 | Claude Code | `/review-ready`（可加一句範圍描述） |
| 要獨立審查 | 不用做事 | `/review-ready` 最後會在背景啟動 Codex，跑完回報（想自己開：終端機 `codex` → `$independent-review`） |
| 審查說要修 | Claude Code | `/review-fix R-編號` |
| 修完要複查 | 不用做事 | `/review-fix` 會重新交接並在背景啟動複查 |
| 合併／部署前 | 終端機 | `py -3 .ai-review/kit/kit.py gate` |
| 不確定現在什麼狀態 | 終端機 | `py -3 .ai-review/kit/kit.py status` |

每次開 Claude Code，開頭會自動出現一段 `[ai-review-kit vX]` 狀態（初始化、狀態、未結案）。看到「已過期」就代表要重新 `/review-ready`。

## 狀態怎麼讀

| 看到 | 意思 | 你做什麼 |
|---|---|---|
| 尚未準備 | 沒交接，或交接後程式又改了 | 做完再 `/review-ready` |
| 待獨立審查 | 交接好了，Codex 在背景審或還沒啟動 | 等回報；沒在跑就請 Claude 執行 `codex-review` |
| 需修正 | Codex 找到阻擋級問題 | `/review-fix` |
| 待複查 | 修好重交了 | 等複查回報 |
| 本次範圍內未發現阻擋問題 | 這個版本 Codex 沒找到阻擋問題 | 可以合併（`gate` 會確認指紋還相符） |

## 哪些檔要 commit

- 要：`.ai-review/`（除了 `.cache/`、`.backup/`，已在 .gitignore）、`.claude/skills/`、`.claude/settings.json`、`.agents/`、`.codex/hooks.json`、`CLAUDE.md`、`AGENTS.md`
- 不要：`.ai-review/.cache/`、`.ai-review/.backup/`、任何 `.env`、金鑰

`refs/ai-review/*` 快照參照只存在本機 git，不會被 push（正常 push 不帶這些 ref）。

## 換電腦（同一個專案 clone 到另一台）

```
py -3 .ai-review/kit/kit.py relink
```
只重寫 hook 裡的 Python 路徑。之後重開 Claude Code。

## 常見狀況

- **hook 開頭沒出現**：hooks 是啟動時載入，改完設定要重開 Claude Code；`status` 看接線是否就位；Python 路徑不對就 `relink`。
- **Codex 不認得 `$independent-review`**：確認在專案根目錄啟動、`.agents/skills/independent-review/SKILL.md` 存在；不行就貼 `codex-start.md` 那句話。
- **背景審查沒有產生報告**：看 `.ai-review/.cache/codex-<H-編號>.log`（常見：額度不足、登入過期）。額度不足就在 `config.md` 第 6 節記下哪份交接尚未審，恢復後再跑 `py -3 .ai-review/kit/kit.py codex-review`。
- **審查結束時出現「⚠️ 審查期間工作區有 N 個檔變了」**：Codex 審查期間專案裡多了或改了檔（例如字面名稱的 `%SystemDrive%\` 資料夾＝沙箱少了環境變數時 Windows 留下的快取），指紋可能因此對不上、審查判 invalid。先看清單上是什麼：是垃圾就清掉後 `codex-review --again`；是真的改動就重新 `/review-ready`。kit 不會自動刪任何檔。
- **Codex 沙箱唯讀寫不了報告**（手動用 `--sandbox read-only` 時）：它會把報告印出來，你存到 `.ai-review/reviews/R-編號.md`，回 Claude Code 跑 `py -3 .ai-review/kit/kit.py state`。
- **想看某次審的是哪個版本**：交接檔頭的 `snapshot_ref`，`git diff <base>..refs/ai-review/H-xxx`。
