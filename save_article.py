import argparse
import json
import os
import sys
from datetime import datetime

# Windows端末の文字コード問題を回避
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import requests
import trafilatura
from bs4 import BeautifulSoup

SCOPES = ["https://www.googleapis.com/auth/documents"]
SEPARATOR = "━" * 40
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config():
    config_path = os.path.join(SCRIPT_DIR, "config.json")
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def save_config(config):
    config_path = os.path.join(SCRIPT_DIR, "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def format_article(title, body, url, saved_at):
    return f"\n{SEPARATOR}\n【{title}】\n保存日時: {saved_at}\nURL: {url}\n\n{body}\n"


def get_google_creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_path = os.path.join(SCRIPT_DIR, "token.json")
    creds_path = os.path.join(SCRIPT_DIR, "credentials.json")
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def parse_html(html, url):
    """HTMLからタイトルと本文を抽出する共通処理"""
    soup = BeautifulSoup(html, "html.parser")

    # タイトル取得
    title = None
    if soup.find("meta", property="og:title"):
        title = soup.find("meta", property="og:title").get("content", "").strip()
    if not title and soup.title:
        title = soup.title.get_text(strip=True)
    if not title:
        title = url

    # 本文をtrafilaturaで抽出
    body = trafilatura.extract(html, include_comments=False, include_tables=False)

    # フォールバック: <article> or <main> タグから本文取得
    if not body:
        for tag in ["article", "main"]:
            el = soup.find(tag)
            if el:
                body = el.get_text(separator="\n", strip=True)
                break
    if not body:
        body = "（本文を取得できませんでした）"

    return title, body


def fetch_with_curl_cffi(url):
    """curl_cffiを使ってブラウザのTLSフィンガープリントを偽装して取得する"""
    from curl_cffi import requests as cf_requests
    resp = cf_requests.get(url, impersonate="chrome120", timeout=30)
    resp.raise_for_status()
    return resp.text


def fetch_article(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.text
    except requests.HTTPError as e:
        if e.response.status_code in (403, 429):
            # ブロックされた場合はcurl_cffiでリトライ
            html = fetch_with_curl_cffi(url)
        else:
            raise

    return parse_html(html, url)


def create_doc(drive_service, doc_title, folder_id=None):
    """Google Driveに新しいDocumentを作成してIDを返す"""
    metadata = {
        "name": doc_title,
        "mimeType": "application/vnd.google-apps.document",
    }
    if folder_id:
        metadata["parents"] = [folder_id]
    file = drive_service.files().create(body=metadata, fields="id").execute()
    return file["id"]


def append_to_doc(docs_service, doc_id, articles):
    # ドキュメントの末尾インデックスを取得
    doc = docs_service.documents().get(documentId=doc_id).execute()
    end_index = doc["body"]["content"][-1]["endIndex"] - 1

    text_to_insert = ""
    for title, body, url, saved_at in articles:
        text_to_insert += format_article(title, body, url, saved_at)

    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{"insertText": {"location": {"index": end_index}, "text": text_to_insert}}]}
    ).execute()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Google Docsに保存せずターミナルにプレビュー表示")
    args = parser.parse_args()

    if not args.test:
        config = load_config()
        doc_id = config.get("document_id", "")
        if doc_id == "YOUR_GOOGLE_DOC_ID":
            doc_id = ""
            config["document_id"] = ""

    print("URLを入力してください（空行で処理開始）:")
    urls = []
    count = 1
    while True:
        line = input(f"  {count}: ").strip()
        if not line:
            break
        urls.append(line)
        count += 1

    if not urls:
        print("URLが入力されませんでした。終了します。")
        return

    # 記事取得
    articles = []
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] 取得中... ", end="", flush=True)
        try:
            title, body = fetch_article(url)
            saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            articles.append((title, body, url, saved_at))
            print(f'✅ 「{title}」')
        except Exception as e:
            print(f"❌ エラー: {e}")

    if not articles:
        print("保存できる記事がありませんでした。")
        return

    if args.test:
        # テストモード: ターミナルにプレビュー表示
        print("\n" + "=" * 50)
        print("【プレビュー】Google Documentに追記される内容:")
        print("=" * 50)
        for title, body, url, saved_at in articles:
            print(format_article(title, body, url, saved_at))
        return

    # Google Docs に追記
    print("Google Documentに保存中...", end="", flush=True)
    creds = get_google_creds()
    from googleapiclient.discovery import build as gdoc_build
    docs_service = gdoc_build("docs", "v1", credentials=creds)
    drive_service = gdoc_build("drive", "v3", credentials=creds)

    # document_idが未設定の場合は新規作成
    if not doc_id:
        folder_id = config.get("folder_id") or None
        doc_title = config.get("document_title", "記事保存")
        doc_id = create_doc(drive_service, doc_title, folder_id)
        config["document_id"] = doc_id
        save_config(config)
        print(f"\n新しいDocumentを作成しました (ID: {doc_id})")
        print("保存中...", end="", flush=True)

    append_to_doc(docs_service, doc_id, articles)
    print(f" ✅ 完了: {len(articles)}件をドキュメントに保存しました")


if __name__ == "__main__":
    main()
