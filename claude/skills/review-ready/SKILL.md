---
name: review-ready
description: 在一個完整、可獨立理解的變更做完後執行：釘住待審版本（指紋＋git 快照）、逐條執行 config.md 的檢查命令並照實記錄、寫交接報告到 .ai-review/handoffs/，狀態變為「待獨立審查」，再於背景啟動獨立審查（預設派隔離的 Claude 審查員子代理，報告標「非 Codex 審查」；改動檔數超過 big_change_files 或帶 --codex 才送 Codex；--claude 強制走 Claude）。修正審查發現後重新交接也用這個（加 --recheck R-編號）。
argument-hint: "[--recheck R-xxx] [--base <ref>] [--codex | --claude] [一句話描述本次變更範圍]"
---

# /review-ready：交接給獨立審查

完整規範：`.ai-review/kit/handoff-spec.md`。範本：`.ai-review/kit/templates/handoff.md`。本文只列執行順序，**每一步都要真的執行，不能憑印象填**。

## 前置

- 跑 `py -3 .ai-review/kit/kit.py state --json`，看 `initialized`。是 `false`（沒有 config.md、meta 沒填、或第 4 節沒有檢查命令）→ **停下來**，把 `init_reason` 白話轉告使用者，請他先跑 `/safety-setup`，不要交接。
- 先確認這次變更**已經做完**。還在改就不要交接。
- 參數：`$ARGUMENTS` 可能含 `--recheck R-xxx`（修正後重交）、`--base <ref>`、`--codex`（這次送 Codex 審查）、`--claude`（這次強制走隔離 Claude 審查員）、以及範圍描述。`--codex` 與 `--claude` 同時出現 → 停下來問使用者要哪一個。

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
6. **變更範圍與相關檔案**：`git diff --stat <base>..<snapshot_ref> -- . ":(exclude).ai-review"`（快照不含 `.ai-review/`，不排除的話已提交的 `.ai-review/` 檔會全部顯示成刪除、灌高檔數），記下改動檔數（最後一行 `N files changed` 的 N，第 10 步要用）；列出沒改但審查必看的檔案（被呼叫端、設定、權限判斷所在）。
7. **寫報告**：複製範本到 `.ai-review/handoffs/<id>.md`，填滿 1～9 節。`recheck_of` 有 `--recheck` 才填。`{{KIT_VERSION}}` 取 `.ai-review/kit/VERSION`。
8. **推導狀態**：`py -3 .ai-review/kit/kit.py state` → 應為「待獨立審查」（或「待複查」）。不是的話讀它印的原因處理。
9. **回報使用者**（白話）：
   - 改了什麼（三句）
   - 檢查結果：幾條通過、幾條失敗或沒跑、原因
   - 已知風險一到三條
   - 下一步：「我已在背景啟動獨立審查（隔離 Claude 審查員／Codex，依第 10 步），跑完會回報」；Codex 路線走退路時改成「請在專案根目錄開 Codex，輸入 `$independent-review`」；你不能派子代理時改成「交接完成，待派審查員：<H-id>」
   - 固定一句：**本次為開發 AI 自查，尚未獨立審查。**

   **你若是不能再派子代理的子代理**（例如被上層派來做事、規則不准你再派子代理）：做到這一步就停。不跑第 10～12 步（不跑 `claude-review --begin`、不派審查員、不啟動 codex-review），在你的回報（結果檔或最後訊息）寫「待派審查員：<H-id>」，由能派子代理的上層從第 10 步接手。
10. **選審查員**：
   - 算改動檔數：第 3 步的 `modified`＋`untracked`，與第 6 步 `git diff --stat` 的檔數，**取較大者**（先 commit 再交接時前者是 0，所以兩個都要看）。
   - 讀 `config.md` 第 5 節 `big_change_files`；沒有這一行或沒填數字就當 10。
   - 判斷：參數有 `--claude` → Claude 路線；參數有 `--codex`，或改動檔數 > `big_change_files` → Codex 路線；其他 → Claude 路線（預設）。
   - 在回報裡寫一句選了哪條、為什麼（例：「改了 4 個檔，未超過 10，走隔離 Claude 審查員」）。
   - 準備發版、而 `config.md` 第 5 節寫「發版前 gate 需 Codex 審查：是」時，提醒使用者這次要帶 `--codex`（否則之後 `kit.py gate --require-reviewer codex` 不會放行）。
