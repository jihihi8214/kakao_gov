import requests
from bs4 import BeautifulSoup
import json
import os
import time
import subprocess
from datetime import datetime, timedelta, timezone
import urllib3
import google.generativeai as genai

try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except Exception:
    # zoneinfo 데이터가 없는 환경 대비 고정 오프셋으로 대체
    KST = timezone(timedelta(hours=9))

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. API 키 금고에서 꺼내오기
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    with open(os.path.join(BASE_DIR, "secret.txt"), "r") as f:
        GOOGLE_API_KEY = f.read().strip()
    genai.configure(api_key=GOOGLE_API_KEY)
except Exception as e:
    print(f"❌ secret.txt 파일이 없거나 구글 API 키를 읽을 수 없습니다: {e}")
    exit()

# ==========================================
# 1-1. Gemini 모델 자동 선택 (fallback 포함)
# ==========================================
# list_models()에 뜨는 모델이라도 실제로 이 API 키로는 호출이 막혀있는 경우가 있어서
# (예: "gemini-2.5-flash is no longer available to new users"),
# 목록만 믿지 않고 실제로 호출해보고 실패하면 다음 후보로 자동 전환한다.
_MODEL_STATE = {"working_name": None, "candidates": None}

def _get_model_candidates():
    if _MODEL_STATE["candidates"] is None:
        names = []
        try:
            for m in genai.list_models():
                methods = getattr(m, "supported_generation_methods", [])
                if "generateContent" in methods and "flash" in m.name.lower():
                    names.append(m.name)
        except Exception as e:
            print(f"❌ 모델 목록 조회 실패: {e}")
        # 신규 키에서 자주 막히는 정확히 'gemini-2.5-flash'인 이름은 뒤로 미루고 나머지부터 시도
        names.sort(key=lambda n: n.rstrip("/").endswith("gemini-2.5-flash"))
        _MODEL_STATE["candidates"] = names
    return _MODEL_STATE["candidates"]

def generate_with_fallback(prompt):
    if _MODEL_STATE["working_name"]:
        try:
            return genai.GenerativeModel(_MODEL_STATE["working_name"]).generate_content(prompt)
        except Exception:
            _MODEL_STATE["working_name"] = None  # 캐시된 모델도 막히면 다시 탐색

    for name in list(_get_model_candidates()):
        try:
            resp = genai.GenerativeModel(name).generate_content(prompt)
            if _MODEL_STATE["working_name"] != name:
                print(f"✅ 사용할 Gemini 모델: {name}")
            _MODEL_STATE["working_name"] = name
            return resp
        except Exception as e:
            print(f"   (모델 {name} 사용 불가: {e})")
            continue

    raise RuntimeError("사용 가능한 Gemini 모델을 찾지 못했습니다.")

try:
    with open(os.path.join(BASE_DIR, "secret_naver.txt"), "r") as f:
        naver_keys = f.read().strip().split('\n')
        NAVER_CLIENT_ID = naver_keys[0].strip()
        NAVER_CLIENT_SECRET = naver_keys[1].strip()
except Exception as e:
    print("❌ secret_naver.txt 파일이 없거나 네이버 API 키를 읽을 수 없습니다.")
    exit()

# ==========================================
# 2. 기본 설정
# ==========================================
AGENCIES = [
    "과학기술정보통신부", "방송미디어통신위원회", "개인정보보호위원회",
    "공정거래위원회", "행정안전부", "산업통상부", "문화체육관광부",
    "국무조정실·국무총리비서실", "금융위원회", "금융감독원"
]

DATA_DIR = os.path.join(BASE_DIR, "data_personnel")

# ==========================================
# 3. 날짜 계산
# ==========================================
def get_search_dates(now: datetime):
    """
    평일에만 실행하는 것을 전제로, "직전 실행 시각(오전 9:45) 직후 ~ 이번 실행 시각"을
    검색 범위로 잡는다 (자정 기준이 아니라 실행 시각 기준).
    - 화~금요일: 전날 09:46 ~ 오늘 실행 시각(now)
    - 월요일: 지난 금요일 09:46 ~ 오늘(월요일) 실행 시각(now)
    """
    end_date = now
    if now.weekday() == 0:  # 월요일 -> 지난 금요일 기준
        prev_business_day = now - timedelta(days=3)
    else:  # 화~금요일 -> 전날 기준
        prev_business_day = now - timedelta(days=1)
    start_date = prev_business_day.replace(hour=9, minute=46, second=0, microsecond=0)
    period_label = f"{start_date.strftime('%m.%d %H:%M')} ~ {end_date.strftime('%m.%d %H:%M')}"
    return start_date, end_date, period_label

