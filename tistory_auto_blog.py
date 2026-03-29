"""
티스토리 완전 자동화 블로그 발행 스크립트 v8
- 쿠키 판정 수정: __T_ 계열 감지
- 로그인 불안정 대비: 최대 3회 재시도
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
TISTORY_BLOG_URL  = os.environ["TISTORY_BLOG_URL"].rstrip("/")

client = genai.Client(api_key=GEMINI_API_KEY)
MODEL  = "gemini-2.5-flash"

def gemini_call(prompt: str, max_retry=5) -> str:
    """429 Rate Limit 시 자동 재시도"""
    for attempt in range(1, max_retry + 1):
        try:
            res = client.models.generate_content(model=MODEL, contents=prompt)
            return res.text.strip()
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                wait = 65  # 65초 대기
                print(f"  API 한도 초과 — {wait}초 후 재시도 ({attempt}/{max_retry})")
                time.sleep(wait)
            else:
                raise
    raise Exception("Gemini API 재시도 초과")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 드라이버
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 로그인 성공 여부 판정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def is_logged_in(driver) -> bool:
    """블로그 관리 페이지 직접 접근으로 로그인 확인"""
    driver.get(f"{TISTORY_BLOG_URL}/manage")
    time.sleep(3)
    current = driver.current_url
    cookies = [c['name'] for c in driver.get_cookies()]
    print(f"  보유 쿠키: {cookies}")
    print(f"  관리 페이지 URL: {current}")

    # 관리 페이지 접근 성공 = 로그인 확실
    if "login" not in current and ("manage" in current or TISTORY_BLOG_URL.split("//")[1] in current):
        print("  로그인 확인 (관리 페이지 접근 성공)")
        return True

    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 1 · 로그인 (최대 3회 재시도)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def kakao_login(driver) -> bool:
    wait = WebDriverWait(driver, 15)

    for attempt in range(1, 4):  # 최대 3회
        print(f"  로그인 시도 {attempt}/3...")
        try:
            driver.get("https://www.tistory.com/auth/login")
            time.sleep(2)

            wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "a.btn_login.link_kakao_id")
            )).click()
            time.sleep(2)

            # 이메일
            email_el = wait.until(EC.presence_of_element_located((By.ID, "loginId--1")))
            email_el.clear()
            for char in TISTORY_EMAIL:
                email_el.send_keys(char)
                time.sleep(0.04)
            time.sleep(0.5)

            # 비밀번호
            pw_el = driver.find_element(By.ID, "password--2")
            pw_el.clear()
            for char in TISTORY_PASSWORD:
                pw_el.send_keys(char)
                time.sleep(0.04)
            time.sleep(0.5)

            driver.find_element(By.CSS_SELECTOR, "button.btn_g.highlight.submit").click()
            time.sleep(4)

            # 추가 팝업 건너뛰기
            for sel in ["button.btn_cancel", "a.btn_later", ".btn_skip"]:
                try:
                    driver.find_element(By.CSS_SELECTOR, sel).click()
                    time.sleep(2)
                    print(f"  팝업 건너뜀")
                    break
                except:
                    continue

            # 로그인 성공 확인
            if is_logged_in(driver):
                print(f"  로그인 성공! ({attempt}회차)")
                return True
            else:
                print(f"  {attempt}회차 실패, 재시도...")
                time.sleep(3)

        except Exception as e:
            print(f"  {attempt}회차 오류: {e}")
            time.sleep(3)

    print("  3회 모두 실패")
    driver.save_screenshot("/tmp/login_fail.png")
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 2 · 트렌드 수집
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
        print(f"  트렌드 오류: {e}")
        keywords = []
    if not keywords:
        keywords = ["2026 청년 지원금", "청년도약계좌", "정부 보조금", "실업급여 신청", "건강보험료 환급"]
    print(f"  수집된 키워드 {len(keywords)}개")
    return keywords


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 3 · 주제 선정
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def select_topic(keywords: list[str]) -> dict:
    print("주제 선정 중...")
    prompt = f"""한국 블로그 SEO 전문가. 아래 키워드 중 주제 1개 선정.
금융/정책/건강 우선, 2026년 유효한 정보.
순수 JSON만 (마크다운 없이):
{{"topic":"제목","main_keyword":"핵심키워드","sub_keywords":["연관1","연관2","연관3"],"category":"카테고리"}}

키워드:
{chr(10).join(f"- {k}" for k in keywords[:25])}"""

    raw = gemini_call(prompt)
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
# STEP 4 · 글 생성
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_post(topic: dict) -> dict:
    print("글 작성 중...")
    prompt = f"""한국 SEO/GEO 블로그 전문가. 티스토리 포스팅 작성.
