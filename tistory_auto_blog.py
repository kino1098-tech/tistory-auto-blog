"""
티스토리 완전 자동화 블로그 발행 스크립트 v2
- Google Trends RSS + 네이버 DataLab으로 트렌드 수집
- Claude API로 주제 선정 → SEO/GEO 최적화 글 + 카드뉴스 생성
- Selenium으로 티스토리 직접 로그인 후 발행 (Open API 대체)
"""

import os
import json
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

import anthropic
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ── 환경변수 (GitHub Actions Secrets에 등록) ──────────────────────────
CLAUDE_API_KEY       = os.environ["CLAUDE_API_KEY"]
TISTORY_EMAIL        = os.environ["TISTORY_EMAIL"]        # 카카오 로그인 이메일
TISTORY_PASSWORD     = os.environ["TISTORY_PASSWORD"]     # 카카오 비밀번호
TISTORY_BLOG_URL     = os.environ["TISTORY_BLOG_URL"]     # ex) https://myblog.tistory.com
NAVER_CLIENT_ID      = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET  = os.environ.get("NAVER_CLIENT_SECRET", "")

client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 1 · 트렌드 키워드 수집
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_google_trends_korea() -> list[str]:
    url = "https://trends.google.com/trending/rss?geo=KR"
    try:
        res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(res.text)
        return [item.text.strip() for item in root.findall(".//item/title") if item.text][:20]
    except Exception as e:
        print(f"[Google Trends 오류] {e}")
        return []

def fetch_govt_policy_rss() -> list[str]:
    url = "https://www.gov.kr/rss/rss_policy.do"
    try:
        res = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(res.content)
        return [item.text.strip() for item in root.findall(".//item/title") if item.text][:10]
    except Exception as e:
        print(f"[정부24 RSS 오류] {e}")
        return []

def collect_trends() -> list[str]:
    print("트렌드 수집 중...")
    keywords = list(dict.fromkeys(fetch_google_trends_korea() + fetch_govt_policy_rss()))
    print(f"  수집된 키워드 {len(keywords)}개")
    return keywords


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 2 · Claude가 주제 선정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TOPIC_PROMPT = """
당신은 한국 블로그 SEO 전문가입니다.
아래 트렌드 키워드 목록에서 블로그 포스팅 주제를 1개 선정하세요.

선정 기준:
1. 정보성 + 생활밀착형 (독자가 즉시 행동 가능)
2. 금융/정책/건강 카테고리 우선 (광고 단가 높음)
3. 2026년 현재 유효한 정보

JSON만 출력 (다른 텍스트 없이):
{{"topic":"제목","main_keyword":"핵심키워드","sub_keywords":["연관1","연관2","연관3"],"category":"카테고리"}}

트렌드 키워드:
{keywords}
"""