# ==========================================
# 4. 네이버 뉴스 API 검색 및 기사 본문 싹쓸이 + AI 요약
# ==========================================
def fetch_naver_news_and_summarize(agency, keyword, start_date, end_date, prev_info):
    # 가운데 점(·)이 있는 부처는 쪼개서 'OR(|)' 조건으로 검색
    # 참고: 큰따옴표로 감싼 정확 문구 검색은 네이버 API에서 실제 존재하는 기사도
    # 누락시키는 경우가 있어 사용하지 않는다 (다음뉴스 테스트에서도 따옴표 없이 잘 잡혔음).
    if '·' in agency:
        parts = agency.split('·')  # ['국무조정실', '국무총리비서실']
        if keyword == "인사":
            search_query = f"[{keyword}] {parts[0]} | [{keyword}] {parts[1]}"
        else:
            search_query = f"{keyword} {parts[0]} | {keyword} {parts[1]}"
    else:
        if keyword == "인사":
            search_query = f"[{keyword}] {agency}"
        else:
            search_query = f"{keyword} {agency}"

    url = f"https://openapi.naver.com/v1/search/news.json?query={search_query}&display=20&sort=date"

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }

    # 네이버가 로봇인 줄 알고 막는 것을 방지하기 위한 신분증
    web_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print(f"🔍 [{agency}] {keyword} 검색 중...", end="")
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()

        snippets = []
        for item in data.get('items', []):
            pub_date_str = item['pubDate']
            try:
                # 네이버가 주는 시간대 정보(예: +0900)를 버리지 않고 그대로 파싱해서
                # KST 기준 start_date/end_date와 시간대 어긋남 없이 비교한다.
                pub_date_obj = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %z")
            except Exception:
                continue

            if start_date <= pub_date_obj <= end_date:
                title = BeautifulSoup(item['title'], "html.parser").get_text()

                # 대괄호/화살괄호/기호 표기 + 구두점 없는 "기관명 인사"/"인사 기관명" 형태까지 폭넓게 인정
                bracket_match = (
                    f"[{keyword}]" in title or f"<{keyword}>" in title
                    or f"◆ {keyword}" in title or f"■ {keyword}" in title
                    or (keyword == "부고" and "[부음]" in title)
                )
                plain_match = keyword in title and any(p in title for p in ([agency] if '·' not in agency else agency.split('·')))
                # "인사하는", "인사말", "인사를 나누" 등 동사·인사말 용법은 제외
                verb_like = any(v in title for v in ["인사하는", "인사말", "인사를 나누", "인사 나누"])

                if (bracket_match or plain_match) and not verb_like:
                    naver_link = item.get('link', '')
                    article_body = ""

                    # 네이버 뉴스 링크(n.news.naver.com)면 직접 들어가서 본문을 통째로 긁어옴
                    if "n.news.naver.com" in naver_link:
                        try:
                            art_res = requests.get(naver_link, headers=web_headers, timeout=5)
                            art_soup = BeautifulSoup(art_res.text, "html.parser")
                            body_tag = art_soup.find("article", id="dic_area")
                            if body_tag:
                                article_body = body_tag.get_text(separator="\n", strip=True)
                        except Exception:
                            pass

                    if not article_body:
                        article_body = BeautifulSoup(item['description'], "html.parser").get_text()

                    snippets.append(f"[제목: {title}]\n내용: {article_body[:3000]}")

        if not snippets:
            print(" ➔ 관련 기사 없음 (패스 ⚡)")
            return "해당 없음"

        print(" ➔ 찐 기사 발견! (본문 확보 완료, AI 분석 중)")
        combined_text = "\n\n---\n\n".join(snippets)

        prompt = f"""
        다음은 네이버 뉴스에서 '{agency}'의 '{keyword}'와 관련된 기사 본문 모음이야.
        이 내용 중에서 실제 인사 이동이나 부고 내역을 추출해서 아래 형식으로만 대답해줘.

        [중요: 중복 제거 지시사항]
        아래는 최근에 이미 보고된 내역이야.
        <기존 내역 시작>
        {prev_info}
        <기존 내역 끝>

        기사 내용에 위 '기존 내역'과 겹치는 사람이나 직책이 있다면 오늘 결과에서 무조건 제외해. 오직 "새롭게 추가된 사람"만 추출해야 해.
        중복된 사람을 제외하고 났을 때 남은 사람이 한 명도 없거나, 애초에 관련 없는 기사라면 오직 '해당 없음'이라고만 대답해. (설명 추가 절대 금지)

        [주의] 부고 검색 결과 중, 고인과의 관계로 언급된 인물이 국회의원 등 '{agency}'와 무관한 사람이면 제외해. 반드시 '{agency}' 소속 인물 본인 또는 그 가족의 상(喪)이어야 채택해.

        [출력 형식 예시 - 인사]
        ◇ 국장급 승진
        - 정책기획관 홍길동
        ◇ 과장급 전보
        - 홍보담당관 김철수

        [출력 형식 예시 - 부고]
        ※ 부고 기사의 경우 기사 원문에 있는 기호(▲, ■ 등)나 기자/언론사 이름(예: 연합뉴스)은 모두 제거해.
        ※ 첫 줄에는 [우리 부처 관계자(소속 및 직책) 상명]을 적고, 두 번째 줄에는 [고인 이름 별세 = 빈소, 발인 일시]를 원문 느낌을 살려서 그대로 적어줘.
        황갑성(국무총리비서실 민정민원 팀장) 장인상
        이금록 씨 별세 = 25일, 광주 국빈장례문화원 301호, 발인 27일 낮 12시 30분

        기사 내용:
        {combined_text}
        """

        response = generate_with_fallback(prompt)
        result = response.text.strip()

        result = result.replace("[출력 형식 예시 - 인사]", "").replace("[출력 형식 예시 - 부고]", "").strip()
        result = result.replace("※ 부고 기사의 경우 기사 원문에 있는 기호(▲, ■ 등)나 기자/언론사 이름(예: 연합뉴스)은 모두 제거해.", "")
        result = result.replace("※ 첫 줄에는 [우리 부처 관계자(소속 및 직책) 상명]을 적고, 두 번째 줄에는 [고인 이름 별세 = 빈소, 발인 일시]를 원문 느낌을 살려서 그대로 적어줘.", "").strip()

        time.sleep(1)

        if not result or "해당 없음" in result:
            return "해당 없음"

        return result

    except Exception as e:
        print(f"❌ 검색 에러: {e}")
        return "해당 없음"

