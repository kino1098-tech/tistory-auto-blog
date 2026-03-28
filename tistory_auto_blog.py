"""
티스토리 완전 자동화 블로그 발행 스크립트
- Google Trends RSS + 네이버 DataLab으로 트렌드 수집
- Claude API로 주제 선정 → SEO/GEO 최적화 글 + 카드뉴스 생성
- 티스토리 API로 자동 발행
"""

import os
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import anthropic

# ── 환경변수 (GitHub Actions Secrets에 등록) ────────────────────────────
CLAUDE_API_KEY      = os.environ["CLAUDE_API_KEY"]
TISTORY_ACCESS_TOKEN = os.environ["TISTORY_ACCESS_TOKEN"]
TISTORY_BLOG_NAME   = os.environ["TISTORY_BLOG_NAME"]   # ex) myblog
NAVER_CLIENT_ID     = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 1 · 트렌드 키워드 수집
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_google_trends_korea() -> list[str]:
    """Google Trends 한국 실시간 RSS에서 키워드 수집 (무료, 인증 불필요)"""
    url = "https://trends.google.com/trending/rss?geo=KR"
    try:
        res = requests.get(url, timeout=10,
                           headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(res.text)
        keywords = []
        for item in root.findall(".//item/title"):
            if item.text:
                keywords.append(item.text.strip())
        return keywords[:20]
    except Exception as e:
        print(f"[Google Trends 오류] {e}")
        return []


def fetch_naver_trends() -> list[str]:
    """네이버 DataLab API로 분야별 트렌드 키워드 수집"""
    if not NAVER_CLIENT_ID:
        return []
    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json",
    }
    today = datetime.now().strftime("%Y-%m-%d")
    body = {
        "startDate": "2025-01-01",
        "endDate": today,
        "timeUnit": "week",
        "keywordGroups": [
            {"groupName": "청년정책", "keywords": ["청년", "청년통장", "청년지원금"]},
            {"groupName": "재테크",   "keywords": ["적금", "재테크", "금리"]},
            {"groupName": "복지",     "keywords": ["복지", "정부지원", "보조금"]},
        ],
        "device": "mo",
        "ages": ["2", "3", "4"],
        "gender": "f",
    }
    try:
        res = requests.post(url, headers=headers,
                            data=json.dumps(body), timeout=10)
        data = res.json()
        return [g["groupName"] for g in data.get("results", [])]
    except Exception as e:
        print(f"[네이버 DataLab 오류] {e}")
        return []


