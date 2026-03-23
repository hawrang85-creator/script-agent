#!/usr/bin/env python3
"""
트렌드 콘텐츠 수집기 (Trending Content Scraper)

국방, 기술, K-푸드 분야의 최신 트렌드를 웹에서 수집하여
input/ 폴더에 JSON 및 마크다운 형식으로 저장합니다.

사용법:
    python3 collect_trends.py                  # 전체 카테고리 수집
    python3 collect_trends.py --category 국방   # 특정 카테고리만 수집
    python3 collect_trends.py --category 기술
    python3 collect_trends.py --category K-푸드
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error
import ssl
from datetime import datetime
from html.parser import HTMLParser


# ─────────────────────────────────────────────
# 검색 키워드 설정
# ─────────────────────────────────────────────
SEARCH_QUERIES = {
    "국방": [
        "한국 국방 트렌드 최신 뉴스",
        "한국 방산 수출 최신",
        "한미동맹 국방 전략",
        "한국 드론 군사 기술",
    ],
    "기술": [
        "한국 AI 반도체 트렌드 최신",
        "삼성전자 SK하이닉스 반도체 최신",
        "한국 AI 스타트업 투자",
        "자율주행 로봇 피지컬AI 한국",
    ],
    "K-푸드": [
        "K-food 한국 음식 트렌드 해외 인기",
        "한식 글로벌 수출 트렌드",
        "K-푸드 해외 반응 최신",
        "한국 식품 스타트업 푸드테크",
    ],
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "input")


# ─────────────────────────────────────────────
# HTML 텍스트 추출용 파서
# ─────────────────────────────────────────────
class TextExtractor(HTMLParser):
    """HTML에서 텍스트만 추출하는 간단한 파서"""

    def __init__(self):
        super().__init__()
        self._texts = []
        self._skip_tags = {"script", "style", "noscript"}
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip = True

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self._texts.append(text)

    def get_text(self):
        return " ".join(self._texts)


def extract_text_from_html(html: str) -> str:
    parser = TextExtractor()
    parser.feed(html)
    return parser.get_text()


# ─────────────────────────────────────────────
# 웹 검색 (Google 검색 결과 스크래핑)
# ─────────────────────────────────────────────
def fetch_url(url: str, timeout: int = 10) -> str:
    """URL에서 HTML을 가져옵니다."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"  [경고] URL 접근 실패: {url} ({e})")
        return ""


class GoogleResultParser(HTMLParser):
    """Google 검색 결과에서 제목과 링크를 추출합니다."""

    def __init__(self):
        super().__init__()
        self.results = []
        self._in_h3 = False
        self._current_link = None
        self._current_title = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "a":
            href = attrs_dict.get("href", "")
            if href.startswith("/url?q="):
                # Google 리다이렉트 URL에서 실제 URL 추출
                actual_url = href.split("/url?q=")[1].split("&")[0]
                self._current_link = urllib.parse.unquote(actual_url)
        if tag == "h3":
            self._in_h3 = True
            self._current_title = ""

    def handle_endtag(self, tag):
        if tag == "h3" and self._in_h3:
            self._in_h3 = False
            if self._current_title and self._current_link:
                self.results.append({
                    "title": self._current_title.strip(),
                    "url": self._current_link,
                })
            self._current_link = None

    def handle_data(self, data):
        if self._in_h3:
            self._current_title += data


def search_google(query: str, num_results: int = 5) -> list[dict]:
    """Google 검색을 수행하고 결과를 반환합니다."""
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://www.google.com/search?q={encoded_query}&hl=ko&num={num_results}"

    html = fetch_url(url)
    if not html:
        return []

    parser = GoogleResultParser()
    try:
        parser.feed(html)
    except Exception:
        pass

    return parser.results[:num_results]


def fetch_article_summary(url: str, max_chars: int = 500) -> str:
    """기사 URL에서 요약 텍스트를 추출합니다."""
    html = fetch_url(url, timeout=8)
    if not html:
        return ""

    text = extract_text_from_html(html)
    # 너무 짧은 텍스트는 무시
    if len(text) < 50:
        return ""

    # 적절한 길이로 자르기
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    return text


# ─────────────────────────────────────────────
# 트렌드 수집 메인 로직
# ─────────────────────────────────────────────
def collect_trends(category: str) -> dict:
    """특정 카테고리의 트렌드를 수집합니다."""
    queries = SEARCH_QUERIES.get(category, [])
    if not queries:
        print(f"[오류] 알 수 없는 카테고리: {category}")
        return {}

    print(f"\n{'='*60}")
    print(f"  [{category}] 트렌드 수집 시작")
    print(f"{'='*60}")

    results = {
        "category": category,
        "collected_at": datetime.now().isoformat(),
        "articles": [],
    }

    seen_urls = set()
    for query in queries:
        print(f"\n  검색: {query}")
        search_results = search_google(query)

        for item in search_results:
            url = item["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)

            print(f"    - {item['title'][:50]}...")
            summary = fetch_article_summary(url)

            results["articles"].append({
                "title": item["title"],
                "url": url,
                "search_query": query,
                "summary": summary,
            })

    print(f"\n  → {len(results['articles'])}개 기사 수집 완료")
    return results


def save_as_json(data: dict, filepath: str):
    """JSON 형식으로 저장합니다."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  저장: {filepath}")


def save_as_markdown(data: dict, filepath: str):
    """마크다운 형식으로 저장합니다."""
    lines = []
    category = data.get("category", "")
    collected_at = data.get("collected_at", "")

    lines.append(f"# {category} 트렌드 리서치")
    lines.append(f"\n> 수집일시: {collected_at}\n")

    for i, article in enumerate(data.get("articles", []), 1):
        lines.append(f"## {i}. {article['title']}")
        lines.append(f"\n- **출처**: [{article['url']}]({article['url']})")
        lines.append(f"- **검색어**: {article['search_query']}")
        if article.get("summary"):
            lines.append(f"\n### 요약\n\n{article['summary']}")
        lines.append("")

    lines.append("---")
    lines.append(f"\n총 {len(data.get('articles', []))}개 기사 수집\n")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  저장: {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="국방/기술/K-푸드 트렌드 수집기"
    )
    parser.add_argument(
        "--category",
        choices=["국방", "기술", "K-푸드", "all"],
        default="all",
        help="수집할 카테고리 (기본: all)",
    )
    args = parser.parse_args()

    os.makedirs(INPUT_DIR, exist_ok=True)

    categories = (
        list(SEARCH_QUERIES.keys()) if args.category == "all"
        else [args.category]
    )
    today = datetime.now().strftime("%Y%m%d")
    all_results = {}

    for cat in categories:
        results = collect_trends(cat)
        if not results:
            continue
        all_results[cat] = results

        # 카테고리별 파일 저장
        safe_name = cat.replace("-", "").replace(" ", "_")
        json_path = os.path.join(INPUT_DIR, f"trends_{safe_name}_{today}.json")
        md_path = os.path.join(INPUT_DIR, f"trends_{safe_name}_{today}.md")

        save_as_json(results, json_path)
        save_as_markdown(results, md_path)

    # 전체 요약 저장
    if len(all_results) > 1:
        summary_path = os.path.join(INPUT_DIR, f"trends_summary_{today}.json")
        save_as_json({
            "collected_at": datetime.now().isoformat(),
            "categories": list(all_results.keys()),
            "total_articles": sum(
                len(v.get("articles", [])) for v in all_results.values()
            ),
            "data": all_results,
        }, summary_path)

    print(f"\n{'='*60}")
    print("  수집 완료!")
    print(f"  결과 위치: {INPUT_DIR}/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
