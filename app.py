import json
import os

from flask import Flask, render_template, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build

from save_article import fetch_article, format_article
from datetime import datetime

app = Flask(__name__)

SCOPES = ["https://www.googleapis.com/auth/documents"]
DOCUMENT_ID = os.environ.get("DOCUMENT_ID", "")
SERVICE_ACCOUNT_JSON = os.environ.get("SERVICE_ACCOUNT_JSON", "")
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "")


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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/save", methods=["POST"])
def save():
    data = request.get_json()

    if ACCESS_PASSWORD and data.get("password") != ACCESS_PASSWORD:
        return jsonify({"error": "パスワードが違います"}), 403

    urls = [u.strip() for u in data.get("urls", []) if u.strip()]
    if not urls:
        return jsonify({"error": "URLが入力されていません"}), 400

    results = []
    articles = []
    for url in urls:
        try:
            title, body = fetch_article(url)
            saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            articles.append((title, body, url, saved_at))
            results.append({"url": url, "title": title, "status": "ok"})
        except Exception as e:
            results.append({"url": url, "error": str(e), "status": "error"})

    if articles:
        try:
            service = get_docs_service()
            append_to_doc(service, articles)
        except Exception as e:
            return jsonify({"error": f"Google Docsへの保存に失敗: {e}", "results": results}), 500

    return jsonify({"results": results})


if __name__ == "__main__":
    app.run(debug=False)
