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
