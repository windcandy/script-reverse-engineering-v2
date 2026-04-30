import json
import os
import requests
from datetime import datetime, timedelta
from pytrends.request import TrendReq
from googleapiclient.discovery import build

# 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
API_DIR = os.path.join(BASE_DIR, "..", "API")

with open(os.path.join(API_DIR, "youtube_api_key.json")) as f:
    YOUTUBE_API_KEY = json.load(f)["api_key"]

with open(os.path.join(API_DIR, "naver_api_key.json")) as f:
    naver = json.load(f)
    NAVER_CLIENT_ID = naver["client_id"]
    NAVER_CLIENT_SECRET = naver["client_secret"]

# 타겟: 30~50대
TARGET_AUDIENCE = "30~50대"

# 기간 설정
# 기본값: 최근 7일 ("now 7-d")
# 유저가 기간을 언급하면 아래 TIMEFRAME을 직접 변경
# 예시: "now 7-d" / "today 1-m" / "today 3-m" / "today 12-m"
TIMEFRAME = "now 7-d"


# ── 1. Google Trends ───────────────────────────────────
def search_trends(keywords, timeframe=TIMEFRAME):
    """키워드 검색량 비교 + 연관 키워드 추출"""
    print(f"\n[Google Trends] 검색량 분석 중... (기간: {timeframe})")
    pytrends = TrendReq(hl="ko", tz=540)

    chunks = [keywords[i:i+5] for i in range(0, len(keywords), 5)]
    results = {}

    for chunk in chunks:
        pytrends.build_payload(chunk, cat=0, timeframe=timeframe, geo="KR")
        df = pytrends.interest_over_time()

        if not df.empty:
            for kw in chunk:
                if kw in df.columns:
                    results[kw] = {
                        "평균": int(df[kw].mean()),
                        "최근값": int(df[kw].iloc[-1]),
                        "추세": "상승" if df[kw].iloc[-1] > df[kw].mean() else "하락"
                    }

    # 연관 키워드 (첫 번째 키워드 기준)
    pytrends.build_payload([keywords[0]], timeframe=timeframe, geo="KR")
    related = pytrends.related_queries()
    related_top = []
    if keywords[0] in related and related[keywords[0]]["top"] is not None:
        related_top = related[keywords[0]]["top"]["query"].tolist()[:5]

    return results, related_top


# ── 2. YouTube API ─────────────────────────────────────
def search_youtube(keyword, timeframe=TIMEFRAME, max_results=5):
    """경쟁 영상 조회수 + 오션 판별 (레드/퍼플/블루)"""
    print(f"\n[YouTube] '{keyword}' 경쟁 현황 분석 중... (기간: {timeframe})")
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    # 기간 → publishedAfter 변환
    published_after = _timeframe_to_iso(timeframe)

    search_params = dict(
        q=keyword,
        part="snippet",
        type="video",
        regionCode="KR",
        relevanceLanguage="ko",
        maxResults=max_results,
    )
    if published_after:
        search_params["publishedAfter"] = published_after

    search_response = youtube.search().list(**search_params).execute()
    video_ids = [item["id"]["videoId"] for item in search_response["items"]]

    if not video_ids:
        return [], "⚪ 데이터 없음"

    stats_response = youtube.videos().list(
        part="statistics,snippet",
        id=",".join(video_ids)
    ).execute()

    videos = []
    for item in stats_response["items"]:
        stats = item["statistics"]
        videos.append({
            "제목": item["snippet"]["title"],
            "채널": item["snippet"]["channelTitle"],
            "조회수": int(stats.get("viewCount", 0)),
            "좋아요": int(stats.get("likeCount", 0)),
        })

    videos.sort(key=lambda x: x["조회수"], reverse=True)

    max_views = videos[0]["조회수"] if videos else 0
    if max_views >= 1_000_000:
        ocean = "🔴 레드오션 (100만+ — 강력한 차별화 각도 필수)"
    elif max_views >= 100_000:
        ocean = "🟣 퍼플오션 (10만~100만 — 차별화 각도로 진입 가능)"
    elif max_views >= 10_000:
        ocean = "🟡 경쟁 있음 (1만~10만 — 차별화 확인 후 진행)"
    else:
        ocean = "🟢 블루오션 (1만 미만 — 여지 있음)"

    return videos, ocean


def _timeframe_to_iso(timeframe):
    """Google Trends timeframe 문자열 → YouTube publishedAfter ISO 변환"""
    now = datetime.utcnow()
    mapping = {
        "now 1-H": timedelta(hours=1),
        "now 4-H": timedelta(hours=4),
        "now 1-d": timedelta(days=1),
        "now 7-d": timedelta(days=7),
        "today 1-m": timedelta(days=30),
        "today 3-m": timedelta(days=90),
        "today 12-m": timedelta(days=365),
    }
    delta = mapping.get(timeframe)
    if delta:
        return (now - delta).strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


# ── 3. 네이버 API ──────────────────────────────────────
def search_naver(keyword, timeframe=TIMEFRAME):
    """한국어 뉴스 + 블로그 반응 (30~50대 타겟 맥락)"""
    print(f"\n[네이버] '{keyword}' 뉴스/블로그 수집 중... (기간: {timeframe})")
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }

    results = {}
    for search_type in ["news", "blog"]:
        url = f"https://openapi.naver.com/v1/search/{search_type}"
        params = {"query": keyword, "display": 5, "sort": "date"}
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            results[search_type] = [
                item["title"].replace("<b>", "").replace("</b>", "")
                for item in items
            ]

    return results


