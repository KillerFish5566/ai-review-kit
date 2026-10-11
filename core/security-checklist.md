# 通用安全檢查清單（依 OWASP ASVS 5.0.0 對應）

> OWASP ASVS（Application Security Verification Standard）是一份「應用程式安全要驗證哪些事」的公開標準。
> 本檔對應 **ASVS 5.0.0（2025 年 5 月）** 的 17 章，只取「這種專案用得到」的部分。專案實際勾選哪些，寫在 `.ai-review/config.md` 第 2 節。
> 原文：https://github.com/OWASP/ASVS （5.0/en 目錄）。本檔是摘要與對應表，不是原文替代品。

## 1. 先判斷專案是哪一種（決定哪些章適用）

| 類型 | 例子 | 通常適用的章 |
|---|---|---|
| A 本機工具／腳本／桌面程式 | Revit 外掛、批次轉檔、單機小工具 | V1、V2、V5、V11（若加密）、V13、V14、V15、V16 |
| B 有帳號的網站或 API | 使用者登入、後台、行動 App 後端 | 幾乎全部（V17 只在有即時音訊視訊時） |
| C 內部自動化／CI／agent 工具 | 讀寫 GitHub、呼叫 LLM、排程任務 | V1、V2、V4、V5、V8、V11、V12、V13、V14、V15、V16 |
| D 靜態內容／純前端 | GitHub Pages、無後端的頁面 | V3、V12、V13、V14、V15 |

判斷依據：有沒有「使用者」、有沒有「對外開放」、有沒有「別人的資料」。三個都沒有就是 A。

## 2. 重大變更的設計檢查（動到這些先想，再寫碼）

動到**登入、權限、敏感資料、對外介面**任一項時，在寫程式前先回答：

1. 誰能呼叫這個入口？未登入的人能不能？別的角色能不能？
2. 這個入口拿到的每個參數，攻擊者能改成什麼？改了會怎樣？
3. 這個入口碰到的資料屬於誰？怎麼確定呼叫者有權看／改？
4. 需要秘密（token、密碼、連線字串）嗎？放哪裡？誰讀得到？
5. 失敗時會洩漏什麼（錯誤訊息、堆疊、路徑）？
6. 這個改動有沒有關掉或繞過既有的檢查？

答不出來的，記到 config.md 第 6 節「未驗證事項」，不要假裝已考慮。

## 3. 逐章對應（適用時逐條看）

| ASVS 5.0 章 | 一句白話 | 這種專案最常見的檢查點 |
|---|---|---|
| V1 Encoding and Sanitization（編碼與淨化） | 輸出到哪裡就用哪裡的編碼 | SQL 用參數化；命令列用參數陣列不拼字串；HTML 用範本自動跳脫；路徑用 `os.path` 正規化並限制在根目錄內 |
| V2 Validation and Business Logic（驗證與商業邏輯） | 輸入在進門時就檢查 | 型別、長度、範圍、白名單；流程順序不能被跳步（先付款再出貨） |
| V3 Web Frontend Security（前端安全） | 瀏覽器層的防線 | CSP、Cookie 屬性（HttpOnly／Secure／SameSite）、避免 `innerHTML` 塞未處理內容 |
| V4 API and Web Service（API） | API 也是入口 | 每個端點都有驗證與授權；拒絕未預期的 Content-Type；限流 |
| V5 File Handling（檔案處理） | 檔名與內容都是不可信輸入 | 上傳限制型別與大小；存到使用者選的路徑前先正規化；解壓縮防路徑穿越（zip slip） |
| V6 Authentication（身分驗證） | 證明你是你 | 密碼雜湊（argon2／bcrypt）；不自己發明登入；失敗次數限制；不用 API 直接 OAuth 走現成函式庫 |
| V7 Session Management（工作階段） | 登入後的通行證 | 登出要真的失效；逾時；隨機且夠長的 session id |
| V8 Authorization（授權） | 你能做什麼 | **每次**存取都檢查（不是只在選單隱藏）；物件層級授權（改 id 不能拿到別人的） |
| V9 Self-contained Tokens（自含式權杖，如 JWT） | 權杖裡的內容要驗簽 | 驗簽名與演算法；驗 `exp`／`aud`；不接受 `alg: none` |
| V10 OAuth and OIDC | 第三方登入 | 驗 `state`／PKCE；redirect URI 白名單 |
| V11 Cryptography（密碼學） | 用對演算法、管好金鑰 | 不自己寫加密；金鑰不進 git；隨機數用 CSPRNG |
| V12 Secure Communication（安全通訊） | 傳輸加密 | 全部 HTTPS；不關閉憑證驗證（`verify=False` 是紅燈） |
| V13 Configuration（設定） | 出廠設定也要安全 | 沒有 debug 開關留在正式環境；秘密走環境變數或秘密管理；依賴套件有來源與版本鎖定；已知漏洞掃描（`pip-audit`／`npm audit`／`dotnet list package --vulnerable`） |
| V14 Data Protection（資料保護） | 敏感資料的存放與流向 | 個資／公司資料最小化；不記進 log；本機快取有沒有加密或至少放對位置 |
| V15 Secure Coding and Architecture（安全編碼與架構） | 結構本身要安全 | 依賴方向單一；第三方元件清單；不安全的反序列化；競態條件 |
| V16 Security Logging and Error Handling（日誌與錯誤處理） | 該記的記、不該記的不記 | 登入失敗、權限拒絕要記；密碼、token、個資不記；錯誤訊息對外不含堆疊 |
| V17 WebRTC | 即時音訊視訊 | 幾乎不適用；有才看 |

## 4. 不分類型一律要看的（最低限度）

- 秘密掃描：程式碼、設定、註解、測試資料、git 歷史。工具例：`gitleaks detect --no-banner --redact`（有裝才用，沒裝就記「未執行」；`--redact` 讓輸出遮蔽金鑰原文，不讓它進 checks 紀錄與交接報告）。
- 依賴漏洞：對應語言的 audit 指令；沒網路就記「未執行」。
- `.gitignore` 是否涵蓋 `.env`、`*.local.*`、`credentials*`、IDE 個人設定、含使用者名稱的絕對路徑。機密與 AI 逐字稿的標準清單用 `kit.py ignore-check` 檢查（唯讀，不改 `.gitignore`）。
- 含 Windows 使用者名稱或公司名的絕對路徑不得進入會公開的 repo。
- 新增的對外入口（HTTP 端點、命令列參數、檔案匯入）都在 config.md 第 1 節登記過。

## 5. 不要做的事

- 不要為了「檢查數量」加沒有斷言的測試、或只是呼叫函式不驗結果的測試。
- 不要把「靜態掃描 0 個發現」當成安全證明；掃描器只看它會看的。
- 不要因為導入本流程而移除專案既有的 lint、測試、pre-commit、CI 檢查。
