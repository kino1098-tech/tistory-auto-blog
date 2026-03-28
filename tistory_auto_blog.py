"""
티스토리 완전 자동화 블로그 발행 스크립트 v4
- google-genai (최신 패키지) 사용
- Gemini 2.0 Flash 모델 (무료)
- Selenium으로 티스토리 발행
"""

import os
import json
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

from google import genai
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ── 환경변수 ──────────────────────────────────────────────────────
GEMINI_API_KEY    = os.environ["GEMINI_API_KEY"]
TISTORY_EMAIL     = os.environ["TISTORY_EMAIL"]
TISTORY_PASSWORD  = os.environ["TISTORY_PASSWORD"]
TISTORY_BLOG_URL  = os.environ["TISTORY_BLOG_URL"]

client = genai.Client(api_key=GEMINI_API_KEY)
MODEL  = "gemini-2.5-flash"  # 무료 티어 지원 모델


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 1 · 트렌드 수집
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_google_trends() -> list[str]:
    try:
        res = requests.get(
            "https://trends.google.com/trending/rss?geo=KR",
            timeout=10, headers={"User-Agent": "Mozilla/5.0"}
        )
        root = ET.fromstring(res.text)
        return [el.text.strip() for el in root.findall(".//item/title") if el.text][:20]
    except Exception as e:
        print(f"[Google Trends 오류] {e}")
        return []

def collect_trends() -> list[str]:
    print("트렌드 수집 중...")
    keywords = fetch_google_trends()
    # 수집 실패 시 기본 키워드
    if not keywords:
        keywords = ["2026 청년 지원금", "청년도약계좌", "정부 보조금", "실업급여 신청", "건강보험료 환급"]
    print(f"  수집된 키워드 {len(keywords)}개")
    return keywords


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 2 · 주제 선정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def select_topic(keywords: list[str]) -> dict:
    print("주제 선정 중...")
    prompt = f"""
한국 블로그 SEO 전문가로서 아래 트렌드 키워드 중 블로그 주제 1개를 선정하세요.

선정 기준:
1. 금융/정책/건강 카테고리 우선 (광고 단가 높음)
2. 정보성 + 생활밀착형 (독자가 즉시 행동 가능)
3. 2026년 현재 유효한 정보

반드시 순수 JSON만 출력 (마크다운, 코드블록, 설명 없이):
{{"topic":"블로그제목","main_keyword":"핵심키워드","sub_keywords":["연관1","연관2","연관3"],"category":"카테고리"}}

트렌드 키워드:
{chr(10).join(f"- {k}" for k in keywords[:25])}
"""
    res = client.models.generate_content(model=MODEL, contents=prompt)
    raw = res.text.strip()
    # 코드블록 제거
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else parts[0]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        topic = json.loads(raw.strip())
        print(f"  선정 주제: {topic['topic']}")
        return topic
    except:
        return {
            "topic": keywords[0],
            "main_keyword": keywords[0],
            "sub_keywords": ["신청방법", "자격조건", "지원금액"],
            "category": "정보"
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 3 · 글 + 카드뉴스 생성
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_post(topic: dict) -> dict:
    print("글 작성 중...")
    today = datetime.now().strftime("%Y년 %m월 %d일")
    prompt = f"""
한국 최고의 SEO/GEO 블로그 작성 전문가로서 티스토리 포스팅을 작성하세요.

주제: {topic['topic']}
핵심 키워드: {topic['main_keyword']}
연관 키워드: {", ".join(topic['sub_keywords'])}
작성일: {today}

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
<div style="font-size:11px;opacity:0.65;margin-bottom:6px;">01 · 핵심요약</div>
<div style="font-size:19px;font-weight:500;margin-bottom:10px;">카드 제목</div>
<div style="font-size:13px;opacity:0.88;line-height:1.7;">내용</div>
</div>
색상: 핵심=#3C3489 통계=#0F6E56 주의=#854F0B 절차=#185FA5

[출력] 순수 JSON만 (마크다운/코드블록 없이):
{{"title":"제목","meta_description":"설명150자이내","tags":["태그1","태그2","태그3","태그4","태그5"],"content":"HTML본문전체"}}
"""
    res = client.models.generate_content(model=MODEL, contents=prompt)
    raw = res.text.strip()
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else parts[0]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        post = json.loads(raw.strip())
        print(f"  제목: {post['title']}")
        print(f"  본문 길이: {len(post['content'])}자")
        return post
    except Exception as e:
        print(f"  JSON 파싱 오류: {e}")
        return {
            "title": topic["topic"],
            "meta_description": "",
            "tags": topic["sub_keywords"],
            "content": raw
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 4 · Selenium 발행
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36")
    return webdriver.Chrome(options=options)

def kakao_login(driver, wait):
    print("  카카오 로그인 중...")
    driver.get("https://www.tistory.com/auth/login")
    time.sleep(2)

    kakao_btn = wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, "a.btn_login.link_kakao_id")
    ))
    kakao_btn.click()
    time.sleep(2)

    wait.until(EC.presence_of_element_located((By.ID, "loginId--1"))).send_keys(TISTORY_EMAIL)
    driver.find_element(By.ID, "password--2").send_keys(TISTORY_PASSWORD)
    driver.find_element(By.CSS_SELECTOR, "button.btn_g.highlight.submit").click()
    time.sleep(3)
    print("  로그인 완료")

