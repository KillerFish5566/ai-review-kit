# 變更紀錄

版本規則：patch＝修 bug 不改行為；minor＝加功能且舊專案資料相容；major＝專案資料需轉換或使用方式改變。
每次發版：改 `VERSION`、在這裡加一段、`kit.py pack` 重打離線包。

## 0.1.2 — 2026-09-26

修正：`install／update --preview` 漏列設定與紀錄檔（第二台電腦 2026-09-21 回報）。

- 預覽原本只列套件檔與入口區塊（20 項），實裝另外會寫 `.claude/settings.json`（SessionStart、Stop hook）、`.codex/hooks.json`、`.gitignore`、三個 `.gitkeep` 與 `kit-version.json`／`local.json`／`state.json`。現在另起一張「設定與紀錄檔」表全部列出，兩個 hook 設定檔附安裝前後差異。
- 這些檔的內容改為在預覽前就算好，實裝照同一份內容寫入，預覽與實裝不會對不上。
- 測試 78 → 81 項（新增 T16：預覽不寫檔、實裝寫入的每個檔都出現在預覽、hook 差異有顯示）。

## 0.1.1 — 2026-09-19

修正：安裝後進版控的檔案會帶出本機路徑（含 Windows 使用者名稱）。

- 直譯器與套件來源路徑改存 `.ai-review/local.json`（自動加進 `.gitignore`），`kit-version.json` 不再記這兩項。
- hook 預設直譯器改用 PATH 上的通用命令（Windows `py -3`、其他 `python3`），不再寫 `sys.executable` 的絕對路徑；`--python` 指定的值照用，路徑在使用者資料夾內會提出警告。
- Claude Code hook 的 kit.py 路徑改寫 `${CLAUDE_PROJECT_DIR}/.ai-review/kit/kit.py`（實測 exec 形式會展開），不再寫專案的絕對路徑。
- 從 0.1.0 升級：舊欄位自動搬走；0.1.0 自動記下的絕對直譯器路徑不沿用，改用通用命令。
- 從 zip 安裝時記住的來源改為 zip 檔本身（原本記到會被清掉的暫存資料夾）。
- `.gitignore` 補新行時接在既有區段後面，不再重複標題。
- 測試 67 → 78 項（T12 補一項、新增 T13～T15）。

## 0.1.0 — 2026-09-18

第一版。

- 核心規範五份（`core/`）：總覽與狀態推導、安全檢查清單（對應 OWASP ASVS 5.0.0）、交接規範、獨立審查規範、修正規範。
- 範本七份（`templates/`）：專案設定、交接／審查／修正報告、Claude 與 Codex 入口區塊。
- Claude Code Skills 三個：`/safety-setup`、`/review-ready`、`/review-fix`。
- Codex Skill 一個：`$independent-review`。
- 工具 `tools/kit.py`（純 Python 標準函式庫）：install／update／status／restore／pack／check-update，以及專案內的 snapshot／checks／state／verify／gate／hook。
- hooks：Claude Code 的 SessionStart（顯示版本、初始化、狀態、未結案）與 Stop（交接過期提醒，每個指紋只提醒一次，永不阻擋）；Codex 的 SessionStart（同內容，未實測）。
- 狀態由報告檔頭與程式碼指紋推導，`.ai-review/` 不計入指紋，所以寫報告不會讓狀態過期。
