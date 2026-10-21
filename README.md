# 籌碼觀測站

台指選擇權籌碼動向儀表板，太空科幻風格介面，透過 GitHub Actions 排程自動更新資料。

## 架構說明

- `fetch_data.py`：由 GitHub Actions 執行的資料抓取腳本，跑在 GitHub 的伺服器上，
  不受瀏覽器 CORS 限制，抓完寫成 `data.json`。
- `.github/workflows/update-data.yml`：排程設定，預設每個交易日台北時間下午2:30自動跑一次，
  也可以手動觸發（Actions 分頁 → 選這個workflow → Run workflow）。
- `index.html`：實際顯示的網頁，讀取「同一個網站裡」的 `data.json`（同源讀取，
  瀏覽器不會擋），不會直接對期交所發請求。

## 部署步驟

1. 在 GitHub 建立一個新的 public repository（例如叫 `options-observatory`）。
2. 把這個資料夾裡的三個東西（`fetch_data.py`、`index.html`、`.github/workflows/update-data.yml`，
   注意 `.github` 資料夾結構要保留）全部上傳到這個 repo 的根目錄。
   網頁版操作：進 repo → "Add file" → "Upload files"，把檔案（含資料夾結構）拖進去即可，
   不需要用命令列。
3. 進 repo 的 **Settings → Pages**，Source 選 "Deploy from a branch"，
   Branch 選 `main`、資料夾選 `/ (root)`，存檔。等一兩分鐘後會出現一個網址，
   長得像 `https://你的帳號.github.io/options-observatory/`，這就是你的網站。
4. 進 repo 的 **Settings → Actions → General**，往下找到 "Workflow permissions"，
   選 "Read and write permissions"，存檔。（這一步是讓機器人有權限把 `data.json`
   寫回你的 repo，沒開這個權限，排程會失敗。）
5. 進 **Actions** 分頁，應該會看到 "Update options chip data" 這個 workflow，
   點進去手動按一次 "Run workflow"，確認它能成功跑完、且 repo 裡真的多了一個 `data.json`。
6. 打開步驟3拿到的網址，應該就能看到資料了。之後排程會照設定的時間自動更新，
   你不用再手動做任何事。

## 我可以確認到的程度

- `index.html` 讀取 `./data.json` 這件事，因為是同源讀取，不會被瀏覽器CORS擋——這件事在原理上是確定的。
- `fetch_data.py` 裡解析期交所資料的欄位名稱，已經用真實回傳資料核對過（見對話中的除錯截圖）。
- GitHub Actions 排程本身能不能順利跑起來、寫回 repo 成不成功，這需要你實際照著上面步驟做一次
  才能確認——我沒有 GitHub 帳號可以先幫你跑過。如果步驟5卡住，把 Actions 分頁裡的錯誤訊息貼給我。

## 太空人 Chasel 盤後雷達（/flow/）

網址：`https://chasel1201.github.io/Chasel-Stock/flow/`

- `fetch_flow.py`：抓證交所、櫃買中心 OpenAPI 的盤後行情與公司基本資料，算出大產業／細產業資金流向與籌碼強勢股，寫成 `flow/flow.json`。
- `flow/history.json`：保存每日各產業成交占比，用來算「占比變化（pp）」，所以第二個交易日起才會有 pp。
- `sub_industries.json`：細產業（概念股）分組，可自行增刪股票代號。
- `flow/index.html`：網頁本體，讀取同資料夾的 `flow.json`。
- 排程：每個交易日台北時間 16:40 跑一次，18:10 再補跑一次。也可以在 Actions 分頁手動 Run workflow。
- 強勢股條件：周轉率 ≥ 10%、成交量 ≥ 1 萬張、漲幅 ≥ 3%（寫在 `fetch_flow.py` 最上方，可修改）。

## 盤後短線報告／波段報告

- 網址：盤後雷達的「籌碼強勢股」分頁，每檔股票有「盤後報告」按鈕，上方搜尋框可查任何上市櫃普通股
- 程式：`fetch_reports.py`，排程：`.github/workflows/update-reports.yml`（每個交易日 16:55、18:25 自動執行）
- 歷史資料：`reports_data/ohlc.json`（保留近 130 個交易日），報告輸出：`flow/reports/<代號>.json`
- 第一次使用或資料中斷：到 Actions →「Update stock reports」→ Run workflow，`backfill` 填 `120`