11. **啟動獨立審查（背景）**——照第 10 步的路線做其中一段：

   **11A. Claude 路線（預設）**

   本段指令寫 `<專案>/.ai-review/kit/kit.py`（`<專案>`＝專案根目錄的絕對路徑，**路徑一律用雙引號或正斜線**：Windows 的反斜線沒加引號會被 bash 吃掉），對話資料夾不是專案根（巢狀）時也指得到同一個專案；kit.py 預設就以它所在的專案為對象。
   守門要生效的前提（kit 查不到，`kit.py doctor` 會提醒）：專案資料夾在 Claude Code 開過並**接受信任**（沒信任時子代理定義裡的 hook 會被略過、不報錯）、Claude Code 2.1.271 以上、對話開在專案根目錄（或 `reviewer-agent --session-root` 指定的上層資料夾；開在專案的子資料夾時守門找不到 kit.py，審查員的工具全被擋）。
   1. 先看你的可用子代理清單裡有沒有 `independent-reviewer`。沒有 → 跳到下面「找不到審查員子代理」，**不要**先跑 `--begin`。
   2. 登記開審：
      ```
      py -3 <專案>/.ai-review/kit/kit.py claude-review --begin <H-id>
      ```
      它會拒絕：不是最新交接、交接後程式又改過（重新交接）、這份交接已有審查（真的要重審才加 `--again`）、同一份正在跑。照它印的原因處理，不要硬派。
   3. 選模型別名：與你自己不同。你是 opus → 填 `fable`；其他（fable、sonnet…）→ 填 `opus`。
   4. 用 Agent 工具派工：`subagent_type: independent-reviewer`、`model: <別名>`、背景執行（`run_in_background: true`）。prompt 固定只寫下面四行（`--begin` 印出的就是這四行、已填好專案與交接，把 `<別名>` 換掉即可），**不附你的開發摘要、結論或建議**（審查員要自己查證）：
      ```
      專案：<專案>
      交接：<H-id>
      reviewer_model：<別名>
      請依 <專案>/.ai-review/kit/review-spec.md 審查這份交接；報告檔頭 reviewer 寫 claude-isolated、reviewer_model 寫上面的別名。
      ```
   5. 收到子代理結束通知後，收尾：
      ```
      py -3 <專案>/.ai-review/kit/kit.py claude-review --end <H-id> --model <別名>
      ```
      它只收**這次審查開始後新寫**的報告，比對審查前後工作目錄、寫紀錄並推導狀態，印出 R 編號與結論。
      - exit 2＝沒有先跑 `--begin`（或開始紀錄是舊版）。
      - exit 1＝「這次沒有新的審查報告」→ 讀子代理的最後回報找原因（回報第一行是「守門未生效，停止審查」時，照下面「守門沒生效」處理）；或「審查報告區在審查期間有不該出現的變動」（審查開始前就有的報告被改／刪、新報告的 reviewer 不是 claude-isolated）→ 這次結果先不要採信，把它印的清單原樣告訴使用者，kit 不會自動還原或刪除。
      - 印出「⚠️⚠️ 守門 hook 沒有執行紀錄」＝審查期間守門一次都沒被呼叫（exit 仍 0，狀態標「（非 Codex 審查；守門未生效）」）：照實告訴使用者「這次審查沒有守門保護」，建議跑 `kit.py doctor`、在專案根目錄開一次 Claude Code 接受信任後重派，或改送 Codex。
      - 子代理說它寫不了檔、把報告放在回報裡 → 原樣轉給使用者，**不得**自己改寫內容或代存成審查報告。

   **守門沒生效**（子代理回報「守門未生效，停止審查」，或 `--end` 印守門沒有執行紀錄）：不要自己補審、不要改用一般子代理。告訴使用者原因多半是專案資料夾還沒被 Claude Code 信任、這台找不到 `py`（`kit.py doctor` 會說怎麼改）、或對話開在別的資料夾；處理好後 `claude-review --begin <H-id> --again` 重派，或改走 Codex 路線（11B）。

   **找不到審查員子代理**（可用子代理清單沒有 `independent-reviewer`，或 Agent 工具回報沒有這個類型）。常見原因：剛裝好套件、Claude Code 還沒重開（新的 `.claude/agents/` 要重開才會載入）；或這是巢狀專案（對話開在專案的上層資料夾，子代理只從對話資料夾往上找）。退路三選一，告訴使用者由他決定：
   - 改走 Codex 路線（11B）。
   - 剛裝完：請使用者重開 Claude Code 後再跑 `/review-ready`。
   - 巢狀專案：`py -3 <專案>/.ai-review/kit/kit.py reviewer-agent --session-root <對話開啟的資料夾>` 會印出改好路徑的審查員定義（加 `--out <檔>` 才寫檔）；放到對話資料夾的 `.claude/agents/` 由使用者決定，放好要重開 Claude Code。
   - **不得**改用一般子代理（general-purpose 等）或自己來冒充審查員：它們會讀 CLAUDE.md 與記憶、沒有守門，審出來的不算獨立審查。已跑過 `--begin` 才發現派不出去 → 照實告訴使用者；之後重跑 `--begin` 若說同一份正在跑，照它印的指示處理。

   **11B. Codex 路線（大件、發版前、或帶 `--codex`）**
   ```
   py -3 .ai-review/kit/kit.py codex-review
   ```
   - Claude Code 裡用 Bash 工具的 `run_in_background` 執行（指令會等 Codex 跑完才結束，結束時你會收到通知）；不是在 Claude Code 裡就加 `--detach`，它會丟到背景立刻返回。
   - 這個指令固定用沙箱：Codex 設定檔有 `default_permissions`（權限設定檔）就用它（`-c default_permissions`，不帶 `-s`），沒有就用工作區沙箱（`-s workspace-write`）；TMP 指到 `.ai-review/.cache/tmp`、模型照 Codex 設定檔；**不得**自己改用 `--dangerously-bypass-approvals-and-sandbox` 或加 `-m`。
   - 它會拒絕：交接後程式又改過（重新交接）、這份交接已有審查（真的要重審才加 `--again`）、同一份正在跑。
   - exit 3＝找不到 codex → 走退路：請使用者在專案根目錄開 Codex 輸入 `$independent-review`（`.ai-review/kit/docs/codex-start.md`）。
   - 使用者說「這次我自己開 Codex」也走退路，不要硬跑。