# ==========================================
# 5. 깃허브 배달
# ==========================================
def push_to_github(file_name):
    try:
        print("\n🚀 깃허브로 인사/부고 데이터를 배달합니다...")

        subprocess.run(["git", "add", "data_personnel"], cwd=BASE_DIR, check=True)

        status = subprocess.run(
            ["git", "status", "--porcelain", "data_personnel"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=True
        )

        if not status.stdout.strip():
            print("✨ 변경된 인사/부고 데이터가 없습니다.")
            return

        commit_msg = f"Update personnel: {file_name}"
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=BASE_DIR, check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=BASE_DIR, check=True)

        print("✅ 배달 완료!")

    except Exception as e:
        print(f"✨ 변경된 내역이 없거나 배달을 건너뜁니다: {e}")

def main():
    now = datetime.now(KST)
    start_date, end_date, period_label = get_search_dates(now)
    date_key = now.strftime("%Y-%m-%d")

    print(f"📅 다음뉴스/네이버 인사·부고 수집 시작 (기간: {period_label})\n")

    # 최근 최대 4일 치의 기존 데이터를 모아 중복 필터 가동
    print("📂 최근 4일 치 데이터를 찾아 중복 필터를 가동합니다...")
    prev_data_list = []

    for i in range(1, 6):
        check_date_str = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        filepath = os.path.join(DATA_DIR, f"{check_date_str}.json")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                prev_data_list.append(json.load(f))
            print(f"   ✔️ {check_date_str} 데이터 확보 완료")

        if len(prev_data_list) == 4:
            break

    if not prev_data_list:
        print("   (참고) 이전 데이터가 없어 필터 없이 수집합니다.\n")
    else:
        print()

    final_data = {
        "date": date_key,
        "period": period_label,
        "인사": {},
        "부고": {}
    }

    for agency in AGENCIES:
        prev_insa = ""
        prev_bugo = ""

        for p_data in prev_data_list:
            insa_text = p_data["인사"].get(agency, "해당 없음")
            if insa_text != "해당 없음":
                prev_insa += insa_text + "\n"

            bugo_text = p_data["부고"].get(agency, "해당 없음")
            if bugo_text != "해당 없음":
                prev_bugo += bugo_text + "\n"

        if not prev_insa.strip():
            prev_insa = "해당 없음"
        if not prev_bugo.strip():
            prev_bugo = "해당 없음"

        final_data["인사"][agency] = fetch_naver_news_and_summarize(agency, "인사", start_date, end_date, prev_insa)
        final_data["부고"][agency] = fetch_naver_news_and_summarize(agency, "부고", start_date, end_date, prev_bugo)

    os.makedirs(DATA_DIR, exist_ok=True)
    filepath = os.path.join(DATA_DIR, f"{date_key}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {date_key} 데이터 저장 완료!")
    push_to_github(date_key)

if __name__ == "__main__":
    main()
