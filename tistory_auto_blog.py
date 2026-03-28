"""
티스토리 완전 자동화 블로그 발행 스크립트 v5
- 디버그 스크린샷 추가
- 제목/본문 셀렉터 다중 시도
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
from selenium.webdriver.common.action_chains import ActionChains

# ── 환경변수 ──────────────────────────────────────────────────────
GEMINI_API_KEY    = os.environ["GEMINI_API_KEY"]
TISTORY_EMAIL     = os.environ["TISTORY_EMAIL"]
TISTORY_PASSWORD  = os.environ["TISTORY_PASSWORD"]
TISTORY_BLOG_URL  = os.environ["TISTORY_BLOG_URL"]

client = genai.Client(api_key=GEMINI_API_KEY)
MODEL  = "gemini-2.5-flash"


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
        root = ET.fromstring(res.text)
        keywords = [el.text.strip() for el in root.findall(".//item/title") if el.text][:20]
    except Exception as e:
        print(f"  트렌드 오류: {e}")
        keywords = []
    if not keywords:
        keywords = ["2026 청년 지원금", "청년도약계좌", "정부 보조금", "실업급여 신청", "건강보험료 환급"]
    print(f"  수집된 키워드 {len(keywords)}개")
    return keywords


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 2 · 주제 선정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def select_topic(keywords: list[str]) -> dict:
    print("주제 선정 중...")
    prompt = f"""한국 블로그 SEO 전문가로서 아래 키워드 중 블로그 주제 1개를 선정하세요.
금융/정책/건강 카테고리 우선, 2026년 유효한 정보.
순수 JSON만 출력:
{{"topic":"제목","main_keyword":"핵심키워드","sub_keywords":["연관1","연관2","연관3"],"category":"카테고리"}}

키워드:
{chr(10).join(f"- {k}" for k in keywords[:25])}"""

    raw = client.models.generate_content(model=MODEL, contents=prompt).text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    try:
        topic = json.loads(raw.strip())
        print(f"  선정 주제: {topic['topic']}")
        return topic
    except:
        return {"topic": keywords[0], "main_keyword": keywords[0],
                "sub_keywords": ["신청방법", "자격조건", "지원금액"], "category": "정보"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 3 · 글 생성
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_post(topic: dict) -> dict:
    print("글 작성 중...")
    prompt = f"""한국 SEO/GEO 블로그 전문가로서 티스토리 포스팅 작성.
주제: {topic['topic']} | 키워드: {topic['main_keyword']} | 날짜: {datetime.now().strftime("%Y년 %m월 %d일")}

규칙: H2 4~6개, 키워드 5회 이상, 1500자 이상, FAQ 3개 이상, 카드뉴스 3~4개 삽입.
카드뉴스 형식:
<div style="background:#3C3489;border-radius:14px;padding:28px 24px;color:#fff;margin:1.5rem 0;">
<div style="font-size:11px;opacity:0.65;margin-bottom:6px;">01 · 섹션</div>
<div style="font-size:19px;font-weight:500;margin-bottom:10px;">제목</div>
<div style="font-size:13px;line-height:1.7;">내용</div></div>

