# Gmail OAuth で「redirect_uri_mismatch」が出るとき

`send_daily_report.py` の初回実行で **Error 400: redirect_uri_mismatch** が出る場合は、Google Cloud の「承認済みリダイレクト URI」に、スクリプトが使う URI を追加する必要があります。

## 手順

1. **Google Cloud Console** を開く  
   https://console.cloud.google.com/

2. **プロジェクトを選択**（Gmail API を有効にしたプロジェクト）

3. **API とサービス** → **認証情報**

4. 使っている **OAuth 2.0 クライアント ID**（「デスクトップ アプリ」など）をクリック

5. **承認済みのリダイレクト URI** に次の **2 つ** を追加して保存  
   - `http://localhost:8080/`  
   - `http://127.0.0.1:8080/`

6. もう一度 `python send_daily_report.py` を実行する

---

**注意**: 8080 番が別のアプリで使われている場合は、スクリプト内の `port=8080` を別の番号（例: 9090）に変え、上記の `8080` もその番号に合わせて追加してください。