주제: {topic['topic']} | 키워드: {topic['main_keyword']} | 날짜: {datetime.now().strftime("%Y년 %m월 %d일")}

H2 4~6개, 키워드 5회 이상, 1500자 이상, FAQ 3개 이상.
카드뉴스 3~4개 삽입:
<div style="background:#3C3489;border-radius:14px;padding:28px 24px;color:#fff;margin:1.5rem 0;">
<div style="font-size:11px;opacity:0.65;margin-bottom:6px;">01 · 섹션</div>
<div style="font-size:19px;font-weight:500;margin-bottom:10px;">제목</div>
<div style="font-size:13px;line-height:1.7;">내용</div></div>

순수 JSON만 (마크다운 없이):
{{"title":"제목","meta_description":"설명","tags":["태그1","태그2","태그3","태그4","태그5"],"content":"HTML본문"}}"""

    raw = gemini_call(prompt)
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
# STEP 5 · 발행
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def find_any(driver, selectors, timeout=8):
    wait = WebDriverWait(driver, timeout)
    for sel in selectors:
        try:
            el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
            print(f"  발견: {sel}")
            return el
        except:
            continue
    return None

def publish_post(driver, post: dict) -> bool:
    print("  글쓰기 페이지 이동...")
    write_url = f"{TISTORY_BLOG_URL}/manage/newpost"
    driver.get(write_url)
    time.sleep(4)
    print(f"  현재 URL: {driver.current_url}")
    driver.save_screenshot("/tmp/newpost.png")

    if "login" in driver.current_url:
        print("  [실패] 글쓰기 페이지 접근 불가 — 세션 만료")
        return False

    # 제목
    title_el = find_any(driver, [
        "input#post-title-inp", "input.txt_inp",
        "input[name='title']", "input[placeholder*='제목']",
        ".tit_area input", "#post-title",
    ], timeout=15)

    if not title_el:
        print("  [실패] 제목창 없음")
        driver.save_screenshot("/tmp/title_fail.png")
        print(f"  페이지 타이틀: {driver.title}")
        for inp in driver.find_elements(By.TAG_NAME, "input")[:10]:
            print(f"    input id={inp.get_attribute('id')} placeholder={inp.get_attribute('placeholder')}")
        return False

    title_el.clear()
    title_el.send_keys(post["title"])
    time.sleep(1)
    print("  제목 입력 완료")

    # HTML 모드
    html_btn = find_any(driver, [
        "button.btn_switch", "button[data-type='html']",
        ".editor-mode-html", "button[aria-label*='HTML']",
    ], timeout=5)
    if html_btn:
        html_btn.click()
        time.sleep(1)
    else:
        ActionChains(driver).key_down(Keys.CONTROL).key_down(Keys.SHIFT).send_keys("h").key_up(Keys.SHIFT).key_up(Keys.CONTROL).perform()
        time.sleep(1)

    # 본문
    result = driver.execute_script("""
        var sels = ['div.CodeMirror textarea','textarea#content','#content-area','.editor-content textarea'];
        for (var s of sels) {
            var el = document.querySelector(s);
            if (el) {
                var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
                setter.call(el, arguments[0]);
                el.dispatchEvent(new Event('input',{bubbles:true}));
                return s;
            }
        }
        return 'not_found';
    """, post["content"])
    print(f"  본문 주입: {result}")
    time.sleep(1)

    # 태그
    try:
        tag_el = driver.find_element(By.CSS_SELECTOR, "input#tagText, input[placeholder*='태그']")
        for tag in post.get("tags", [])[:5]:
            tag_el.send_keys(tag)
            tag_el.send_keys(Keys.RETURN)
            time.sleep(0.3)
    except:
        pass

    # 발행
    pub_btn = find_any(driver, [
        "button.btn_publish", "button#publish-btn",
        "button[data-action='publish']", ".area_btn button.btn_point",
    ], timeout=10)

    if pub_btn:
        pub_btn.click()
        time.sleep(2)
        try:
            public_opt = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "label[for='open20'], input[value='20']")
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
        driver.save_screenshot("/tmp/published.png")
        return True
    else:
        print("  [실패] 발행 버튼 없음")
        driver.save_screenshot("/tmp/publish_fail.png")
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    print(f"\n{'='*50}")
    print(f"티스토리 자동 발행 시작: {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'='*50}\n")

    driver = get_driver()
    try:
        # 1. 로그인 (최대 3회)
        login_ok = kakao_login(driver)
        if not login_ok:
            print("\n로그인 실패 — 종료 (API 사용량 절약)")
            return

        # 2. 글 생성
        keywords = collect_trends()
        topic    = select_topic(keywords)
        post     = generate_post(topic)

        # 3. 발행
        publish_post(driver, post)

    finally:
        driver.quit()

    print(f"\n{'='*50}")
    print("완료!")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
