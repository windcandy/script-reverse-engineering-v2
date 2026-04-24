"""
YouTube OAuth 인증 설정 스크립트
새 구글 계정으로 채널을 연결할 때 실행합니다.
브라우저가 열리면 업로드할 채널의 구글 계정으로 로그인하세요.
"""

import json
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
API_DIR = os.path.join(BASE_DIR, "..", "API")

CLIENT_SECRET_FILE = os.path.join(
    API_DIR,
    "client_secret_562871393369-avevlk1fiss268uuodjkh4ifdv4fedkk.apps.googleusercontent.com.json"
)
TOKEN_FILE = os.path.join(API_DIR, "youtube_token.json")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def main():
    print("=" * 50)
    print("  YouTube 채널 인증 설정")
    print("=" * 50)
    print("\n브라우저가 열립니다.")
    print("업로드할 채널의 구글 계정으로 로그인하세요.\n")

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    # 토큰 저장
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes),
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)
    print(f"\n토큰 저장 완료: {TOKEN_FILE}")

    # 연결된 채널 확인
    yt = build("youtube", "v3", credentials=creds)
    res = yt.channels().list(part="snippet,statistics", mine=True).execute()
    items = res.get("items", [])
    if items:
        ch = items[0]
        name = ch["snippet"]["title"]
        ch_id = ch["id"]
        subs = int(ch["statistics"].get("subscriberCount", 0))
        print(f"\n연결된 채널: {name}")
        print(f"채널 ID    : {ch_id}")
        print(f"구독자 수  : {subs:,}명")
        print("\n인증 완료! youtube_upload.py를 바로 사용할 수 있습니다.")
    else:
        print("\n채널을 찾을 수 없습니다. 계정에 YouTube 채널이 있는지 확인하세요.")


if __name__ == "__main__":
    main()