# ── 4. 핵심 대상 추출 + 가중치 채점 ───────────────────
def extract_candidates(keyword, youtube_results, trends):
    """
    키워드에서 핵심 대상 후보 3~5개 추출 후 가중치 채점
    가중치 공식: (한국 관련도×3) + (일상 연결성×2) + (3유형 적합도 최고값×2) + (보편 궁금증×1) + (30~50대 공감도×2)
    Claude가 직접 판단 — 실행 시 콘솔에서 입력받음
    """
    print(f"\n[핵심 대상 추출] '{keyword}' → 후보 입력")
    print("  사건이 아닌 '핵심 대상'을 추출하세요. (예: '전세 사기' → '전세 제도', '보증 보험')")
    print("  후보를 쉼표로 구분해서 입력 (엔터로 건너뜀):")

    raw = input("  > ").strip()
    if not raw:
        return []

    candidates_raw = [c.strip() for c in raw.split(",") if c.strip()]
    candidates = []

    for cand in candidates_raw:
        print(f"\n  [{cand}] 가중치 채점 (각 항목 1~5점)")
        try:
            kr   = int(input("    한국 관련도       (1~5): "))
            life = int(input("    일상 연결성       (1~5): "))
            rev  = int(input("    3유형 적합도 최고값 (1~5): "))
            univ = int(input("    보편 궁금증       (1~5): "))
            t30  = int(input("    30~50대 공감도    (1~5): "))
            paradox_q = input("    핵심 질문 한 문장 (서사 유형에 맞는 형태): ").strip()
        except ValueError:
            print("    숫자 입력 오류 — 건너뜀")
            continue

        score = (kr * 3) + (life * 2) + (rev * 2) + (univ * 1) + (t30 * 2)
        candidates.append({
            "대상": cand,
            "핵심 질문": paradox_q,
            "한국 관련도": kr,
            "일상 연결성": life,
            "3유형 적합도": rev,
            "보편 궁금증": univ,
            "30~50대 공감도": t30,
            "가중치 점수": score,
        })

    candidates.sort(key=lambda x: x["가중치 점수"], reverse=True)
    return candidates


# ── 5. 보고서 출력 ─────────────────────────────────────
def print_report(keywords, trends, related, youtube_results, naver_results, all_candidates, timeframe):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print("\n" + "="*60)
    print(f"  키워드 발굴 보고서  |  {now}  |  기간: {timeframe}  |  타겟: {TARGET_AUDIENCE}")
    print("="*60)

    print("\n【 Google Trends — 검색량 비교 】")
    for kw, data in trends.items():
        bar = "▮" * (data["평균"] // 10)
        print(f"  {kw:15} 평균:{data['평균']:3}  {data['추세']}  {bar}")

    if related:
        print(f"\n  [{keywords[0]}] 연관 키워드: {', '.join(related)}")

    print("\n【 YouTube 경쟁 현황 】")
    for kw, (videos, ocean) in youtube_results.items():
        print(f"\n  [{kw}] {ocean}")
        for v in videos[:3]:
            views = f"{v['조회수']:,}"
            print(f"    · {v['제목'][:35]:35}  {views:>10}회  ({v['채널']})")

    print("\n【 네이버 최신 뉴스/블로그 】")
    for kw, naver in naver_results.items():
        print(f"\n  [{kw}]")
        news = naver.get("news", [])
        blogs = naver.get("blog", [])
        if news:
            print(f"  뉴스: {' / '.join(news[:2])}")
        if blogs:
            print(f"  블로그: {' / '.join(blogs[:2])}")

    if all_candidates:
        print("\n【 핵심 대상 후보 — 가중치 순위 】")
        print(f"  가중치 공식: 한국 관련도×3 + 일상 연결성×2 + 3유형 적합도 최고값×2 + 보편 궁금증×1 + 30~50대 공감도×2")
        print(f"  {'순위'} {'대상':15} {'점수':>4}  {'핵심 질문'}")
        print("  " + "-"*70)
        medals = ["🥇", "🥈", "🥉"]
        for i, c in enumerate(all_candidates, 1):
            medal = medals[i-1] if i <= 3 else f" {i}."
            print(f"  {medal} {c['대상']:15} {c['가중치 점수']:>4}점  {c['핵심 질문']}")
        print()
        top = all_candidates[0]
        print(f"  → 추천 주제: [{top['대상']}]  (점수 {top['가중치 점수']}점)")

    print("\n" + "="*60)
    print("  → 다음 단계: P1 퀵서치 + 제목/썸네일 (지침/P1_퀵서치_제목썸네일.md)")
    print("="*60 + "\n")


# ── 실행 ───────────────────────────────────────────────
if __name__ == "__main__":
    # 기간 설정 (기본: 최근 7일)
    # 변경 예시: "today 1-m" / "today 3-m" / "today 12-m"
    timeframe = TIMEFRAME

    # 분석할 키워드 입력 (최대 5개 권장)
    KEYWORDS = [
        "전세 사기",
        "부동산",
        "금리",
    ]

    trends, related = search_trends(KEYWORDS, timeframe)

    youtube_results = {}
    naver_results = {}
    for kw in KEYWORDS:
        youtube_results[kw] = search_youtube(kw, timeframe)
        naver_results[kw] = search_naver(kw, timeframe)

    all_candidates = []
    for kw in KEYWORDS:
        candidates = extract_candidates(kw, youtube_results, trends)
        all_candidates.extend(candidates)
    all_candidates.sort(key=lambda x: x["가중치 점수"], reverse=True)

    print_report(KEYWORDS, trends, related, youtube_results, naver_results, all_candidates, timeframe)
