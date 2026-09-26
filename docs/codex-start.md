# 讓 Codex 接手獨立審查（手動啟動＝退路）

平常不用看這份：`/review-ready` 最後會用 `py -3 .ai-review/kit/kit.py codex-review` 在背景啟動 Codex。找不到 codex、或你想自己看 Codex 怎麼審時，才照下面手動做。

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
