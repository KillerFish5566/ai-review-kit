# 讓 Codex 接手獨立審查（手動啟動＝退路）

平常不用看這份：`/review-ready` 最後會用 `py -3 .ai-review/kit/kit.py codex-review` 在背景啟動 Codex。找不到 codex、或你想自己看 Codex 怎麼審時，才照下面手動做。

## 只在專案資料夾開 Codex

**一律在專案根目錄開 Codex**（手動開或用 `codex exec -C <專案>` 都一樣）。不要在使用者資料夾（`C:\Users\<你>`）、也不要在放很多專案的上層資料夾開。

為什麼（2026-10-11 在 Windows 實際查到的現象）：
- 在某個資料夾開過 Codex，Windows 版 Codex 沙箱的群組（`CodexSandboxUsers`）就可能對那個資料夾和底下全部子資料夾多一筆「可修改」權限，Codex 關掉後還留著。在使用者資料夾開過一次，等於沙箱能改 Claude Code 的設定夾（`.claude`：規則、hook、記憶、對話紀錄）和其他專案。
- 那個資料夾也會被記進 `~/.codex/config.toml` 的信任清單（`[projects.'<路徑>'] trust_level = "trusted"`）。
- 收回要手動改檔案權限、刪掉信任清單那一筆；而且只要再在那裡開一次，⚠️推測權限又會被加回去。
- 就算只在專案裡開，沙箱每次執行仍會對它要讀的範圍補一筆「讀取＋執行」權限（⚠️推測是沙箱設計），所以 Codex 還是讀得到專案外的檔，只是不能改。審查只寫 `.ai-review/reviews/`，是靠審查規範與審後比對把關，不是靠權限擋住。

`/review-ready` 背景啟動的 `kit.py codex-review` 一律帶 `-C <專案>`，不受影響；這段是給手動開 Codex 的時候看的。

## 手動啟動

在**專案根目錄**開終端機：

```
codex
```

進去後輸入下面任一種：

- 打 `$independent-review`（Codex 會載入 `.agents/skills/independent-review/SKILL.md`）
- 或貼這句話：

```
請以獨立審查者身分，依 .ai-review/kit/review-spec.md 審查最新的交接（.ai-review/handoffs/ 編號最大的 H-*.md）：先核對指紋，讀實際 diff 與完整相關程式碼，不改實作，把報告寫到 .ai-review/reviews/。
```

審查完成後回到 Claude Code：

- 結論是 `needs-fix` → `/review-fix R-編號`
- 結論是 `no-blocking-found` → 合併前 `py -3 .ai-review/kit/kit.py gate`

不想讓 Codex 動任何檔案時，用唯讀沙箱啟動：`codex --sandbox read-only`；報告內容會印在畫面上，請自己存到 `.ai-review/reviews/<R-編號>.md`。
