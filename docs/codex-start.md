# 讓 Codex 接手獨立審查（手動啟動＝退路）

Codex 現在是**大件與發版前**的審查路線：平常的變更預設由隔離的 Claude 審查員子代理審（報告標「非 Codex 審查」）；改動檔數超過 `config.md` 第 5 節 `big_change_files`（沒填當 10）、或你要發版前帶 `/review-ready --codex` 時，`/review-ready` 才會用 `py -3 .ai-review/kit/kit.py codex-review` 在背景啟動 Codex。

平常不用看這份。Codex 路線找不到 codex、或你想自己看 Codex 怎麼審時，才照下面手動做。

## 只在專案資料夾開 Codex

**一律在專案根目錄開 Codex**（手動開或用 `codex exec -C <專案>` 都一樣）。不要在使用者資料夾（`%USERPROFILE%`、`~`）、也不要在放很多專案的上層資料夾開。

為什麼（2026-10-11 在 Windows 實際查到的現象）：
- 在某個資料夾開過 Codex，Windows 版 Codex 沙箱的群組（`CodexSandboxUsers`）就可能對那個資料夾和底下全部子資料夾多一筆「可修改」權限，Codex 關掉後還留著。在使用者資料夾開過一次，等於沙箱能改 Claude Code 的設定夾（`.claude`：規則、hook、記憶、對話紀錄）和其他專案。
- 那個資料夾也會被記進 `~/.codex/config.toml` 的信任清單（`[projects.'<路徑>'] trust_level = "trusted"`）。
- 收回要手動改檔案權限、刪掉信任清單那一筆；而且只要再在那裡開一次，⚠️推測權限又會被加回去。
- 就算只在專案裡開，沙箱每次執行仍會對它要讀的範圍補一筆「讀取＋執行」權限（⚠️推測是沙箱設計），所以 Codex 還是讀得到專案外的檔，只是不能改。審查只寫 `.ai-review/reviews/`，是靠審查規範與審後比對把關，不是靠權限擋住。
- 要真的擋住讀取（例如 `~/.ssh`、Codex 登入憑證 `~/.codex/auth.json`），在 `~/.codex/config.toml` 設權限設定檔：最上面（任何 `[表格]` 之前）寫 `default_permissions = "<名稱>"`，再寫 `[permissions.<名稱>]`（`extends = ":workspace"`）與 `[permissions.<名稱>.filesystem]`，要擋的路徑寫 `= "deny"`（官方權限文件；Windows 要 mxc 或 elevated 沙箱才支援）。`codex-review` 看到 `default_permissions` 就改帶 `-c default_permissions`、不帶 `-s workspace-write`——帶了 `-s`，權限設定檔會整組被忽略（Codex 0.162.1 原始碼）。`kit.py doctor` 會列出送審用的是哪一種。

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
- 結論是 `no-blocking-found` → 合併前 `py -3 .ai-review/kit/kit.py gate`（發版前要求 Codex 審查的專案用 `gate --require-reviewer codex`）

不想讓 Codex 動任何檔案時，用唯讀沙箱啟動：`codex --sandbox read-only`；報告內容會印在畫面上，請自己存到 `.ai-review/reviews/<R-編號>.md`。