def fetch_govt_policy_rss() -> list[str]:
    """정부24 정책 RSS에서 최신 정책 키워드 수집 (무료)"""
    url = "https://www.gov.kr/rss/rss_policy.do"
    try:
        res = requests.get(url, timeout=10,
                           headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(res.content)
        titles = []
        for item in root.findall(".//item/title"):
            if item.text:
                titles.append(item.text.strip())
        return titles[:10]
    except Exception as e:
        print(f"[정부24 RSS 오류] {e}")
        return []


def collect_trends() -> list[str]:
    """전체 트렌드 수집 후 합산"""
    print("트렌드 수집 중...")
    google   = fetch_google_trends_korea()
    naver    = fetch_naver_trends()
    policy   = fetch_govt_policy_rss()
    combined = list(dict.fromkeys(google + naver + policy))  # 중복 제거
    print(f"  수집된 키워드 {len(combined)}개")
    return combined


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 2 · Claude가 주제 선정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TOPIC_SELECTION_PROMPT = """
당신은 한국 블로그 SEO 전문가입니다.
아래 트렌드 키워드 목록에서 블로그 포스팅 주제를 1개 선정하세요.

선정 기준 (우선순위 순):
1. 정보성 + 생활밀착형 — 독자가 검색 후 즉시 행동할 수 있는 주제
2. 검색량 대비 경쟁 낮음 — 대형 언론사보다 개인 블로그가 유리한 롱테일 키워드
3. 광고 단가 높음 — 금융, 정책 지원금, 부동산, 건강 카테고리 우선
4. 2025~2026년 현재 유효한 정보

반드시 JSON만 출력하세요 (다른 텍스트 없이):
{
  "topic": "선정한 주제 제목",
  "main_keyword": "핵심 검색 키워드",
  "sub_keywords": ["연관키워드1", "연관키워드2", "연관키워드3"],
  "category": "카테고리명",
  "reason": "선정 이유 한 줄"
}

트렌드 키워드 목록:
{keywords}
"""

def select_topic(keywords: list[str]) -> dict:
    """Claude가 트렌드 중 최적 주제를 선정"""
    print("주제 선정 중...")
    prompt = TOPIC_SELECTION_PROMPT.format(
        keywords="\n".join(f"- {k}" for k in keywords[:30])
    )
    res = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = res.content[0].text.strip()
    try:
        topic = json.loads(raw)
        print(f"  선정 주제: {topic['topic']}")
        return topic
    except json.JSONDecodeError:
        # JSON 파싱 실패 시 기본값
        return {
            "topic": keywords[0] if keywords else "2026 청년 지원금 총정리",
            "main_keyword": keywords[0] if keywords else "청년 지원금",
            "sub_keywords": ["신청 방법", "자격 조건", "지원 금액"],
            "category": "정보",
            "reason": "트렌드 상위 키워드"
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 3 · SEO + GEO 최적화 글 + 카드뉴스 생성
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BLOG_WRITING_PROMPT = """
당신은 한국 최고의 SEO/GEO 블로그 작성 전문가입니다.
아래 주제로 티스토리 블로그 포스팅을 작성하세요.

주제: {topic}
핵심 키워드: {main_keyword}
연관 키워드: {sub_keywords}
작성일: {today}

━━━ 반드시 지킬 SEO 규칙 ━━━
1. H1 제목: 핵심 키워드 포함, 30자 이내, 클릭하고 싶은 제목
2. 도입부 첫 100자 안에 핵심 키워드 자연스럽게 포함
3. H2 소제목 4~6개, H3 소제목 각 H2 아래 2~3개
4. 핵심 키워드 본문 전체에서 최소 5회 자연스럽게 반복
5. 글 길이: 1500자 이상 (체류시간 확보)
6. 마지막에 FAQ 섹션 필수 (Q&A 형식, 최소 3개)

━━━ 반드시 지킬 GEO 규칙 (AI 검색 인용 최적화) ━━━
1. 각 H2 섹션 시작에 "~란?", "~하는 방법은?" 형식의 직접 질문-답변 단락 포함
2. 금액, 날짜, 퍼센트 등 구체적 숫자 반드시 포함
3. "결론적으로", "핵심은", "요약하면" 으로 시작하는 요약 문장 각 섹션에 포함
4. 출처나 근거가 있으면 명시 (예: "서울시 2026년 공고 기준")

━━━ 카드뉴스 HTML 규칙 ━━━
본문 중간에 카드뉴스 HTML 블록을 3~4개 삽입하세요.
각 카드뉴스는 해당 섹션의 핵심 내용을 시각화합니다.

카드뉴스 HTML 형식 (이 형식을 반드시 준수):
<div class="cardnews-wrap">
  <div class="card" style="background: #[색상코드]; border-radius: 14px; padding: 28px 24px; color: #fff; margin: 1.5rem 0;">
    <div style="font-size:11px; opacity:0.65; letter-spacing:1.5px; margin-bottom:6px;">0X · [카드 주제]</div>
    <div style="font-size:19px; font-weight:500; line-height:1.4; margin-bottom:10px;">[카드 제목]</div>
    <div style="font-size:13px; opacity:0.88; line-height:1.7;">[카드 본문 내용]</div>
    <!-- 통계 카드의 경우 -->
    <div style="display:flex; gap:0; margin:14px 0 4px;">
      <div style="flex:1; text-align:center; padding:10px 4px; background:rgba(255,255,255,0.12); border-radius:8px 0 0 8px;">
        <div style="font-size:22px; font-weight:500;">[숫자]</div>
        <div style="font-size:11px; opacity:0.72; margin-top:2px;">[설명]</div>
      </div>
    </div>
  </div>
</div>

색상 코드 추천 (섹션 성격에 맞게):
- 핵심요약: #3C3489 (진보라)
- 수치/통계: #0F6E56 (진초록)
- 주의/조건: #854F0B (진황)
- 절차/방법: #185FA5 (진파랑)
- 비교/정리: #993C1D (진빨강)

━━━ 출력 형식 ━━━
반드시 JSON으로만 출력 (마크다운 코드블록 없이):
{{
  "title": "H1 제목",
  "meta_description": "메타 디스크립션 (150자 이내, 핵심 키워드 포함)",
  "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
  "content": "HTML 형식의 전체 본문 (카드뉴스 포함)"
}}
"""

def generate_post(topic: dict) -> dict:
    """Claude로 SEO/GEO 최적화 글 + 카드뉴스 생성"""
    print("글 작성 중...")
    prompt = BLOG_WRITING_PROMPT.format(
        topic=topic["topic"],
        main_keyword=topic["main_keyword"],
        sub_keywords=", ".join(topic["sub_keywords"]),
        today=datetime.now().strftime("%Y년 %m월 %d일")
    )
    res = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = res.content[0].text.strip()
    # JSON 코드블록 제거
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        post = json.loads(raw)
        print(f"  제목: {post['title']}")
        print(f"  본문 길이: {len(post['content'])}자")
        return post
    except json.JSONDecodeError as e:
        print(f"  JSON 파싱 오류: {e}")
        # 파싱 실패 시 raw를 content로 감싸서 반환
        return {
            "title": topic["topic"],
            "meta_description": topic["reason"],
            "tags": topic["sub_keywords"],
            "content": raw
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 4 · 티스토리 자동 발행
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def publish_to_tistory(post: dict, topic: dict) -> str:
    """티스토리 API로 글 발행"""
    print("티스토리 발행 중...")
    url = "https://www.tistory.com/apis/post/write"
    params = {
        "access_token": TISTORY_ACCESS_TOKEN,
        "output":       "json",
        "blogName":     TISTORY_BLOG_NAME,
        "title":        post["title"],
        "content":      post["content"],
        "visibility":   "3",          # 3=공개, 0=비공개
        "category":     "0",          # 0=기본 카테고리
        "tag":          ",".join(post.get("tags", [])),
    }
    try:
        res = requests.post(url, data=params, timeout=30)
        data = res.json()
        post_url = data.get("tistory", {}).get("url", "")
        print(f"  발행 완료: {post_url}")
        return post_url
    except Exception as e:
        print(f"  발행 오류: {e}")
        return ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    print(f"\n{'='*50}")
    print(f"티스토리 자동 블로그 발행 시작: {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'='*50}\n")

    # 1. 트렌드 수집
    keywords = collect_trends()
    if not keywords:
        keywords = ["2026 청년 지원금", "청년통장", "정부 보조금"]

    # 2. 주제 선정
    topic = select_topic(keywords)

    # 3. 글 + 카드뉴스 생성
    post = generate_post(topic)

    # 4. 발행
    url = publish_to_tistory(post, topic)

    print(f"\n{'='*50}")
    print(f"완료! 발행된 글: {url}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