def select_topic(keywords: list[str]) -> dict:
    print("주제 선정 중...")
    res = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        messages=[{"role": "user", "content": TOPIC_PROMPT.format(
            keywords="\n".join(f"- {k}" for k in keywords[:30])
        )}]
    )
    raw = res.content[0].text.strip()
    try:
        topic = json.loads(raw)
        print(f"  선정 주제: {topic['topic']}")
        return topic
    except:
        return {"topic": keywords[0], "main_keyword": keywords[0],
                "sub_keywords": ["신청방법", "자격조건", "지원금액"], "category": "정보"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 3 · SEO + GEO 최적화 글 + 카드뉴스 생성
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BLOG_PROMPT = """
당신은 한국 최고의 SEO/GEO 블로그 작성 전문가입니다.
아래 주제로 티스토리 블로그 포스팅을 작성하세요.

주제: {topic}
핵심 키워드: {main_keyword}
연관 키워드: {sub_keywords}
작성일: {today}

[SEO 규칙]
- H2 소제목 4~6개, 각 H2 아래 H3 2~3개
- 핵심 키워드 본문에서 최소 5회 자연스럽게 반복
- 글 길이 1500자 이상
- 마지막에 FAQ 섹션 필수 (Q&A 3개 이상)
- 도입부 100자 안에 핵심 키워드 포함

[GEO 규칙 - AI 검색 인용 최적화]
- 각 H2 시작에 질문-답변 형식 단락 포함
- 금액/날짜/퍼센트 등 구체적 숫자 반드시 포함
- "결론적으로", "핵심은" 으로 시작하는 요약 문장 포함
- 출처 명시 (예: "2026년 기준")

[카드뉴스 규칙]
본문 중간에 아래 형식의 카드뉴스를 3~4개 삽입:
<div style="background:#[색상];border-radius:14px;padding:28px 24px;color:#fff;margin:1.5rem 0;">
  <div style="font-size:11px;opacity:0.65;letter-spacing:1.5px;margin-bottom:6px;">0X · 섹션주제</div>
  <div style="font-size:19px;font-weight:500;line-height:1.4;margin-bottom:10px;">카드 제목</div>
  <div style="font-size:13px;opacity:0.88;line-height:1.7;">핵심 내용</div>
</div>
색상: 핵심요약=#3C3489 수치통계=#0F6E56 주의조건=#854F0B 절차방법=#185FA5

[출력 형식] JSON만 출력 (마크다운 코드블록 없이):
{{"title":"H1제목","meta_description":"메타설명150자이내","tags":["태그1","태그2","태그3","태그4","태그5"],"content":"HTML전체본문"}}
"""

def generate_post(topic: dict) -> dict:
    print("글 작성 중...")
    res = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": BLOG_PROMPT.format(
            topic=topic["topic"],
            main_keyword=topic["main_keyword"],
            sub_keywords=", ".join(topic["sub_keywords"]),
            today=datetime.now().strftime("%Y년 %m월 %d일")
        )}]
    )
    raw = res.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        post = json.loads(raw.strip())
        print(f"  제목: {post['title']}")
        print(f"  본문 길이: {len(post['content'])}자")
        return post
    except Exception as e:
        print(f"  JSON 파싱 오류: {e}")
        return {"title": topic["topic"], "meta_description": "", "tags": topic["sub_keywords"], "content": raw}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 4 · Selenium으로 티스토리 자동 발행
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_driver() -> webdriver.Chrome:
    """GitHub Actions 환경용 headless Chrome 설정"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")
    return webdriver.Chrome(options=options)

def kakao_login(driver: webdriver.Chrome):
    """카카오 계정으로 티스토리 로그인"""
    print("  카카오 로그인 중...")
    wait = WebDriverWait(driver, 15)

    # 티스토리 로그인 페이지 이동
    driver.get("https://www.tistory.com/auth/login")
    time.sleep(2)

    # 카카오 로그인 버튼 클릭
    kakao_btn = wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, "a.btn_login.link_kakao_id")
    ))
    kakao_btn.click()
    time.sleep(2)

    # 이메일 입력
    email_input = wait.until(EC.presence_of_element_located((By.ID, "loginId--1")))
    email_input.clear()
    email_input.send_keys(TISTORY_EMAIL)

    # 비밀번호 입력
    pw_input = driver.find_element(By.ID, "password--2")
    pw_input.clear()
    pw_input.send_keys(TISTORY_PASSWORD)

    # 로그인 버튼 클릭
    driver.find_element(By.CSS_SELECTOR, "button.btn_g.highlight.submit").click()
    time.sleep(3)
    print("  로그인 완료")

def publish_post(driver: webdriver.Chrome, post: dict, topic: dict):
    """티스토리 글쓰기 → HTML 모드로 내용 입력 → 발행"""
    wait = WebDriverWait(driver, 20)
    print("  글 발행 중...")

    # 글쓰기 페이지 이동
    write_url = f"{TISTORY_BLOG_URL}/manage/newpost"
    driver.get(write_url)
    time.sleep(3)

    # ── 제목 입력 ──────────────────────────────────────────────────
    title_area = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "input#post-title-inp, textarea.txt_area[placeholder*='제목']")
    ))
    title_area.clear()
    title_area.send_keys(post["title"])
    time.sleep(1)

    # ── HTML 모드로 전환 ───────────────────────────────────────────
    # 에디터 우측 상단 "HTML" 버튼 클릭
    try:
        html_btn = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "button.btn_switch, button[data-type='html'], .editor-mode-html")
        ))
        html_btn.click()
        time.sleep(1)
    except:
        # 버튼 못 찾으면 단축키 시도 (Ctrl+Shift+H)
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(driver).key_down(Keys.CONTROL).key_down(Keys.SHIFT).send_keys("h").key_up(Keys.SHIFT).key_up(Keys.CONTROL).perform()
        time.sleep(1)

    # ── 본문 입력 ──────────────────────────────────────────────────
    # HTML 편집 영역에 내용 삽입 (JavaScript 사용 — 긴 HTML은 send_keys보다 안정적)
    content_area = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "textarea.CodeMirror-scroll, div.CodeMirror, #content-area, .editor-content")
    ))
    driver.execute_script("""
        var editor = document.querySelector('textarea.CodeMirror-scroll, div.CodeMirror textarea, #content-area');
        if (editor) {
            editor.value = arguments[0];
            editor.dispatchEvent(new Event('input', { bubbles: true }));
        }
    """, post["content"])
    time.sleep(1)

    # ── 태그 입력 ──────────────────────────────────────────────────
    try:
        tag_input = driver.find_element(By.CSS_SELECTOR, "input#tagText, input.tag-input, input[placeholder*='태그']")
        for tag in post.get("tags", [])[:5]:
            tag_input.clear()
            tag_input.send_keys(tag)
            tag_input.send_keys(Keys.RETURN)
            time.sleep(0.3)
    except Exception as e:
        print(f"  태그 입력 건너뜀: {e}")

    # ── 공개 발행 ──────────────────────────────────────────────────
    try:
        # 발행 버튼 클릭
        publish_btn = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "button.btn_publish, button#publish-btn, button[data-action='publish']")
        ))
        publish_btn.click()
        time.sleep(2)

        # 공개 옵션 선택 (팝업이 뜨는 경우)
        try:
            public_opt = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "label[for='open20'], input[value='20'], .btn-open-public")
            ))
            public_opt.click()
            time.sleep(0.5)

            # 최종 발행 확인 버튼
            confirm_btn = driver.find_element(
                By.CSS_SELECTOR, "button.btn_confirm, button.btn-publish-confirm, button.btn_action"
            )
            confirm_btn.click()
            time.sleep(2)
        except:
            pass  # 팝업 없이 바로 발행된 경우

        print(f"  발행 완료: {driver.current_url}")

    except Exception as e:
        print(f"  발행 버튼 오류: {e}")
        # 최후 수단: Ctrl+Enter
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(driver).key_down(Keys.CONTROL).send_keys(Keys.RETURN).key_up(Keys.CONTROL).perform()
        time.sleep(2)

def publish_to_tistory(post: dict, topic: dict):
    driver = get_driver()
    try:
        kakao_login(driver)
        publish_post(driver, post, topic)
    finally:
        driver.quit()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    print(f"\n{'='*50}")
    print(f"티스토리 자동 발행 시작: {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'='*50}\n")

    keywords = collect_trends()
    if not keywords:
        keywords = ["2026 청년 지원금", "청년통장", "정부 보조금"]

    topic = select_topic(keywords)
    post  = generate_post(topic)
    publish_to_tistory(post, topic)

    print(f"\n{'='*50}")
    print("자동화 완료!")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
