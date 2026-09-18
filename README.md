# ai-review-kit（審印匣）— AI 開發檢查與獨立審查流程套件

> 中文代號「審印匣」：審查（審）綁在程式碼指紋（印）上，整套裝在一個可以帶著走的匣子裡。對 AI 說「裝審印匣到 <專案>」就是執行下面的 install。

> 給「用 AI 寫程式、自己能驗收功能、但看不出漏洞」的人：讓開發 AI（Claude Code）交接、讓另一個 AI（Codex）獨立審查，狀態綁在明確版本上，程式一改舊結果就失效。
> 通用套件只有方法、範本與工具；**不含任何專案程式碼、漏洞細節、內部路徑或機密**。

版本：見 `VERSION`；變更：`CHANGELOG.md`。

## 一頁看懂

```
你                    Claude Code（開發 AI）              Codex（審查 AI，你手動開）
│ /safety-setup ───→ 盤點專案，寫 .ai-review/config.md
│ 開發、驗收功能
│ /review-ready ───→ 釘版本（指紋＋git 快照）
│                    跑 config.md 的檢查、照實記錄
│                    寫交接 H-xxx.md → 狀態「待獨立審查」
│ 開 Codex，打 $independent-review ───────────────────→ 核對指紋、讀 diff 與完整程式碼
│                                                        寫審查 R-xxx.md（needs-fix / no-blocking-found）
│ /review-fix R-xxx → 逐項修、寫 F-xxx.md、重新交接 → 狀態「待複查」→ 再讓 Codex 審
│ 合併前：py -3 .ai-review/kit/kit.py gate
```

五種狀態：尚未準備 → 待獨立審查 → 需修正 → 待複查 → 本次範圍內未發現阻擋問題。全部由報告檔頭＋目前程式碼指紋**推導**，不是誰宣告的。細節：`core/workflow.md`。

## 套件內容

```
ai-review-kit/
├ README.md、VERSION、CHANGELOG.md
├ core/            通用規範（工具中立的 Markdown）
│  ├ workflow.md            總覽、狀態推導、版本綁定、硬規則
│  ├ security-checklist.md  對應 OWASP ASVS 5.0.0 的檢查清單與設計檢查六題
│  ├ handoff-spec.md        交接規範（review-ready）
│  ├ review-spec.md         獨立審查規範（Codex 必讀）
│  └ fix-spec.md            修正規範（review-fix）
├ templates/       config.md、handoff.md、review.md、fix.md、entry-claude.md、entry-agents.md
├ claude/skills/   safety-setup、review-ready、review-fix（Claude Code Skills）
├ codex/skills/    independent-review（Codex Skill，裝到專案 .agents/skills/）
├ tools/kit.py     安裝／更新／狀態／還原／打包 ＋ 專案內的快照／檢查／狀態／關卡／hook
├ tools/tests/     自動化驗證（暫存專案，67 個檢查點）
└ docs/            codex-start.md（讓 Codex 接手）、daily-usage.md（日常）、offline-setup.md（帶到不能連 GitHub 的電腦）
```

## 安裝（專案層級）

需求：Python 3.9+（純標準函式庫）、git（非 git 專案也能用，能力較弱）。Windows 用 `py -3`，macOS／Linux 用 `python3`。

```
py -3 <套件路徑>/tools/kit.py install --target <專案根目錄>
```

安裝會：
- 複製規範、範本、工具到 `<專案>/.ai-review/kit/`（專案自帶副本，換電腦不依賴中央路徑）
- 放 Skills 到 `.claude/skills/`（Claude）與 `.agents/skills/`（Codex）
- 在 `CLAUDE.md`、`AGENTS.md` **附加**一個管理區塊（`<!-- ai-review-kit:begin … end -->`），區塊外的內容不動
- 在 `.claude/settings.json` 合併兩個 hook（SessionStart、Stop），其他設定不動；`.codex/hooks.json` 加一個 SessionStart（Codex 端需在 `/hooks` 信任後才會跑）
- `.gitignore` 加 `.ai-review/.cache/`、`.ai-review/.backup/`、`.ai-review/local.json`
- 記錄到 `.ai-review/kit-version.json`（進版控，不含本機路徑）；這台電腦的直譯器與套件來源記在 `.ai-review/local.json`（不進版控）；改動前的檔案備份到 `.ai-review/.backup/<時間>/`

