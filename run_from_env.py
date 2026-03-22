"""GitHub Actionsから実行されるスクリプト"""
import json
import os
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build

from save_article import fetch_article, format_article

SCOPES = ["https://www.googleapis.com/auth/documents"]
DOCUMENT_ID = os.environ["DOCUMENT_ID"]
SERVICE_ACCOUNT_JSON = os.environ["SERVICE_ACCOUNT_JSON"]
URLS = json.loads(os.environ["URLS"])


def get_docs_service():
    info = json.loads(SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("docs", "v1", credentials=creds)


def append_to_doc(docs_service, articles):
    doc = docs_service.documents().get(documentId=DOCUMENT_ID).execute()
    end_index = doc["body"]["content"][-1]["endIndex"] - 1

    text_to_insert = ""
    for title, body, url, saved_at in articles:
        text_to_insert += format_article(title, body, url, saved_at)

    docs_service.documents().batchUpdate(
        documentId=DOCUMENT_ID,
        body={"requests": [{"insertText": {"location": {"index": end_index}, "text": text_to_insert}}]}
    ).execute()


def main():
    articles = []
    for url in URLS:
        print(f"取得中: {url}")
        try:
            title, body = fetch_article(url)
            saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            articles.append((title, body, url, saved_at))
            print(f"  ✅ {title}")
        except Exception as e:
            print(f"  ❌ エラー: {e}")

    if articles:
        print("Google Documentに保存中...")
        service = get_docs_service()
        append_to_doc(service, articles)
        print(f"✅ 完了: {len(articles)}件保存しました")
    else:
        print("保存できる記事がありませんでした")


if __name__ == "__main__":
    main()
