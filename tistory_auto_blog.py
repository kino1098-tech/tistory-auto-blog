"""
티스토리 블로그 글 자동 생성 v10
- 썸네일: HTML → Playwright로 1:1 PNG 변환 → 이메일 첨부
- 링크 버튼: 글 내용 관련 공식 사이트 링크 자동 삽입
- Gmail 전송
"""

import os
import json
import time
import base64
import smtplib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from pathlib import Path

from google import genai

# ── 환경변수 ──────────────────────────────────────────────────────
GEMINI_API_KEY  = os.environ["GEMINI_API_KEY"]
GMAIL_ADDRESS   = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PW    = os.environ["GMAIL_APP_PW"]
RECEIVE_EMAIL   = os.environ["RECEIVE_EMAIL"]

client = genai.Client(api_key=GEMINI_API_KEY)
MODEL  = "gemini-2.5-flash"
POSTS_PER_DAY = 5


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Gemini 호출
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def gemini_call(prompt: str, max_retry=5) -> str:
    for attempt in range(1, max_retry + 1):
        try:
            return client.models.generate_content(model=MODEL, contents=prompt).text.strip()
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
# STEP 2 · 주제 선정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def select_topics(keywords: list[str], count: int = 5) -> list[dict]:
    print(f"주제 {count}개 선정 중...")
    prompt = f"""당신은 한국 SNS/검색 트렌드에 정통한 블로그 콘텐츠 전략가입니다.
아래 실시간 트렌드 키워드를 보고, 지금 이 순간 사람들이 검색하고 싶어하는 주제 {count}개를 선정하세요.

[중요 선정 기준]
1. 지금 당장 화제가 되는 이슈 (뉴스, 정책 변경, 시즌 이벤트 등)
2. "왜?", "어떻게?", "얼마나?" 궁금증을 유발하는 주제
3. 단순 정보 나열 X — 사람들이 감정적으로 반응하는 주제 (논란, 변화, 혜택 등)
4. 예시: "○○ 폐지 논란 — 나는 어떻게 해야 하나", "○○ 가격 폭등 이유와 대처법"

순수 JSON 배열만 출력 (마크다운 없이):
[{{"topic":"제목","main_keyword":"핵심키워드","sub_keywords":["연관1","연관2","연관3"],"category":"카테고리","color":"#3C3489","hook":"독자 호기심 유발 한 줄"}}]
color: 금융/경제=#0F6E56 정책/사회=#185FA5 건강/의료=#993C1D 생활/문화=#534AB7 논란/이슈=#854F0B

실시간 트렌드 키워드:
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
    except:
        return [{"topic": k, "main_keyword": k, "sub_keywords": ["신청방법", "자격조건", "지원금액"],
                 "category": "정보", "color": "#3C3489"} for k in keywords[:count]]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 3 · 글 생성 (링크 버튼 포함)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_post(topic: dict) -> dict:
    hook = topic.get('hook', '')
    prompt = f"""당신은 독자를 사로잡는 한국 트렌드 블로그 작가입니다.
주제: {topic['topic']}
핵심 키워드: {topic['main_keyword']}
연관 키워드: {", ".join(topic['sub_keywords'])}
독자 훅: {hook}

[글쓰기 원칙]
- 도입부: 날짜 없이 시작. 독자가 "맞아 나도 궁금했어!" 하게 만드는 첫 문장
- 길이: 800~1000자 (짧고 핵심만, 스크롤 부담 없게)
- 문체: 친근하고 명확하게. 어려운 용어 최소화
- 구조: H2 3~4개만 (많으면 X)
- 핵심 키워드 3~4회만 자연스럽게
- 날짜/작성일 절대 넣지 말 것

[카드뉴스] 2~3개만 (핵심 포인트만):
<div style="background:#3C3489;border-radius:14px;padding:24px 20px;color:#fff;margin:1.2rem 0;">
<div style="font-size:11px;opacity:0.65;margin-bottom:6px;">포인트</div>
<div style="font-size:18px;font-weight:500;margin-bottom:8px;">카드 제목</div>
<div style="font-size:13px;line-height:1.65;">핵심 내용 2~3줄</div>
</div>
색상: 핵심=#3C3489 수치=#0F6E56 주의=#854F0B 방법=#185FA5

[링크 버튼] 글 중간에 2~3개. 해당 내용 관련 실제 공식 사이트 URL만 사용:
<a href="실제URL" target="_blank" style="display:inline-flex;align-items:center;gap:8px;background:#f8f9fa;border:1.5px solid #dee2e6;border-radius:10px;padding:12px 20px;text-decoration:none;color:#212529;font-size:14px;font-weight:500;margin:1rem 0;">
  <span style="background:#3C3489;color:#fff;border-radius:6px;padding:3px 8px;font-size:11px;">바로가기</span>
  사이트명
  <span style="margin-left:auto;color:#868e96;">→</span>
