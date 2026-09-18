# 變更紀錄

版本規則：patch＝修 bug 不改行為；minor＝加功能且舊專案資料相容；major＝專案資料需轉換或使用方式改變。
每次發版：改 `VERSION`、在這裡加一段、`kit.py pack` 重打離線包。

## 0.1.0 — 2026-09-18

第一版。

- 核心規範五份（`core/`）：總覽與狀態推導、安全檢查清單（對應 OWASP ASVS 5.0.0）、交接規範、獨立審查規範、修正規範。
- 範本七份（`templates/`）：專案設定、交接／審查／修正報告、Claude 與 Codex 入口區塊。
- Claude Code Skills 三個：`/safety-setup`、`/review-ready`、`/review-fix`。
- Codex Skill 一個：`$independent-review`。
- 工具 `tools/kit.py`（純 Python 標準函式庫）：install／update／status／restore／pack／check-update，以及專案內的 snapshot／checks／state／verify／gate／hook。
- hooks：Claude Code 的 SessionStart（顯示版本、初始化、狀態、未結案）與 Stop（交接過期提醒，每個指紋只提醒一次，永不阻擋）；Codex 的 SessionStart（同內容，未實測）。
- 狀態由報告檔頭與程式碼指紋推導，`.ai-review/` 不計入指紋，所以寫報告不會讓狀態過期。