def publish_post(driver, wait, post: dict):
    print("  글 발행 중...")
    driver.get(f"{TISTORY_BLOG_URL}/manage/newpost")
    time.sleep(3)

    # 제목
    title = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "input#post-title-inp, textarea[placeholder*='제목']")
    ))
    title.clear()
    title.send_keys(post["title"])
    time.sleep(1)

    # HTML 모드 전환
    try:
        html_btn = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "button.btn_switch, button[data-type='html'], .editor-mode-html")
        ))
        html_btn.click()
        time.sleep(1)
    except:
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(driver).key_down(Keys.CONTROL).key_down(Keys.SHIFT).send_keys("h").key_up(Keys.SHIFT).key_up(Keys.CONTROL).perform()
        time.sleep(1)

    # 본문 입력
    driver.execute_script("""
        var selectors = ['div.CodeMirror textarea', '#content-area', '.editor-content textarea'];
        for (var s of selectors) {
            var el = document.querySelector(s);
            if (el) {
                var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                nativeInputValueSetter.call(el, arguments[0]);
                el.dispatchEvent(new Event('input', { bubbles: true }));
                break;
            }
        }
    """, post["content"])
    time.sleep(1)

    # 태그
    try:
        tag_input = driver.find_element(
            By.CSS_SELECTOR, "input#tagText, input[placeholder*='태그']"
        )
        for tag in post.get("tags", [])[:5]:
            tag_input.send_keys(tag)
            tag_input.send_keys(Keys.RETURN)
            time.sleep(0.3)
    except Exception as e:
        print(f"  태그 건너뜀: {e}")

    # 발행
    try:
        publish_btn = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "button.btn_publish, button#publish-btn, button[data-action='publish']")
        ))
        publish_btn.click()
        time.sleep(2)

        try:
            public_opt = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "label[for='open20'], input[value='20'], .btn-open-public")
            ))
            public_opt.click()
            time.sleep(0.5)
            driver.find_element(
                By.CSS_SELECTOR, "button.btn_confirm, button.btn-publish-confirm, button.btn_action"
            ).click()
            time.sleep(2)
        except:
            pass

        print(f"  발행 완료!")
    except Exception as e:
        print(f"  발행 오류: {e}")

def publish_to_tistory(post: dict):
    driver = get_driver()
    wait   = WebDriverWait(driver, 20)
    try:
        kakao_login(driver, wait)
        publish_post(driver, wait, post)
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
    topic    = select_topic(keywords)
    post     = generate_post(topic)
    publish_to_tistory(post)

    print(f"\n{'='*50}")
    print("자동화 완료!")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