</a>

[마무리] FAQ 2개만 (가장 많이 검색하는 질문)

순수 JSON만 (마크다운 없이):
{{"title":"제목","meta_description":"설명120자이내","tags":["태그1","태그2","태그3","태그4","태그5"],"content":"HTML본문전체","related_links":[{{"name":"사이트명","url":"https://..."}}]}}"""

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
                "tags": topic["sub_keywords"], "content": raw, "related_links": []}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 4 · 썸네일 HTML → PNG 변환
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def make_thumbnail_html(topic: dict, post: dict) -> str:
    """1:1 썸네일 카드 HTML 생성"""
    color = topic.get("color", "#3C3489")
    # 색상에서 밝은 버전 계산 (투명도로 처리)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:800px; height:800px; overflow:hidden; }}
  .card {{
    width:800px; height:800px;
    background: {color};
    display:flex; flex-direction:column;
    justify-content:center; align-items:center;
    padding:60px;
    position:relative;
    font-family: 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
  }}
  .bg-circle {{
    position:absolute; border-radius:50%;
    background:rgba(255,255,255,0.06);
  }}
  .category {{
    font-size:18px; color:rgba(255,255,255,0.75);
    letter-spacing:3px; margin-bottom:28px;
    text-transform:uppercase;
  }}
  .title {{
    font-size:44px; font-weight:700; color:#fff;
    text-align:center; line-height:1.35;
    margin-bottom:36px; word-break:keep-all;
  }}
  .keyword {{
    display:flex; gap:10px; flex-wrap:wrap; justify-content:center;
  }}
  .kw-tag {{
    background:rgba(255,255,255,0.18);
    color:#fff; font-size:15px;
    padding:6px 16px; border-radius:20px;
  }}
  .bottom {{
    position:absolute; bottom:40px;
    font-size:15px; color:rgba(255,255,255,0.5);
    letter-spacing:1px;
  }}
  .year-badge {{
    position:absolute; top:44px; right:50px;
    background:rgba(255,255,255,0.15);
    color:#fff; font-size:16px; font-weight:600;
    padding:6px 16px; border-radius:20px;
  }}
</style>
</head>
<body>
<div class="card">
  <div class="bg-circle" style="width:500px;height:500px;top:-150px;right:-150px;"></div>
  <div class="bg-circle" style="width:300px;height:300px;bottom:-80px;left:-80px;"></div>
  <div class="year-badge">2026</div>
  <div class="category">{topic.get('category', '정보')}</div>
  <div class="title">{post['title'][:30]}{'...' if len(post['title']) > 30 else ''}</div>
  <div class="keyword">
    {''.join(f'<span class="kw-tag">#{kw}</span>' for kw in topic['sub_keywords'][:3])}
  </div>
  <div class="bottom">tistory blog · {datetime.now().strftime('%Y.%m.%d')}</div>
</div>
</body>
</html>"""


def html_to_png(html_content: str, output_path: str) -> bool:
    """Playwright로 HTML → PNG 변환"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 800, "height": 800})
            page.set_content(html_content, wait_until="networkidle")
            page.screenshot(path=output_path, clip={"x": 0, "y": 0, "width": 800, "height": 800})
            browser.close()
        print(f"  썸네일 생성: {output_path}")
        return True
    except Exception as e:
        print(f"  썸네일 생성 실패: {e}")
        return False


def generate_thumbnail(topic: dict, post: dict, idx: int) -> str | None:
    """썸네일 PNG 생성 후 경로 반환"""
    html = make_thumbnail_html(topic, post)
    path = f"/tmp/thumbnail_{idx}.png"

    # HTML 파일 저장
    html_path = f"/tmp/thumbnail_{idx}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    if html_to_png(html_path, path):
        return path
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 5 · Gmail 전송
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def send_email(posts: list[dict], topics: list[dict], thumbnails: list[str | None]):
    print("이메일 전송 중...")
    today = datetime.now().strftime("%Y년 %m월 %d일")

    html_body = f"""
<html><body style="font-family:'Apple SD Gothic Neo',sans-serif;max-width:820px;margin:0 auto;padding:20px;background:#f8f9fa;">
<div style="background:#3C3489;color:#fff;padding:24px 28px;border-radius:14px;margin-bottom:24px;">
  <h1 style="margin:0;font-size:22px;">{today} 블로그 자동 생성 — {len(posts)}편</h1>
  <p style="margin:8px 0 0;opacity:0.8;font-size:14px;">티스토리 HTML 모드에 복붙 후 발행하세요</p>
