"""
티스토리 블로그 글 자동 생성 + Gmail 전송 v9
- Selenium 제거 (발행은 수동)
- 하루 5개 글 생성 → Gmail로 전송
- 각 글은 HTML 형식으로 바로 복붙 가능
"""

import os
import json
import time
import smtplib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google import genai

# ── 환경변수 ──────────────────────────────────────────────────────
GEMINI_API_KEY  = os.environ["GEMINI_API_KEY"]
GMAIL_ADDRESS   = os.environ["GMAIL_ADDRESS"]    # 보내는 Gmail 주소
GMAIL_APP_PW    = os.environ["GMAIL_APP_PW"]     # Gmail 앱 비밀번호
RECEIVE_EMAIL   = os.environ["RECEIVE_EMAIL"]    # 받는 이메일 (같아도 됨)

client = genai.Client(api_key=GEMINI_API_KEY)
MODEL  = "gemini-2.5-flash"
POSTS_PER_DAY = 5  # 하루 생성 글 수


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Gemini 호출 (429 자동 재시도)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def gemini_call(prompt: str, max_retry=5) -> str:
    for attempt in range(1, max_retry + 1):
        try:
            res = client.models.generate_content(model=MODEL, contents=prompt)
            return res.text.strip()
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                print(f"  API 한도 — 65초 후 재시도 ({attempt}/{max_retry})")
                time.sleep(65)
            else:
                raise
    raise Exception("Gemini API 재시도 초과")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 1 · 트렌드 수집
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def collect_trends() -> list[str]:
    print("트렌드 수집 중...")
    try:
        res = requests.get(
            "https://trends.google.com/trending/rss?geo=KR",
            timeout=10, headers={"User-Agent": "Mozilla/5.0"}
        )
        keywords = [el.text.strip() for el in ET.fromstring(res.text).findall(".//item/title") if el.text][:20]
    except Exception as e:
        print(f"  오류: {e}")
        keywords = []
    if not keywords:
        keywords = ["2026 청년 지원금", "청년도약계좌", "정부 보조금",
                    "실업급여 신청방법", "건강보험료 환급", "전세 사기 예방",
                    "자동차세 납부", "종합소득세 신고", "육아휴직 급여", "국민연금 조기수령"]
    print(f"  수집 키워드 {len(keywords)}개")
    return keywords


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 2 · 주제 5개 선정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def select_topics(keywords: list[str], count: int = 5) -> list[dict]:
    print(f"주제 {count}개 선정 중...")
    prompt = f"""한국 블로그 SEO 전문가. 아래 키워드를 참고해서 블로그 포스팅 주제 {count}개를 선정하세요.

선정 기준:
1. 금융/정책/건강/생활정보 우선 (광고 단가 높음)
2. 2026년 현재 유효한 정보
3. 서로 중복되지 않는 다양한 주제

순수 JSON 배열만 출력 (마크다운 없이):
[
  {{"topic":"제목","main_keyword":"핵심키워드","sub_keywords":["연관1","연관2","연관3"],"category":"카테고리"}},
  ...
]

참고 키워드:
{chr(10).join(f"- {k}" for k in keywords[:30])}"""

    raw = gemini_call(prompt)
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    try:
        topics = json.loads(raw.strip())
        for t in topics:
            print(f"  - {t['topic']}")
        return topics[:count]
    except Exception as e:
        print(f"  파싱 오류: {e}")
        # 기본 주제 반환
        return [{"topic": k, "main_keyword": k,
                 "sub_keywords": ["신청방법", "자격조건", "지원금액"],
                 "category": "정보"} for k in keywords[:count]]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 3 · 글 생성
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_post(topic: dict) -> dict:
    prompt = f"""한국 SEO/GEO 블로그 전문가. 티스토리 포스팅 작성.
주제: {topic['topic']}
핵심 키워드: {topic['main_keyword']}
연관 키워드: {", ".join(topic['sub_keywords'])}
작성일: {datetime.now().strftime("%Y년 %m월 %d일")}

[SEO 규칙]
- H2 소제목 4~6개, 각 H2 아래 H3 2~3개
- 핵심 키워드 본문에서 최소 5회 자연스럽게 반복
- 글 길이 1500자 이상
- 마지막에 FAQ 섹션 필수 (Q&A 3개 이상)
- 도입부 100자 안에 핵심 키워드 포함

[GEO 규칙]
- 각 H2 시작에 질문-답변 형식 단락
- 금액/날짜/퍼센트 등 구체적 숫자 포함
- "결론적으로", "핵심은" 으로 시작하는 요약 문장 포함

[카드뉴스] 본문 중간에 3~4개 삽입:
<div style="background:#3C3489;border-radius:14px;padding:28px 24px;color:#fff;margin:1.5rem 0;">
<div style="font-size:11px;opacity:0.65;margin-bottom:6px;">01 · 섹션주제</div>
<div style="font-size:19px;font-weight:500;margin-bottom:10px;">카드 제목</div>
<div style="font-size:13px;line-height:1.7;">핵심 내용</div>
</div>
색상: 핵심요약=#3C3489 수치통계=#0F6E56 주의조건=#854F0B 절차방법=#185FA5

순수 JSON만 출력 (마크다운 없이):
{{"title":"제목","meta_description":"설명150자이내","tags":["태그1","태그2","태그3","태그4","태그5"],"content":"HTML본문전체"}}"""

    raw = gemini_call(prompt)
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    try:
        post = json.loads(raw.strip())
        print(f"  완성: {post['title']} ({len(post['content'])}자)")
        return post
    except Exception as e:
        print(f"  파싱 오류: {e}")
        return {"title": topic["topic"], "meta_description": "",
                "tags": topic["sub_keywords"], "content": raw}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 4 · Gmail 전송
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def send_email(posts: list[dict]):
    print("이메일 전송 중...")
    today = datetime.now().strftime("%Y년 %m월 %d일")

    # 이메일 본문 — 각 글을 섹션으로 구분
    html_body = f"""
<html><body style="font-family:sans-serif;max-width:800px;margin:0 auto;padding:20px;">
<h1 style="color:#3C3489;border-bottom:2px solid #3C3489;padding-bottom:10px;">
  {today} 티스토리 자동 생성 글 {len(posts)}편
</h1>
<p style="color:#666;font-size:14px;">아래 글들을 티스토리에 복붙해서 발행하세요.</p>
"""

    for i, post in enumerate(posts, 1):
        html_body += f"""
<div style="margin:40px 0;padding:24px;border:1px solid #ddd;border-radius:12px;">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
    <span style="background:#3C3489;color:#fff;padding:4px 12px;border-radius:20px;font-size:13px;">
      {i}/{len(posts)}
    </span>
    <h2 style="margin:0;font-size:18px;color:#222;">{post['title']}</h2>
  </div>

  <div style="background:#f5f5f5;border-radius:8px;padding:12px;margin-bottom:16px;font-size:13px;color:#555;">
    <b>태그:</b> {", ".join(post.get('tags', []))}<br>
    <b>메타 설명:</b> {post.get('meta_description', '')}
  </div>

  <div style="background:#fff8e1;border:1px solid #ffc107;border-radius:8px;padding:12px;margin-bottom:16px;font-size:13px;">
    아래 HTML을 티스토리 에디터 → HTML 모드에서 붙여넣기 하세요.
  </div>

  <textarea style="width:100%;height:200px;font-family:monospace;font-size:11px;padding:10px;border:1px solid #ddd;border-radius:6px;box-sizing:border-box;"
    onclick="this.select()">{post['content'].replace('<', '&lt;').replace('>', '&gt;')}</textarea>

  <details style="margin-top:16px;">
    <summary style="cursor:pointer;color:#3C3489;font-weight:500;">미리보기 펼치기</summary>
    <div style="margin-top:12px;padding:16px;border:1px solid #eee;border-radius:8px;">
      {post['content']}
    </div>
  </details>
</div>
"""

    html_body += "</body></html>"

    # Gmail SMTP 전송
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[블로그 자동생성] {today} — {len(posts)}편 준비완료"
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = RECEIVE_EMAIL
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_ADDRESS, GMAIL_APP_PW)
        smtp.send_message(msg)

    print(f"  전송 완료 → {RECEIVE_EMAIL}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    print(f"\n{'='*50}")
    print(f"블로그 글 자동 생성 시작: {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'='*50}\n")

    # 1. 트렌드 수집
    keywords = collect_trends()

    # 2. 주제 5개 선정
    topics = select_topics(keywords, count=POSTS_PER_DAY)

    # 3. 글 5개 생성
    print(f"\n글 생성 중 (총 {len(topics)}편)...")
    posts = []
    for i, topic in enumerate(topics, 1):
        print(f"\n[{i}/{len(topics)}] {topic['topic']}")
        post = generate_post(topic)
        posts.append(post)
        if i < len(topics):
            time.sleep(3)  # API 부하 방지

    # 4. Gmail 전송
    print(f"\n")
    send_email(posts)

    print(f"\n{'='*50}")
    print(f"완료! {len(posts)}편 → {RECEIVE_EMAIL} 전송됨")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
