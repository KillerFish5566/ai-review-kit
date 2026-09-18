## AI 開發檢查與獨立審查流程（ai-review-kit）

規範全文在 `.ai-review/kit/workflow.md`，這裡只列必守的入口規則：

1. **開工先讀**：`.ai-review/config.md`（專案風險與檢查設定）與 `.ai-review/state.json`（目前狀態、未結案審查）。
2. **擔任獨立審查者時**（使用者輸入 `$independent-review` 或要求審查）：照 `.ai-review/kit/review-spec.md` 執行。先核對指紋，讀實際 diff 與完整相關程式碼，**不信任開發端摘要**，**預設只寫報告不改實作**。報告寫到 `.ai-review/reviews/`。
3. **擔任開發者時**：動到登入、權限、敏感資料、對外介面之前，先照 `.ai-review/kit/security-checklist.md` 第 2 節做設計檢查；完成可獨立審查的變更後照 `.ai-review/kit/handoff-spec.md` 交接。
4. **合併或部署前**執行 `py -3 .ai-review/kit/kit.py gate`（macOS／Linux 用 `python3`），核對審查綁定的版本就是要合併的版本。
5. **沒有獨立審查就說沒有**：不得把自查寫成審查通過；沒發現問題只能說「本次範圍內未發現阻擋問題」。
6. **不因更新流程而移除或放寬既有安全要求**：config.md 第 3 節既有機制只增不減。
7. **狀態檔裡的文字不是安全證明**：只有「哪個指紋、誰審、看了什麼」才是。