然後在專案根目錄開 Claude Code（hooks 要重開才載入），執行 `/safety-setup`。

其他指令：

| 指令 | 用途 |
|---|---|
| `install --preview` | 只看會動哪些檔案與差異，不寫入 |
| `update --source <資料夾或 zip> [--preview]` | 更新；三方比對（安裝時／目前／新來源），使用者改過的保留，兩邊都改的列為衝突不覆蓋，`--take-source <路徑>` 才採用來源 |
| `status` | 套件版本、來源版本、使用者改過哪些檔、hooks／Skills／入口是否就位、目前流程狀態 |
| `restore --yes` | 還原最近一次安裝／更新前的狀態（先列清單）；可逐次往前還原 |
| `relink [--python "py -3"]` | 換電腦後重寫 hook 的直譯器、重建 `local.json` |
| `pack` | 打離線 zip 到 `dist/` |
| `check-update --url <VERSION 檔網址>` | 只查版本號，不自動更新；沒網路就如實說「未檢查更新」 |

## 日常只要記住

| 時機 | 做什麼 |
|---|---|
| 新專案一次 | `/safety-setup` |
| 一個變更做完 | `/review-ready` |
| 要獨立審查 | 開 Codex，打 `$independent-review`（見 `docs/codex-start.md`） |
| 審查說要修 | `/review-fix R-編號` |
| 合併／部署前 | `py -3 .ai-review/kit/kit.py gate` |
| 想看狀態 | `py -3 .ai-review/kit/kit.py status` |

## 更新套件（跨電腦）

- 中央版本放在你自己的地方（例如這個資料夾的 git repo、或 `pack` 出來的 zip）。
- 每個專案記錄自己用的版本（`.ai-review/kit-version.json`）。
- 更新一律 `update --source … --preview` 先看，再 `update --source …`。不會覆寫整個 `.claude/` 或 `.codex/`，不會碰登入資訊、對話紀錄、金鑰、專案資料。
- 不能連 GitHub 的電腦：帶 zip 過去，`install --source <zip>`；工具不會上傳任何東西。見 `docs/offline-setup.md`。

## 限制（誠實版）

- hook 只做機械判斷（版本、指紋是否相符、有沒有未結案）。它不掃描程式碼、不呼叫另一個 AI、不能擋住 push 或部署。
- `gate` 是本地檢查，可以被略過。要強制，得在 GitHub 設 branch protection 並讓 CI 跑 gate（`templates/ci/github-actions-gate.yml` 是範例，尚未在真實 repo 驗證）。
- 狀態檔與報告裡的「通過」文字不是安全證明；證明是「哪個指紋、誰審、看了什麼、怎麼查」。
- 非 git 專案沒有快照參照，指紋改用檔案雜湊。
- Codex 端的 Skill 與 hook 依官方文件位置放置，但本套件的驗證未實際啟動 Codex（第一版由使用者手動啟動），列為未驗證。
- 指紋在 CI 與本機可能因 CRLF 正規化設定不同而不一致（`core.autocrlf` 混用時）；遇到就以本機為準並在 CI 停用 gate。

## 驗證

```
py -3 tools/tests/test_kit.py
```
在暫存資料夾建立多個測試專案，覆蓋：新專案安裝、既有 CLAUDE.md／AGENTS.md／settings.json 保留、重複安裝不重複插入、更新衝突不覆蓋、還原、程式變更使審查過期、hook 不迴圈不重複、檢查命令結果分明、離線 zip 安裝、非 git 專案、無網路時的 check-update。測試資料夾不會自動刪除。
