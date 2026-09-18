# 日常使用（一頁）

## 你要記的只有這些

| 時機 | 在哪裡 | 打什麼 |
|---|---|---|
| 新專案第一次 | Claude Code | `/safety-setup` |
| 一個完整變更做完 | Claude Code | `/review-ready`（可加一句範圍描述） |
| 要獨立審查 | 終端機開 `codex` | `$independent-review` |
| 審查說要修 | Claude Code | `/review-fix R-編號` |
| 修完要複查 | 終端機開 `codex` | `$independent-review`（它會自己看到是複查） |
| 合併／部署前 | 終端機 | `py -3 .ai-review/kit/kit.py gate` |
| 不確定現在什麼狀態 | 終端機 | `py -3 .ai-review/kit/kit.py status` |

每次開 Claude Code，開頭會自動出現一段 `[ai-review-kit vX]` 狀態（初始化、狀態、未結案）。看到「已過期」就代表要重新 `/review-ready`。

## 狀態怎麼讀

| 看到 | 意思 | 你做什麼 |
|---|---|---|
| 尚未準備 | 沒交接，或交接後程式又改了 | 做完再 `/review-ready` |
| 待獨立審查 | 交接好了 | 開 Codex |
| 需修正 | Codex 找到阻擋級問題 | `/review-fix` |
| 待複查 | 修好重交了 | 再開 Codex |
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
- **Codex 沙箱唯讀寫不了報告**：它會把報告印出來，你存到 `.ai-review/reviews/R-編號.md`，回 Claude Code 跑 `py -3 .ai-review/kit/kit.py state`。
- **想看某次審的是哪個版本**：交接檔頭的 `snapshot_ref`，`git diff <base>..refs/ai-review/H-xxx`。
