# 帶到另一台不能連 GitHub 的電腦（沒有 CI、不推送 GitHub）

## 帶什麼

只帶套件本身：`dist/ai-review-kit-<版本>.zip`（在能連 GitHub 的電腦執行 `py -3 tools/kit.py pack` 產生）。
zip 裡只有方法、範本、工具，**沒有**任何專案程式碼、報告、路徑、帳號或金鑰。

## 安裝

```
py -3 <解壓資料夾>/tools/kit.py install --target <專案根目錄> --preview   # 先看
py -3 <解壓資料夾>/tools/kit.py install --target <專案根目錄>             # 再裝
```
或不解壓：`install --source <zip 路徑> --target <專案>`。

那台電腦的 Python 不是 `py` 啟動器時：加 `--python "<Python 完整路徑>"`。

## 跟能連 GitHub 的電腦有什麼不同

| 項目 | 能連 GitHub 的電腦 | 不能連 GitHub 的電腦 |
|---|---|---|
| 遠端 | GitHub | 那台電腦自己的環境，不推 GitHub |
| CI | 可能有 | 沒有 → `gate` 是唯一關卡，**可被略過**，README／config.md 第 5 節要寫明 |
| 上傳 | — | 工具不連網（除非你手動 `check-update --url`）、不上傳任何內容 |
| 更新 | 直接用 repo | 帶新 zip，`update --source <zip> --preview` 先看差異 |
| 對話紀錄 | — | 不在套件範圍；套件不同步登入資訊、聊天歷史、金鑰 |

## Codex 在那台電腦

- `.codex/hooks.json` 的 SessionStart 提醒要在 Codex 裡 `/hooks` 信任後才會跑；不信任也不影響流程（只是少了開頭提醒）。
- `.agents/skills/independent-review/` 隨專案走；Codex 在專案根目錄啟動就會看到。

## 沒有 CI 時的本地關卡

合併或部署前：
```
py -3 .ai-review/kit/kit.py gate
```
exit 0 才代表「最新交接已被獨立審查為本次範圍內未發現阻擋問題，且程式碼沒再變」。這是本地檢查，任何人都能跳過；要強制得靠遠端保護規則，未設定前不要說「已強制」。
