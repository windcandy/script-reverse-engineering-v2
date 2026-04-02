import json
import os
import sys
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
API_DIR = os.path.join(BASE_DIR, "API")
MEDIA_DIR = os.path.join(BASE_DIR, "01_영상, 썸네일")
TOKEN_FILE = os.path.join(API_DIR, "youtube_token.json")
CLIENT_SECRET_FILE = os.path.join(API_DIR, "client_secret_250672933888-dpgigh74j00grc8anikl5b7ut9scvj7i.apps.googleusercontent.com.json")


def get_credentials():
    with open(TOKEN_FILE) as f:
        token_data = json.load(f)

    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data["refresh_token"],
        token_uri=token_data["token_uri"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=token_data["scopes"],
    )

    # 토큰 만료 시 자동 갱신
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_data["token"] = creds.token
        with open(TOKEN_FILE, "w") as f:
            json.dump(token_data, f, indent=2)
        print("토큰 갱신 완료")

    return creds


def upload_video(video_path, title, description, tags, category_id="22", privacy="private", publish_at=None):
    """
    video_path : 영상 파일 경로
    title      : 영상 제목
    description: 영상 설명
    tags       : 태그 리스트 (예: ["경제", "전세", "부동산"])
    category_id: 22 = 사람 및 블로그 / 27 = 교육 / 25 = 뉴스
    privacy    : "private" | "unlisted" | "public"
    publish_at : 예약 공개 시각 — 문자열로 입력 (예: "2026-04-05 18:00")
                 입력 시 privacy는 자동으로 "private"으로 설정됨
    """
    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    # 예약 업로드 처리
    if publish_at:
        from datetime import datetime
        import pytz
        kst = pytz.timezone("Asia/Seoul")
        dt = datetime.strptime(publish_at, "%Y-%m-%d %H:%M")
        dt_kst = kst.localize(dt)
        publish_at_rfc = dt_kst.isoformat()
        privacy = "private"  # 예약 업로드는 반드시 private
        print(f"예약 공개 시각: {publish_at} KST")
    else:
        publish_at_rfc = None

    status_body = {"privacyStatus": privacy}
    if publish_at_rfc:
        status_body["publishAt"] = publish_at_rfc

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
        },
        "status": status_body,
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)

    print(f"업로드 시작: {os.path.basename(video_path)}")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"진행률: {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"업로드 완료: https://youtu.be/{video_id}")
    return video_id


def set_thumbnail(video_id, thumbnail_path):
    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
    print(f"썸네일 설정 완료: {os.path.basename(thumbnail_path)}")


def list_media_files():
    """01_영상, 썸네일 폴더의 파일 목록 출력"""
    files = os.listdir(MEDIA_DIR)
    videos = [f for f in files if f.endswith((".mp4", ".mov", ".avi"))]
    thumbnails = [f for f in files if f.endswith((".jpg", ".jpeg", ".png"))]
    print("\n[영상 파일]")
    for v in videos:
        print(f"  {v}")
    print("\n[썸네일 파일]")
    for t in thumbnails:
        print(f"  {t}")
    return videos, thumbnails


# ── 실행 예시 ──────────────────────────────────────────
if __name__ == "__main__":
    list_media_files()

    # ── 고정 업로드 스케줄 설정 ────────────────────────────
    # 매주 동일한 요일/시간에 공개하려면 아래 두 값만 설정
    WEEKLY_DAY  = "토"    # 공개 요일: 월 화 수 목 금 토 일
    WEEKLY_TIME = "18:00" # 공개 시각 (KST)
    # ────────────────────────────────────────────────────

    # 아래 값을 채워서 실행하세요
    VIDEO_FILE = ""       # 예: "전세제도.mp4"
    THUMBNAIL_FILE = ""   # 예: "전세제도_썸네일.jpg"
    TITLE = ""            # 영상 제목
    DESCRIPTION = ""      # 영상 설명 (SEO 포함)
    TAGS = []             # 예: ["전세", "부동산", "경제"]
    PUBLISH_AT = ""       # 직접 지정 시 입력 (예: "2026-04-10 18:00") — 비워두면 WEEKLY 스케줄 적용
                          # WEEKLY_DAY/WEEKLY_TIME 도 비워두면 비공개 업로드

    if VIDEO_FILE:
        video_path = os.path.join(MEDIA_DIR, VIDEO_FILE)

        # 예약 시각 결정
        if not PUBLISH_AT and WEEKLY_DAY and WEEKLY_TIME:
            from datetime import datetime, timedelta
            import pytz
            day_map = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
            kst = pytz.timezone("Asia/Seoul")
            now = datetime.now(kst)
            target_weekday = day_map[WEEKLY_DAY]
            days_ahead = (target_weekday - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7  # 오늘과 같은 요일이면 다음 주로
            target_date = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
            PUBLISH_AT = f"{target_date} {WEEKLY_TIME}"
            print(f"스케줄 적용: 매주 {WEEKLY_DAY}요일 {WEEKLY_TIME} → {PUBLISH_AT} KST")

        if PUBLISH_AT:
            print(f"예약 공개 업로드 모드: {PUBLISH_AT} KST")
            video_id = upload_video(video_path, TITLE, DESCRIPTION, TAGS, publish_at=PUBLISH_AT)
        else:
            print("비공개 업로드 모드")
            video_id = upload_video(video_path, TITLE, DESCRIPTION, TAGS, privacy="private")

        if THUMBNAIL_FILE:
            thumbnail_path = os.path.join(MEDIA_DIR, THUMBNAIL_FILE)
            set_thumbnail(video_id, thumbnail_path)
