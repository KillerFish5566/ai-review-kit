---
name: review-ready
description: 在一個完整、可獨立理解的變更做完後執行：釘住待審版本（指紋＋git 快照）、逐條執行 config.md 的檢查命令並照實記錄、寫交接報告到 .ai-review/handoffs/，狀態變為「待獨立審查」，再於背景啟動 Codex 獨立審查。修正審查發現後重新交接也用這個（加 --recheck R-編號）。
argument-hint: "[--recheck R-xxx] [--base <ref>] [一句話描述本次變更範圍]"
---

# /review-ready：交接給獨立審查

完整規範：`.ai-review/kit/handoff-spec.md`。範本：`.ai-review/kit/templates/handoff.md`。本文只列執行順序，**每一步都要真的執行，不能憑印象填**。

## 前置

- 跑 `py -3 .ai-review/kit/kit.py state --json`，看 `initialized`。是 `false`（沒有 config.md、meta 沒填、或第 4 節沒有檢查命令）→ **停下來**，把 `init_reason` 白話轉告使用者，請他先跑 `/safety-setup`，不要交接。
- 先確認這次變更**已經做完**。還在改就不要交接。
- 參數：`$ARGUMENTS` 可能含 `--recheck R-xxx`（修正後重交）、`--base <ref>`、以及範圍描述。

## 步驟

1. **範圍一句話**：這次變更是什麼、不含什麼。沒有描述就從 git log／diff 歸納後跟使用者確認。
2. **看工作目錄**：`git status --porcelain`。有未追蹤檔案時逐一判斷：該送審 → 留著；是暫存或實驗 → 請使用者處理，不要自己刪。**不得靜默排除任何檔案。**
3. **釘版本**：
   ```
   py -3 .ai-review/kit/kit.py snapshot --json [--base <ref>]
   ```
   記下輸出的 `id`、`target`、`snapshot_ref`、`head`、`base`、`branch`、`modified`、`untracked`。非 git 專案會沒有 `snapshot_ref`，報告要註明。
4. **跑檢查**：
   ```
   py -3 .ai-review/kit/kit.py checks --run --handoff <id>
   ```
   把印出的 Markdown 表原樣貼進報告第 5 節。`fail`／`skipped`／`not-run` 就照寫；**不得改成 pass**。另記工具版本（語言、框架、掃描器）。
5. **設計檢查**：若這次動到登入／權限／敏感資料／對外介面（依 config.md 第 7 節），照 `security-checklist.md` 第 2 節六題逐題回答寫進第 6 節；沒動到就寫「不適用：本次未動到」。
6. **變更範圍與相關檔案**：`git diff --stat <base>..<snapshot_ref>`；列出沒改但審查必看的檔案（被呼叫端、設定、權限判斷所在）。
7. **寫報告**：複製範本到 `.ai-review/handoffs/<id>.md`，填滿 1～9 節。`recheck_of` 有 `--recheck` 才填。`{{KIT_VERSION}}` 取 `.ai-review/kit/VERSION`。
8. **推導狀態**：`py -3 .ai-review/kit/kit.py state` → 應為「待獨立審查」（或「待複查」）。不是的話讀它印的原因處理。
9. **回報使用者**（白話）：
   - 改了什麼（三句）
   - 檢查結果：幾條通過、幾條失敗或沒跑、原因
   - 已知風險一到三條
   - 下一步：「我已在背景啟動 Codex 獨立審查，跑完會自動回報」（第 10 步）；第 10 步走退路時改成「請在專案根目錄開 Codex，輸入 `$independent-review`」
   - 固定一句：**本次為開發 AI 自查，尚未獨立審查。**
10. **啟動獨立審查（背景）**：
   ```
   py -3 .ai-review/kit/kit.py codex-review
   ```
   - Claude Code 裡用 Bash 工具的 `run_in_background` 執行（指令會等 Codex 跑完才結束，結束時你會收到通知）；不是在 Claude Code 裡就加 `--detach`，它會丟到背景立刻返回。
   - 這個指令固定用工作區沙箱（`-s workspace-write`）、TMP 指到 `.ai-review/.cache/tmp`、模型照 Codex 設定檔；**不得**自己改用 `--dangerously-bypass-approvals-and-sandbox` 或加 `-m`。
   - 它會拒絕：交接後程式又改過（重新交接）、這份交接已有審查（真的要重審才加 `--again`）、同一份正在跑。
   - exit 3＝找不到 codex → 走退路：請使用者在專案根目錄開 Codex 輸入 `$independent-review`（`.ai-review/kit/docs/codex-start.md`）。
   - 使用者說「這次我自己開 Codex」也走退路，不要硬跑。
11. **收結果**（收到背景結束通知後）：讀它印的審查編號與結論，再讀 `.ai-review/reviews/<R-id>.md`。
   - `needs-fix` → 白話列出阻擋項，問使用者是否 `/review-fix <R-id>`。
   - `no-blocking-found` → 告訴使用者可以進行合併前的 `gate`。
   - 沒產生報告 → 讀 `.ai-review/.cache/codex-<H-id>.log` 找原因（額度不足、登入過期…）；額度不足就在 `config.md` 第 6 節記「哪份交接尚未審、為什麼」，等額度恢復再跑。

## 不可以

- 不可以把沒跑、失敗、環境不足的檢查記成通過。
- 不可以把狀態改成「本次範圍內未發現阻擋問題」。
- 不可以交接後繼續改程式卻不重新交接。