</div>
"""

    for i, (post, topic, thumb_path) in enumerate(zip(posts, topics, thumbnails), 1):
        cid = f"thumb{i}"
        thumb_html = f'<img src="cid:{cid}" style="width:160px;height:160px;border-radius:10px;object-fit:cover;">' if thumb_path else '<div style="width:160px;height:160px;background:#eee;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:12px;color:#999;">이미지 없음</div>'

        links_html = ""
        for link in post.get("related_links", [])[:3]:
            links_html += f'<a href="{link["url"]}" style="display:inline-block;margin:4px;padding:4px 10px;background:#e9ecef;border-radius:6px;font-size:12px;color:#495057;text-decoration:none;">{link["name"]}</a>'

        html_body += f"""
<div style="background:#fff;border-radius:14px;padding:24px;margin-bottom:20px;border:1px solid #dee2e6;">
  <div style="display:flex;gap:16px;align-items:flex-start;margin-bottom:16px;">
    {thumb_html}
    <div style="flex:1;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
        <span style="background:#3C3489;color:#fff;padding:3px 10px;border-radius:20px;font-size:12px;">{i}/{len(posts)}</span>
        <span style="background:#e9ecef;color:#495057;padding:3px 10px;border-radius:20px;font-size:12px;">{topic.get('category','정보')}</span>
      </div>
      <h2 style="margin:0 0 8px;font-size:17px;color:#212529;">{post['title']}</h2>
      <p style="margin:0 0 8px;font-size:13px;color:#868e96;">{post.get('meta_description','')}</p>
      <div><b style="font-size:12px;color:#495057;">태그:</b> {", ".join(f"#{t}" for t in post.get('tags',[]))}</div>
      <div style="margin-top:8px;">{links_html}</div>
    </div>
  </div>

  <div style="background:#fff3cd;border:1px solid #ffc107;border-radius:8px;padding:10px 14px;font-size:13px;margin-bottom:10px;">
    아래 HTML을 티스토리 에디터 → <b>HTML 모드</b>에서 클릭 후 전체선택(Ctrl+A) → 붙여넣기
  </div>

  <textarea onclick="this.select()" style="width:100%;height:180px;font-family:monospace;font-size:11px;padding:10px;border:1px solid #dee2e6;border-radius:8px;box-sizing:border-box;resize:vertical;">{post['content']}</textarea>

  <details style="margin-top:12px;">
    <summary style="cursor:pointer;color:#3C3489;font-weight:500;font-size:14px;padding:8px 0;">미리보기 펼치기 ▼</summary>
    <div style="margin-top:12px;padding:20px;border:1px solid #dee2e6;border-radius:8px;background:#fafafa;">
      {post['content']}
    </div>
  </details>
</div>
"""

    html_body += "</body></html>"

    # MIMEMultipart related (이미지 인라인 첨부)
    msg_root = MIMEMultipart("related")
    msg_root["Subject"] = f"[블로그 자동생성] {today} — {len(posts)}편 준비완료"
    msg_root["From"]    = GMAIL_ADDRESS
    msg_root["To"]      = RECEIVE_EMAIL

    msg_alt = MIMEMultipart("alternative")
    msg_root.attach(msg_alt)
    msg_alt.attach(MIMEText(html_body, "html", "utf-8"))

    # 썸네일 이미지 첨부
    for i, thumb_path in enumerate(thumbnails, 1):
        if thumb_path and Path(thumb_path).exists():
            with open(thumb_path, "rb") as f:
                img = MIMEImage(f.read(), _subtype="png")
                img.add_header("Content-ID", f"<thumb{i}>")
                img.add_header("Content-Disposition", "inline", filename=f"thumbnail_{i}.png")
                msg_root.attach(img)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_ADDRESS, GMAIL_APP_PW)
        smtp.send_message(msg_root)

    print(f"  전송 완료 → {RECEIVE_EMAIL}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    print(f"\n{'='*50}")
    print(f"블로그 글 자동 생성 시작: {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'='*50}\n")

    keywords = collect_trends()
    topics   = select_topics(keywords, count=POSTS_PER_DAY)

    print(f"\n글 생성 중 (총 {len(topics)}편)...")
    posts      = []
    thumbnails = []

    for i, topic in enumerate(topics, 1):
        print(f"\n[{i}/{len(topics)}] {topic['topic']}")
        post = generate_post(topic)
        posts.append(post)

        print(f"  썸네일 생성 중...")
        thumb = generate_thumbnail(topic, post, i)
        thumbnails.append(thumb)

        if i < len(topics):
            time.sleep(3)

    print(f"\n")
    send_email(posts, topics, thumbnails)

    print(f"\n{'='*50}")
    print(f"완료! {len(posts)}편 → {RECEIVE_EMAIL}")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
