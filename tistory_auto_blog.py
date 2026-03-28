"""
티스토리 완전 자동화 블로그 발행 스크립트 v6
- 순서 변경: 로그인 먼저 → 성공 시에만 글 생성
- 카카오 봇 차단 우회: 쿠키 기반 세션 유지
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
# Selenium 드라이버
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    # 봇 감지 우회
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)
    # navigator.webdriver 숨기기
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 1 · 로그인 먼저 (성공해야만 이후 진행)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def kakao_login(driver) -> bool:
    """로그인 성공 시 True, 실패 시 False 반환"""
    wait = WebDriverWait(driver, 15)
    print("  카카오 로그인 시도...")

    driver.get("https://www.tistory.com/auth/login")
    time.sleep(2)

    try:
        wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "a.btn_login.link_kakao_id")
        )).click()
        time.sleep(2)

        # 이메일 입력 (자연스럽게 한 글자씩)
        email_el = wait.until(EC.presence_of_element_located((By.ID, "loginId--1")))
        for char in TISTORY_EMAIL:
            email_el.send_keys(char)
            time.sleep(0.05)

        time.sleep(0.5)

        # 비밀번호 입력
        pw_el = driver.find_element(By.ID, "password--2")
        for char in TISTORY_PASSWORD:
            pw_el.send_keys(char)
            time.sleep(0.05)

        time.sleep(0.5)
        driver.find_element(By.CSS_SELECTOR, "button.btn_g.highlight.submit").click()
        time.sleep(4)

        # ── 로그인 성공 여부 확인 ─────────────────────────────────
        current = driver.current_url
        print(f"  로그인 후 URL: {current}")

        # 티스토리 메인 또는 블로그 페이지면 성공
        if "tistory.com" in current and "accounts.kakao.com" not in current and "login" not in current:
            print("  로그인 성공!")
            return True

        # 아직 카카오 페이지에 있으면 추가 처리 필요
        if "accounts.kakao.com" in current:
            print("  카카오 추가 인증 페이지 감지 — 스크린샷 저장")
            driver.save_screenshot("/tmp/login_kakao.png")

            # "나중에 하기" 또는 "건너뛰기" 버튼 처리
            skip_selectors = [
                "button.btn_cancel",
                "a.btn_later",
                "button[data-action='skip']",
                ".btn_skip",
            ]
            for sel in skip_selectors:
                try:
                    btn = driver.find_element(By.CSS_SELECTOR, sel)
                    btn.click()
                    time.sleep(2)
                    print(f"  건너뛰기 클릭: {sel}")
                    break
                except:
                    continue

            # 다시 티스토리로
            driver.get(TISTORY_BLOG_URL)
            time.sleep(3)
            current = driver.current_url
            print(f"  재이동 후 URL: {current}")

            if "login" not in current and "accounts.kakao" not in current:
                print("  로그인 성공!")
                return True

        print("  로그인 실패 — 글 생성 건너뜀")
        driver.save_screenshot("/tmp/login_fail.png")
        return False

    except Exception as e:
        print(f"  로그인 오류: {e}")
        driver.save_screenshot("/tmp/login_error.png")
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
순수 JSON만:
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

순수 JSON만:
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
# STEP 5 · 글 발행
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

def publish_post(driver, post: dict):
    print("  글쓰기 페이지 이동...")
    driver.get(f"{TISTORY_BLOG_URL}/manage/newpost")
    time.sleep(4)
    print(f"  현재 URL: {driver.current_url}")
    driver.save_screenshot("/tmp/newpost.png")

    # 제목
    title_el = find_any(driver, [
        "input#post-title-inp", "input.txt_inp",
        "input[name='title']", "input[placeholder*='제목']",
        ".tit_area input", "#post-title",
    ], timeout=15)

    if not title_el:
        print("  [실패] 제목창 없음 — 로그인 상태 아닐 수 있음")
        driver.save_screenshot("/tmp/newpost_fail.png")
        return False

    title_el.clear()
    title_el.send_keys(post["title"])
    time.sleep(1)

    # HTML 모드 전환
    html_btn = find_any(driver, [
        "button.btn_switch", "button[data-type='html']",
        ".editor-mode-html", "button[aria-label*='HTML']",
    ], timeout=5)
    if html_btn:
        html_btn.click()
        time.sleep(1)
        print("  HTML 모드 전환")
    else:
        ActionChains(driver).key_down(Keys.CONTROL).key_down(Keys.SHIFT).send_keys("h").key_up(Keys.SHIFT).key_up(Keys.CONTROL).perform()
        time.sleep(1)

    # 본문 입력
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
# MAIN — 순서: 로그인 → 성공 시 글 생성 → 발행
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    print(f"\n{'='*50}")
    print(f"티스토리 자동 발행 시작: {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'='*50}\n")

    driver = get_driver()

    try:
        # 1. 로그인 먼저
        login_ok = kakao_login(driver)

        if not login_ok:
            print("\n로그인 실패 — 글 생성 없이 종료 (API 사용량 절약)")
            return

        # 2. 로그인 성공 후에만 트렌드 수집 + 글 생성
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