순수 JSON만 출력:
{{"title":"제목","meta_description":"설명","tags":["태그1","태그2","태그3","태그4","태그5"],"content":"HTML본문"}}"""

    raw = client.models.generate_content(model=MODEL, contents=prompt).text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    try:
        post = json.loads(raw.strip())
        print(f"  제목: {post['title']} | 길이: {len(post['content'])}자")
        return post
    except Exception as e:
        print(f"  JSON 파싱 오류: {e}")
        return {"title": topic["topic"], "meta_description": "",
                "tags": topic["sub_keywords"], "content": raw}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 4 · Selenium 발행
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_driver():
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
    wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "a.btn_login.link_kakao_id"))).click()
    time.sleep(2)
    wait.until(EC.presence_of_element_located((By.ID, "loginId--1"))).send_keys(TISTORY_EMAIL)
    driver.find_element(By.ID, "password--2").send_keys(TISTORY_PASSWORD)
    driver.find_element(By.CSS_SELECTOR, "button.btn_g.highlight.submit").click()
    time.sleep(3)
    print(f"  로그인 완료 — 현재 URL: {driver.current_url}")

def find_element_any(driver, selectors: list, timeout=10):
    """여러 셀렉터 중 먼저 찾히는 요소 반환"""
    wait = WebDriverWait(driver, timeout)
    for sel in selectors:
        try:
            el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
            print(f"  셀렉터 발견: {sel}")
            return el
        except:
            continue
    return None

def debug_screenshot(driver, name: str):
    """디버그용 스크린샷 저장"""
    path = f"/tmp/{name}.png"
    driver.save_screenshot(path)
    print(f"  스크린샷 저장: {path}")
    # 현재 페이지 주요 input/textarea 출력
    els = driver.find_elements(By.CSS_SELECTOR, "input, textarea")
    print(f"  페이지 input/textarea 수: {len(els)}")
    for el in els[:10]:
        print(f"    - tag={el.tag_name} id={el.get_attribute('id')} class={el.get_attribute('class')[:50] if el.get_attribute('class') else ''} placeholder={el.get_attribute('placeholder')}")

def publish_post(driver, wait, post: dict):
    print("  글쓰기 페이지 이동 중...")
    driver.get(f"{TISTORY_BLOG_URL}/manage/newpost")
    time.sleep(4)
    print(f"  현재 URL: {driver.current_url}")
    debug_screenshot(driver, "01_newpost")

    # ── 제목 입력 ─────────────────────────────────────────────────
    title_selectors = [
        "input#post-title-inp",
        "input.txt_inp",
        "input[name='title']",
        "textarea[placeholder*='제목']",
        "input[placeholder*='제목']",
        ".tit_area input",
        "#post-title",
    ]
    title_el = find_element_any(driver, title_selectors, timeout=15)
    if title_el:
        title_el.clear()
        title_el.send_keys(post["title"])
        print(f"  제목 입력 완료")
    else:
        print("  [경고] 제목 입력창을 찾지 못했습니다")
        debug_screenshot(driver, "02_title_fail")

    time.sleep(1)

    # ── HTML 모드 전환 ────────────────────────────────────────────
    html_selectors = [
        "button.btn_switch",
        "button[data-type='html']",
        ".editor-mode-html",
        "button[aria-label*='HTML']",
        ".btn_editor_switch",
    ]
    html_btn = find_element_any(driver, html_selectors, timeout=5)
    if html_btn:
        html_btn.click()
        print("  HTML 모드 전환 완료")
        time.sleep(1)
    else:
        print("  HTML 버튼 없음 — 단축키 시도 (Ctrl+Shift+H)")
        ActionChains(driver).key_down(Keys.CONTROL).key_down(Keys.SHIFT).send_keys("h").key_up(Keys.SHIFT).key_up(Keys.CONTROL).perform()
        time.sleep(1)

    debug_screenshot(driver, "03_html_mode")

    # ── 본문 입력 ─────────────────────────────────────────────────
    injected = driver.execute_script("""
        var selectors = [
            'div.CodeMirror textarea',
            'textarea#content',
            '#content-area',
            '.editor-content textarea',
            'iframe'
        ];
        for (var s of selectors) {
            var el = document.querySelector(s);
            if (el) {
                if (el.tagName === 'TEXTAREA') {
                    var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                    setter.call(el, arguments[0]);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    return 'textarea:' + s;
                }
            }
        }
        return 'not_found';
    """, post["content"])
    print(f"  본문 주입 결과: {injected}")
    time.sleep(1)

    debug_screenshot(driver, "04_content")

    # ── 태그 입력 ─────────────────────────────────────────────────
    try:
        tag_input = driver.find_element(By.CSS_SELECTOR, "input#tagText, input[placeholder*='태그']")
        for tag in post.get("tags", [])[:5]:
            tag_input.send_keys(tag)
            tag_input.send_keys(Keys.RETURN)
            time.sleep(0.3)
        print("  태그 입력 완료")
    except Exception as e:
        print(f"  태그 건너뜀: {e}")

    # ── 발행 ──────────────────────────────────────────────────────
    publish_selectors = [
        "button.btn_publish",
        "button#publish-btn",
        "button[data-action='publish']",
        "button.btn-publish",
        ".area_btn button.btn_point",
    ]
    pub_btn = find_element_any(driver, publish_selectors, timeout=10)
    if pub_btn:
        pub_btn.click()
        time.sleep(2)
        debug_screenshot(driver, "05_after_publish_click")

        # 공개 팝업 처리
        try:
            public_opt = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "label[for='open20'], input[value='20'], .btn-open-public")
            ))
            public_opt.click()
            time.sleep(0.5)
            driver.find_element(By.CSS_SELECTOR,
                "button.btn_confirm, button.btn-publish-confirm, button.btn_action"
            ).click()
            time.sleep(2)
        except:
            pass

        print(f"  발행 완료! URL: {driver.current_url}")
        debug_screenshot(driver, "06_final")
    else:
        print("  [오류] 발행 버튼을 찾지 못했습니다")
        debug_screenshot(driver, "05_publish_fail")

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
    print("완료!")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