12. **收結果**（Claude 路線：`--end` 印出結果後；Codex 路線：收到背景結束通知後）：讀它印的審查編號與結論，再讀 `.ai-review/reviews/<R-id>.md`。
   - Claude 路線固定加一句：**本次為隔離 Claude 的獨立審查（非 Codex 審查）。**
   - `needs-fix` → 白話列出阻擋項，問使用者是否 `/review-fix <R-id>`。
   - `no-blocking-found` → 告訴使用者可以進行合併前的 `gate`（發版前要求 Codex 審查的專案，Claude 路線的結論不能讓 `gate --require-reviewer codex` 放行；這個關卡用本機紀錄核對報告檔頭，`codex-review` 送審或使用者手動開 Codex 審都算）。一般 `gate` 也用本機紀錄核對：隔離 Claude 審查收尾時守門心跳 0 筆（守門未生效）、或本機開過這份交接的審查卻沒有這份報告的收尾紀錄（還沒 `claude-review --end`，或重派後沒收尾）不放行（使用者決定接受才加 `--allow-no-guard`；換電腦或 CI 整台沒紀錄只提示），隔離 Claude 審查員寫的報告檔頭卻不是 `claude-isolated`（冒充）一律不放行。
   - 同一份交接 Codex 已判 `needs-fix`，之後隔離 Claude 判 `no-blocking-found`：狀態維持 `needs-fix`（較弱的審查員不能推翻較強的需修正結論）。照實告訴使用者，重審請用 Codex 或修正後重新交接。
   - Codex 路線沒產生報告 → 讀 `.ai-review/.cache/codex-<H-id>.log` 找原因（額度不足、登入過期…）；額度不足就在 `config.md` 第 6 節記「哪份交接尚未審、為什麼」，等額度恢復再跑，或改走 Claude 路線（`--claude`）。

## 不可以

- 不可以把沒跑、失敗、環境不足的檢查記成通過。
- 不可以把狀態改成「本次範圍內未發現阻擋問題」。
- 不可以交接後繼續改程式卻不重新交接。
- 不可以用一般子代理或自己冒充 `independent-reviewer`；不可以把隔離 Claude 的審查說成 Codex 審查。
