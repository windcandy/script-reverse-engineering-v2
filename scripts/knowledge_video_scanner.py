"""
knowledge_video_scanner.py — 신규/소형 채널 떡상 지식 영상 발굴 스크립트

전략:
  대형 채널이 아닌 신규/소형 채널의 떡상 영상이 가장 좋은 주제 신호다.
  대형 채널은 충성 구독자 + 알고리즘 가산점으로 조회수가 잘 나오지만,
  소형 채널은 그 두 가지가 약하므로 조회수가 많이 나왔다는 것은
  순수하게 주제 자체가 알고리즘을 뚫었다는 직접 증거다.

5경로 병행 검색:
  Path 1: YouTube 카테고리 광역 스캔
  Path 2: 키워드 폭격 검색
  Path 3: 시드 채널 댓글 채널 마이닝
  Path 4: 외부 분석 사이트 (베스트 에포트)
  Path 5: 본 채널 데이터 (추후 단계 — 본 채널 5편 누적 후)

실행:
  python knowledge_video_scanner.py                  # 전체 5경로
  python knowledge_video_scanner.py --path 1         # 특정 경로만
  python knowledge_video_scanner.py --dry-run        # API 호출 없이 흐름만 점검
  python knowledge_video_scanner.py --report-only    # 최신 결과 보고서만 다시 생성
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ── 경로 설정 ──────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
API_DIR = os.path.join(PROJECT_ROOT, "API")
SEED_POOL_PATH = os.path.join(PROJECT_ROOT, "지식채널_시드풀.md")
REPORTS_DIR = os.path.join(PROJECT_ROOT, "대본", "00_떡상 썸네일")
THUMBNAILS_DIR = os.path.join(REPORTS_DIR, "thumbnails")
CACHE_PATH = os.path.join(BASE_DIR, ".scanner_cache.json")

with open(os.path.join(API_DIR, "youtube_api_key.json")) as f:
    YOUTUBE_API_KEY = json.load(f)["api_key"]


# ── Config: 떡상 신호 기준 ─────────────────────────────
SUBSCRIBER_MIN = 10_000        # 신규 채널 하한 (1만)
SUBSCRIBER_MAX = 300_000       # 소형 채널 상한 (30만)
RATIO_THRESHOLD = 5.0          # 비율(조회수/구독자) 5배 이상
RELATIVE_THRESHOLD = 5.0       # 채널 평균 대비 5배 이상
ABSOLUTE_VIEW_MIN = 50_000     # 절대 조회수 5만 이상
DURATION_MIN_SEC = 240         # 영상 길이 4분 이상
PUBLISHED_DAYS = 90            # 최근 90일

# 한국 지식 영상 카테고리
CATEGORIES = {
    "27": "교육",
    "28": "과학기술",
    "25": "뉴스정치",
    "22": "인물블로그",
}

# 제외 필터 — 본 채널은 지식 집중 채널이므로 뉴스·정치·연예 제외
EXCLUDE_CHANNEL_KEYWORDS = [
    "MBC", "KBS", "SBS", "JTBC", "TV조선", "채널A", "YTN", "MBN",
    "연합뉴스", "뉴시스", "노컷뉴스", "뉴스TV", "NEWS", "News",
    "방송국", "뉴스데스크", "방송",
    "정치 돌직구", "정치를", "민주네집",
]
EXCLUDE_TITLE_KEYWORDS = [
    "윤석열", "이재명", "김건희", "한동훈", "민주당", "국민의힘",
    "검찰", "대통령실",
    "먹방", "예능", "아이돌",
]

# 키워드 폭격 풀 (지식 영상 패턴)
KEYWORDS = {
    "경제": ["왜 망했나", "진짜 이유", "충격", "숨겨진", "실제로 벌어진"],
    "역사": ["사실은", "미스터리", "최후", "비밀", "진실"],
    "국제": ["진짜 노린", "왜 일어났나", "숨은 이유", "전쟁의 진실"],
    "사회": ["이상한", "왜 한국만", "이해 안 되는"],
    "과학": ["원리", "왜 그럴까", "충격 사실"],
    "기술": ["왜 안 되나", "진짜 차이"],
    "문화": ["왜 우리만", "유래"],
}


# ── 캐시 (중복 API 호출 방지) ─────────────────────────
def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            return json.load(f)
    return {"channels": {}, "videos": {}, "last_run": None}


def save_cache(cache):
    cache["last_run"] = datetime.now().isoformat()
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ── YouTube 클라이언트 ────────────────────────────────
def get_youtube():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def published_after_iso(days=PUBLISHED_DAYS):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def parse_duration_sec(iso8601):
    """ISO8601 'PT12M34S' → 초"""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso8601 or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def _days_ago(iso_published):
    """ISO8601 published_at → 오늘 기준 경과 일수"""
    try:
        dt = datetime.fromisoformat(iso_published.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return -1


_FILENAME_FORBIDDEN = re.compile(r'[\\/:*?"<>|\n\r\t]')


def sanitize_for_filename(text, max_len=50):
    """파일명에 안전한 문자열로 변환 (특수문자 제거 + 공백→_ + 길이 제한)"""
    if not text:
        return ""
    cleaned = _FILENAME_FORBIDDEN.sub("", text)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("_")
    return cleaned[:max_len]


def thumbnail_filename(video_id, title):
    """제목 + 영상 ID 결합 파일명 (옵션 3)"""
    safe = sanitize_for_filename(title)
    return f"{safe}_{video_id}.jpg" if safe else f"{video_id}.jpg"


def download_thumbnail(video_id, title=""):
    """YouTube 썸네일 다운로드 (이미 있으면 스킵). 파일명: 제목_영상ID.jpg"""
    import requests

    os.makedirs(THUMBNAILS_DIR, exist_ok=True)
    fname = thumbnail_filename(video_id, title)
    target = os.path.join(THUMBNAILS_DIR, fname)
    if os.path.exists(target):
        return target

    legacy_target = os.path.join(THUMBNAILS_DIR, f"{video_id}.jpg")
    if os.path.exists(legacy_target):
        os.rename(legacy_target, target)
        return target

    candidates = [
        f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in candidates:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200 and len(r.content) > 1000:
                with open(target, "wb") as f:
                    f.write(r.content)
                return target
        except Exception:
            continue
    return None


def ocr_thumbnail_text(image_path):
    """썸네일 이미지에서 텍스트 OCR 추출 (macOS 네이티브 Vision)"""
    if not image_path or not os.path.exists(image_path):
        return ""
    try:
        from ocrmac import ocrmac
        recognized = ocrmac.OCR(
            image_path, language_preference=["ko-KR", "en-US"]
        ).recognize()
        # 신뢰도 0.2 이상만, 위→아래 순으로 결합
        items = [
            (box[1], text.strip())
            for text, conf, box in recognized
            if conf >= 0.2 and text.strip()
        ]
        items.sort(key=lambda x: -x[0])
        return " / ".join(t for _, t in items)
    except Exception as e:
        print(f"  ⚠ OCR 실패 ({os.path.basename(image_path)}): {e}")
        return ""


# ── 채널 통계 일괄 조회 (캐시 활용) ───────────────────
def fetch_channels(youtube, channel_ids, cache):
    """채널 ID 리스트 → 채널 정보 dict (캐시 우선)"""
    result = {}
    missing = []
    for cid in channel_ids:
        if cid in cache["channels"]:
            result[cid] = cache["channels"][cid]
        else:
            missing.append(cid)

    for i in range(0, len(missing), 50):
        batch = missing[i : i + 50]
        try:
            resp = (
                youtube.channels()
                .list(part="snippet,statistics", id=",".join(batch))
                .execute()
            )
        except HttpError as e:
            print(f"  ⚠ channels.list 실패: {e}")
            continue
        for item in resp.get("items", []):
            cid = item["id"]
            data = {
                "channel_id": cid,
                "title": item["snippet"]["title"],
                "subscribers": int(item["statistics"].get("subscriberCount", 0)),
                "video_count": int(item["statistics"].get("videoCount", 0)),
                "view_count": int(item["statistics"].get("viewCount", 0)),
                "published_at": item["snippet"].get("publishedAt", ""),
            }
            data["avg_views"] = (
                data["view_count"] // data["video_count"]
                if data["video_count"]
                else 0
            )
            cache["channels"][cid] = data
            result[cid] = data
    return result


def fetch_videos(youtube, video_ids, cache):
    """영상 ID 리스트 → 영상 정보 dict (캐시 우선)"""
    result = {}
    missing = []
    for vid in video_ids:
        if vid in cache["videos"]:
            result[vid] = cache["videos"][vid]
        else:
            missing.append(vid)

    for i in range(0, len(missing), 50):
        batch = missing[i : i + 50]
        try:
            resp = (
                youtube.videos()
                .list(
                    part="snippet,statistics,contentDetails",
                    id=",".join(batch),
                )
                .execute()
            )
        except HttpError as e:
            print(f"  ⚠ videos.list 실패: {e}")
            continue
        for item in resp.get("items", []):
            vid = item["id"]
            stats = item["statistics"]
            data = {
                "video_id": vid,
                "title": item["snippet"]["title"],
                "channel_id": item["snippet"]["channelId"],
                "channel_title": item["snippet"]["channelTitle"],
                "published_at": item["snippet"]["publishedAt"],
                "category_id": item["snippet"].get("categoryId", ""),
                "duration_sec": parse_duration_sec(
                    item["contentDetails"].get("duration", "PT0S")
                ),
                "view_count": int(stats.get("viewCount", 0)),
                "like_count": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
            }
            cache["videos"][vid] = data
            result[vid] = data
    return result


# ── Path 1: 카테고리 광역 스캔 (mostPopular) ──────────
def scan_by_category(youtube, cache, max_per_category=50):
    """videos.list chart=mostPopular로 한국 카테고리별 인기 영상 직접 조회.
    search.list의 videoCategoryId 조합 제약을 우회한다."""
    print("\n[Path 1] YouTube 인기 영상 광역 스캔 (mostPopular)")
    candidates = []
    for cid, name in CATEGORIES.items():
        try:
            resp = (
                youtube.videos()
                .list(
                    part="id",
                    chart="mostPopular",
                    regionCode="KR",
                    videoCategoryId=cid,
                    maxResults=max_per_category,
                )
                .execute()
            )
        except HttpError as e:
            print(f"  ⚠ chart=mostPopular ({name}) 실패: {e}")
            continue
        items = resp.get("items", [])
        for item in items:
            candidates.append(item["id"])
        print(f"  · 카테고리 {cid}({name}): {len(items)}개")
    print(f"  → 후보 영상 수집: {len(candidates)}개")
    return list(set(candidates))


# ── Path 2: 키워드 폭격 검색 ──────────────────────────
def scan_by_keywords(youtube, cache, max_per_keyword=50):
    print("\n[Path 2] 키워드 폭격 검색")
    candidates = []
    for field, kws in KEYWORDS.items():
        for kw in kws:
            try:
                resp = (
                    youtube.search()
                    .list(
                        q=kw,
                        part="snippet",
                        type="video",
                        regionCode="KR",
                        relevanceLanguage="ko",
                        order="viewCount",
                        publishedAfter=published_after_iso(),
                        videoDuration="medium",
                        maxResults=max_per_keyword,
                    )
                    .execute()
                )
            except HttpError as e:
                print(f"  ⚠ '{kw}' 검색 실패: {e}")
                continue
            for item in resp.get("items", []):
                candidates.append(item["id"]["videoId"])
        print(f"  · {field} 분야 {len(kws)}개 키워드 완료")
    candidates = list(set(candidates))
    print(f"  → 후보 영상 수집: {len(candidates)}개 (중복 제거)")
    return candidates


# ── Path 3: 시드 채널 댓글 마이닝 ─────────────────────
CHANNEL_MENTION_RE = re.compile(r"@([A-Za-z0-9_가-힣]{2,30})")


def mine_comments(youtube, cache, seed_channel_ids, videos_per_channel=10, comments_per_video=100):
    print("\n[Path 3] 시드 채널 댓글 채널 마이닝")
    if not seed_channel_ids:
        print("  · 시드 채널 없음 → 스킵")
        return []

    mentioned_channels = Counter()
    mentioned_handles = Counter()

    for cid in seed_channel_ids:
        try:
            ch_resp = (
                youtube.channels()
                .list(part="contentDetails", id=cid)
                .execute()
            )
        except HttpError as e:
            print(f"  ⚠ 채널 {cid} 조회 실패: {e}")
            continue
        items = ch_resp.get("items", [])
        if not items:
            continue
        uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        try:
            pl_resp = (
                youtube.playlistItems()
                .list(part="contentDetails", playlistId=uploads_id, maxResults=videos_per_channel)
                .execute()
            )
        except HttpError as e:
            print(f"  ⚠ 재생목록 {uploads_id} 조회 실패: {e}")
            continue

        video_ids = [
            it["contentDetails"]["videoId"] for it in pl_resp.get("items", [])
        ]

        for vid in video_ids:
            try:
                cm_resp = (
                    youtube.commentThreads()
                    .list(
                        part="snippet",
                        videoId=vid,
                        maxResults=comments_per_video,
                        order="relevance",
                        textFormat="plainText",
                    )
                    .execute()
                )
            except HttpError as e:
                continue
            for it in cm_resp.get("items", []):
                text = it["snippet"]["topLevelComment"]["snippet"].get("textDisplay", "")
                for handle in CHANNEL_MENTION_RE.findall(text):
                    mentioned_handles[handle] += 1

    top_handles = [h for h, c in mentioned_handles.most_common(50) if c >= 3]
    print(f"  → 빈도 3회 이상 언급 핸들: {len(top_handles)}개")

    discovered_channel_ids = []
    for handle in top_handles:
        try:
            resp = (
                youtube.search()
                .list(q="@" + handle, type="channel", part="snippet", maxResults=1)
                .execute()
            )
        except HttpError:
            continue
        items = resp.get("items", [])
        if items:
            discovered_channel_ids.append(items[0]["snippet"]["channelId"])
    print(f"  → 채널 ID 변환 성공: {len(discovered_channel_ids)}개")
    return list(set(discovered_channel_ids))


# ── Path 4: 외부 사이트 (베스트 에포트) ───────────────
def fetch_external_rankings():
    """
    Social Blade·Playboard 등 외부 사이트 자동 수집은
    사이트별 robots.txt·ToS 준수 + JS 렌더링 이슈로 실패율이 높다.
    본 함수는 베스트 에포트로 시도하고, 실패 시 빈 리스트 반환.
    수동 큐레이션 보조용으로 사용 권장.
    """
    print("\n[Path 4] 외부 분석 사이트 (베스트 에포트)")
    print("  · 자동 수집 미구현 (사이트 ToS·JS 렌더링 이슈)")
    print("  · 추후 수동 큐레이션 결과를 시드 풀에 직접 추가하는 방식 권장")
    return []


# ── 떡상 신호 필터링 ──────────────────────────────────
def filter_viral_videos(youtube, video_ids, cache):
    """후보 영상 ID 리스트 → 떡상 신호 충족 영상만 추출"""
    print(f"\n[Filter] 떡상 신호 검증 시작 (후보 {len(video_ids)}개)")
    if not video_ids:
        return []

    videos = fetch_videos(youtube, video_ids, cache)
    channel_ids = list({v["channel_id"] for v in videos.values()})
    channels = fetch_channels(youtube, channel_ids, cache)

    viral = []
    excluded_count = 0
    for v in videos.values():
        ch = channels.get(v["channel_id"])
        if not ch:
            continue

        if v["duration_sec"] < DURATION_MIN_SEC:
            continue
        if v["view_count"] < ABSOLUTE_VIEW_MIN:
            continue
        if not (SUBSCRIBER_MIN <= ch["subscribers"] <= SUBSCRIBER_MAX):
            continue

        # 제외 필터 (뉴스·정치·연예)
        ch_title = ch.get("title", "")
        v_title = v.get("title", "")
        if any(kw in ch_title for kw in EXCLUDE_CHANNEL_KEYWORDS):
            excluded_count += 1
            continue
        if any(kw in v_title for kw in EXCLUDE_TITLE_KEYWORDS):
            excluded_count += 1
            continue

        ratio = v["view_count"] / max(ch["subscribers"], 1)
        relative = v["view_count"] / max(ch["avg_views"], 1)

        if ratio < RATIO_THRESHOLD and relative < RELATIVE_THRESHOLD:
            continue

        engagement = (v["like_count"] + v["comment_count"]) / max(v["view_count"], 1)

        ch_age_days = 0
        try:
            ch_published = datetime.fromisoformat(
                ch["published_at"].replace("Z", "+00:00")
            )
            ch_age_days = (datetime.now(timezone.utc) - ch_published).days
        except Exception:
            pass

        new_channel_bonus = 1 if ch_age_days <= 730 else 0

        score = (
            ratio * 2 + relative * 2 + engagement * 100 * 1 + new_channel_bonus * 1
        )

        video_age_days = max(_days_ago(v["published_at"]), 1)
        avg_daily_views = v["view_count"] / video_age_days

        if video_age_days <= 30:
            v_type = "🔥 신규 떡상"
        elif video_age_days <= 60:
            v_type = "📈 중기 안정"
        elif avg_daily_views >= 5000:
            v_type = "🌱 후행 에버그린"
        else:
            v_type = "📊 일반"

        viral.append(
            {
                **v,
                "channel": ch,
                "ratio": round(ratio, 2),
                "relative": round(relative, 2),
                "engagement": round(engagement, 4),
                "channel_age_days": ch_age_days,
                "video_age_days": video_age_days,
                "avg_daily_views": int(avg_daily_views),
                "type": v_type,
                "score": round(score, 2),
            }
        )

    viral.sort(key=lambda x: x["score"], reverse=True)
    print(f"  → 떡상 신호 충족: {len(viral)}개 (제외 필터 적용 {excluded_count}개)")
    return viral


# ── 시드 풀 입출력 ────────────────────────────────────
def load_seed_pool():
    if not os.path.exists(SEED_POOL_PATH):
        return {"active": {}, "candidates": {}}

    pool = {"active": {}, "candidates": {}}
    section = None
    with open(SEED_POOL_PATH) as f:
        for line in f:
            line = line.strip()
            if line.startswith("## 등록 채널 목록"):
                section = "active"
            elif line.startswith("## 발견 후보"):
                section = "candidates"
            elif line.startswith("|") and section and "채널 ID" not in line and "---" not in line:
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) >= 2 and cells[1].startswith("UC"):
                    pool[section][cells[1]] = cells
    return pool


def save_seed_pool(active_channels, candidate_channels):
    """시드 풀 .md 파일 갱신"""
    lines = [
        "# 지식 채널 시드 풀",
        "",
        "> 자동 갱신 — `scripts/knowledge_video_scanner.py`가 관리합니다.",
        "> 수동 편집 가능 — 제외할 채널은 상태를 `excluded`로 변경하세요.",
        "",
        f"마지막 갱신: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
        "## 등록 채널 목록",
        "",
        "| 채널명 | 채널 ID | 분야 | 구독자 | 평균 조회수 | 발견 경로 | 상태 |",
        "|---|---|---|---|---|---|---|",
    ]
    for ch in sorted(active_channels, key=lambda x: -x.get("subscribers", 0)):
        lines.append(
            f"| {ch.get('title','')} | {ch.get('channel_id','')} | {ch.get('field','-')} "
            f"| {ch.get('subscribers',0):,} | {ch.get('avg_views',0):,} "
            f"| {ch.get('source','-')} | {ch.get('status','active')} |"
        )

    lines += [
        "",
        "---",
        "",
        "## 발견 후보 (유저 검수 대기)",
        "",
        "| 채널명 | 채널 ID | 발견 경로 | 떡상 영상 비율 | 검수 |",
        "|---|---|---|---|---|",
    ]
    for ch in sorted(candidate_channels, key=lambda x: -x.get("max_ratio", 0)):
        lines.append(
            f"| {ch.get('title','')} | {ch.get('channel_id','')} "
            f"| {ch.get('source','-')} | {ch.get('max_ratio',0)} | pending |"
        )

    with open(SEED_POOL_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  → 시드 풀 갱신: {SEED_POOL_PATH}")


# ── 보고서 생성 ───────────────────────────────────────
def generate_report(viral_videos, path_results):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d_%H%M")
    report_path = os.path.join(REPORTS_DIR, f"[떡상 썸네일]_{today}.md")

    print(f"\n[Thumbnails] 상위 {min(len(viral_videos), 50)}개 썸네일 다운로드 + OCR 중...")
    for v in viral_videos[:50]:
        path = download_thumbnail(v["video_id"], v.get("title", ""))
        v["thumbnail_path"] = path
        v["thumbnail_text"] = ocr_thumbnail_text(path) if path else ""

    lines = [
        f"# 떡상 영상 스캔 보고서 — {today}",
        "",
        "> 신규/소형 채널(구독자 1만~30만) 떡상 영상 발굴 결과",
        f"> 임계값: 비율 ≥ {RATIO_THRESHOLD}배 / 채널 평균 대비 ≥ {RELATIVE_THRESHOLD}배 / 조회수 ≥ {ABSOLUTE_VIEW_MIN:,}",
        "",
        "## 경로별 수집 현황",
        "",
        "| 경로 | 후보 영상 수 |",
        "|---|---|",
    ]
    for path, count in path_results.items():
        lines.append(f"| {path} | {count} |")

    type_order = ["🔥 신규 떡상", "📈 중기 안정", "🌱 후행 에버그린", "📊 일반"]
    grouped = {t: [] for t in type_order}
    for v in viral_videos[:50]:
        grouped.get(v.get("type", "📊 일반"), grouped["📊 일반"]).append(v)

    lines += [
        "",
        f"## 떡상 영상 (총 {len(viral_videos)}개, 유형별 분류 + 점수순)",
        "",
        "> ※ 우상향 추세 검증은 VidIQ 확장의 'Views over time' 그래프로 수동 확인 권장 (상위 1·2위 후보만)",
        "",
    ]

    type_desc = {
        "🔥 신규 떡상": "업로드 ≤30일 — 알고리즘이 지금 밀어주는 중, 시의성 라이프사이클 짧음",
        "📈 중기 안정": "업로드 31~60일 — 안정 트렌드",
        "🌱 후행 에버그린": "업로드 >60일 + 일평균 조회수 5천 이상 — 장기 검색·추천 노출 가능성",
        "📊 일반": "기타",
    }

    counter = 0
    for t in type_order:
        bucket = grouped[t]
        if not bucket:
            continue
        lines += [
            f"### {t} ({len(bucket)}개)",
            f"> {type_desc[t]}",
            "",
        ]
        for v in bucket:
            counter += 1
            ch = v["channel"]
            url = f"https://youtu.be/{v['video_id']}"
            thumb_fname = thumbnail_filename(v["video_id"], v.get("title", ""))
            thumb_path = f"thumbnails/{thumb_fname}"
            ocr_text = v.get("thumbnail_text") or "(OCR 결과 없음)"
            lines += [
                f"#### {counter}. {v['title']}",
                "",
                f"![](thumbnails/{thumb_fname})",
                "",
                f"- 제목: {v['title']}",
                f"- 썸네일 문구: {ocr_text}",
                f"- 링크: {url}",
                f"- 업로드: {v['published_at'][:10]} ({v['video_age_days']}일 전) / 일평균 조회수 {v['avg_daily_views']:,} / 길이: {v['duration_sec']//60}분 {v['duration_sec']%60}초",
                f"- 채널: **{ch['title']}** (구독자 {ch['subscribers']:,} / 조회수 {v['view_count']:,} / 비율 점수 {v['ratio']}배 / 상대 점수 {v['relative']}배)",
                f"- 참여도: {v['engagement']} / 채널 개설: {v['channel_age_days']}일 전 / 점수: **{v['score']}**",
                "",
            ]

    top_for_chrome = viral_videos[:10]
    if top_for_chrome:
        lines += [
            "",
            "---",
            "",
            "## 🤖 Claude in Chrome 우상향 검증 프롬프트",
            "",
            "> 아래 블록을 복사하여 Claude in Chrome 세션에 붙여넣으면 VidIQ 'Views over time' 그래프를 자동 검증합니다.",
            "> 사전 조건: 브라우저에 VidIQ 무료 플랜 설치 + 로그인.",
            "",
            "```",
            "다음 영상들의 VidIQ 'Views over time' 그래프(28일 또는 All)를 확인하고",
            "각 영상의 추세를 보고해주세요.",
            "",
        ]
        for i, v in enumerate(top_for_chrome, 1):
            lines.append(
                f"{i}. https://youtu.be/{v['video_id']} ({v['title'][:30]}... / {v['video_age_days']}일 전)"
            )
        lines += [
            "",
            "각 영상마다:",
            "- 추세: 우상향(상승 지속) / 평탄 / 하락",
            "- 우상향 강도: 강 / 중 / 약",
            "- 최근 7일 일평균 조회수 (대략값)",
            "보고해주세요.",
            "```",
            "",
        ]

    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    print(f"\n📄 보고서 저장: {report_path}")
    return report_path


# ── 메인 흐름 ─────────────────────────────────────────
def run_full_scan(paths=(1, 2, 3, 4), dry_run=False):
    if dry_run:
        print("[DRY-RUN] API 호출 없이 흐름만 점검합니다.")
        return

    youtube = get_youtube()
    cache = load_cache()

    all_video_ids = set()
    path_results = {}

    if 1 in paths:
        ids = scan_by_category(youtube, cache)
        all_video_ids.update(ids)
        path_results["Path 1 (카테고리)"] = len(ids)

    if 2 in paths:
        ids = scan_by_keywords(youtube, cache)
        all_video_ids.update(ids)
        path_results["Path 2 (키워드)"] = len(ids)

    if 3 in paths:
        seed_pool = load_seed_pool()
        seed_ids = list(seed_pool["active"].keys())
        new_channels = mine_comments(youtube, cache, seed_ids)
        for cid in new_channels:
            seed_pool["candidates"].setdefault(cid, [None, cid])
        path_results["Path 3 (댓글마이닝)"] = len(new_channels)

    if 4 in paths:
        fetch_external_rankings()
        path_results["Path 4 (외부)"] = 0

    viral = filter_viral_videos(youtube, list(all_video_ids), cache)

    new_channel_data = []
    seen_channel_ids = set()
    for v in viral:
        ch = v["channel"]
        if ch["channel_id"] in seen_channel_ids:
            continue
        seen_channel_ids.add(ch["channel_id"])
        new_channel_data.append(
            {
                **ch,
                "field": "-",
                "source": "auto_scan",
                "status": "candidate",
                "max_ratio": v["ratio"],
            }
        )

    save_seed_pool([], new_channel_data)
    save_cache(cache)
    generate_report(viral, path_results)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=int, choices=[1, 2, 3, 4], help="특정 경로만 실행")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 흐름만 점검")
    parser.add_argument("--report-only", action="store_true", help="캐시 기반 보고서만 재생성")
    args = parser.parse_args()

    if args.report_only:
        print("최신 캐시 기반 보고서 재생성 — 미구현 (다음 단계)")
        return

    paths = (args.path,) if args.path else (1, 2, 3, 4)
    run_full_scan(paths=paths, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
