#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
移転企業チェック(東京23区・場所×人数タグ)

Google ニュースのRSS検索を使って、東京23区内の企業移転ニュースを探し、
場所(建物名 > エリア名 > 区名 > 23区)と従業員数の2軸でタグを付けて
Gmail経由でメール通知する。GitHub Actionsから1時間おきに実行される想定。

外部ライブラリは使わず、標準ライブラリのみで動作する。
"""

import os
import re
import json
import html
import smtplib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

# ── 検索条件 ──────────────────────────────────────────
KEYWORDS = ["本社移転", "本店移転", "事務所移転", "移転 発表"]
LOOKBACK_MINUTES = 75  # 1時間おき実行に対して少し幅を持たせる(取りこぼし防止)

# ── 場所タグの条件(優先度は数字が小さいほど高い) ──────────
BUILDINGS = [
    "日本橋野村三井タワー", "TOFROM YAESU", "WORK VILLA YAESU", "東京京橋ビル",
    "ヒューリック西銀座ビル", "銀座天國ビル", "日本橋3丁目4-13", "本町1丁目3",
    "日本橋本町三井ビルディング", "日本橋本町2丁目7-1", "日本橋本町3-9",
    "日本橋東鉱ビル", "スイテ日本橋人形町", "REVZO西新橋", "TOKYO TORCH",
    "Torch Tower", "YAESU CORE",
]
AREAS = ["京橋", "八重洲", "日本橋"]
PRIORITY_WARDS = ["中央区", "千代田区"]
WARDS_TOKYO23 = [
    "千代田区", "中央区", "港区", "新宿区", "文京区", "台東区", "墨田区", "江東区",
    "品川区", "目黒区", "大田区", "世田谷区", "渋谷区", "中野区", "杉並区", "豊島区",
    "北区", "荒川区", "板橋区", "練馬区", "足立区", "葛飾区", "江戸川区",
]

SEEN_FILE = os.path.join(os.path.dirname(__file__), "seen.json")
MAX_SEEN = 1500


# ── 既知アイテムの記録(重複通知防止) ──────────────────────
def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"seen": []}


def save_seen(data):
    data["seen"] = data["seen"][-MAX_SEEN:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Google ニュース RSS 検索 ──────────────────────────────
def fetch_google_news_rss(query):
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(query) + "&hl=ja&gl=JP&ceid=JP:ja"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read()
    root = ET.fromstring(data)
    items = []
    for item in root.findall(".//item"):
        items.append({
            "title": item.findtext("title") or "",
            "link": item.findtext("link") or "",
            "pubDate": item.findtext("pubDate") or "",
            "source": item.findtext("source") or "",
        })
    return items


def parse_pubdate(pubdate_str):
    try:
        dt = parsedate_to_datetime(pubdate_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(JST)
    except Exception:
        return None


def strip_tags(raw_html):
    text = re.sub(r"<[^>]+>", " ", raw_html)
    return html.unescape(text)


def fetch_article_text(google_news_link):
    """Googleニュースのリンク先(元記事)を取得し、タグを除去したテキストを返す。
    取得に失敗した場合は空文字を返す(致命的エラーにしない)。"""
    req = urllib.request.Request(google_news_link, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            final_url = resp.geturl()
            raw = resp.read().decode("utf-8", errors="ignore")
        return final_url, strip_tags(raw)
    except Exception:
        return google_news_link, ""


# ── 従業員数の抽出(ベストエフォート) ─────────────────────
def extract_employee_count(text):
    for pattern in [
        r"従業員数[\s:：]*([0-9,]+)\s*名",
        r"従業員[\s:：]*([0-9,]+)\s*名",
        r"社員数[\s:：]*([0-9,]+)\s*名",
    ]:
        m = re.search(pattern, text)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


# ── 場所ラベルの判定(優先度が高いものを1つ採用) ────────────
def detect_place(text):
    for b in BUILDINGS:
        if b in text:
            return (1, b)
    for a in AREAS:
        if a in text:
            return (2, a)
    for w in PRIORITY_WARDS:
        if w in text:
            return (3, w)
    for w in WARDS_TOKYO23:
        if w in text:
            return (4, "23区")
    return None  # 東京23区に該当しない場合は対象外


def headcount_label(count):
    if count is None:
        return (4, "人数不明")
    if count <= 50:
        return (3, "50名以下")
    if count <= 100:
        return (2, "50〜100名")
    if count <= 300:
        return (1, "100〜300名")
    return (0, "300名以上")


# ── メール作成・送信 ──────────────────────────────────────
def build_email(hits):
    best = min(hits, key=lambda h: (h["place_rank"], h["count_rank"]))
    subject_tag = f"{best['place_label']}・{best['count_label']}"
    subject = f"【{subject_tag}】移転企業チェック({len(hits)}件)"

    lines = []
    for h in hits:
        lines.append(
            f"・{h['company']}\n"
            f"  タグ: {h['place_label']}・{h['count_label']}\n"
            f"  従業員規模: {h['count_text']}\n"
            f"  タイトル: {h['title']}\n"
            f"  情報源: {h['link']}\n"
        )
    body = "\n".join(lines)
    return subject, body


def send_email(subject, body):
    gmail_user = os.environ["GMAIL_ADDRESS"]
    gmail_pass = os.environ["GMAIL_APP_PASSWORD"]
    to_addr = os.environ["TO_EMAIL"]

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_addr

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, [to_addr], msg.as_string())


# ── メイン処理 ────────────────────────────────────────────
def main():
    seen_data = load_seen()
    seen_links = set(seen_data["seen"])
    now = datetime.now(JST)
    cutoff = now - timedelta(minutes=LOOKBACK_MINUTES)

    candidates = {}
    for kw in KEYWORDS:
        query = f'"{kw}" 東京'
        try:
            items = fetch_google_news_rss(query)
        except Exception as e:
            print(f"[warn] 検索失敗: {kw}: {e}")
            items = []
        for it in items:
            if it["link"] in seen_links or it["link"] in candidates:
                continue
            pub = parse_pubdate(it["pubDate"])
            if pub is None or pub < cutoff:
                continue
            candidates[it["link"]] = it

    hits = []
    for link, it in candidates.items():
        final_url, article_text = fetch_article_text(link)
        combined_text = it["title"] + " " + article_text

        place = detect_place(combined_text)
        seen_links.add(link)  # 一度判定した記事は今後スキップする

        if place is None:
            continue  # 東京23区に該当しない

        place_rank, place_label = place
        count = extract_employee_count(combined_text)
        count_rank, count_label = headcount_label(count)
        company = it["source"] or it["title"]

        hits.append({
            "company": company,
            "title": it["title"],
            "place_label": place_label,
            "place_rank": place_rank,
            "count_label": count_label,
            "count_rank": count_rank,
            "count_text": (f"{count}名" if count else "不明"),
            "link": final_url,
        })

    if hits:
        subject, body = build_email(hits)
        send_email(subject, body)
        print(f"[info] {len(hits)}件検知、メール送信しました: {subject}")
    else:
        if os.environ.get("REPORT_ON_ZERO", "false").lower() == "true":
            subject = "【実行報告】移転企業チェック(0件)"
            body = (
                f"{now.strftime('%Y-%m-%d %H:%M')}(JST) 実行。\n"
                f"今回のチェックでは、直近{LOOKBACK_MINUTES}分以内の東京23区の移転ニュースは"
                f"見つかりませんでした。タスクは正常に動作しています。"
            )
            send_email(subject, body)
            print("[info] 0件のため実行報告メールを送信しました")
        else:
            print("[info] 0件、メールなし")

    seen_data["seen"] = list(seen_links)
    save_seen(seen_data)


if __name__ == "__main__":
    main()
