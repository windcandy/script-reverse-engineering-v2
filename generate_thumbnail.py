import json
import os
import time
import requests

# 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
API_DIR = os.path.join(BASE_DIR, "API")
OUTPUT_DIR = os.path.join(BASE_DIR, "01_영상, 썸네일")

with open(os.path.join(API_DIR, "freepik_api_key.json")) as f:
    FREEPIK_API_KEY = json.load(f)["api_key"]

API_URL = "https://api.freepik.com/v1/ai/mystic"
HEADERS = {
    "x-freepik-api-key": FREEPIK_API_KEY,
    "Content-Type": "application/json",
}


def generate_thumbnail(prompt, filename, aspect_ratio="16_9", model="realism", resolution="2k"):
    """
    prompt      : 이미지 설명 (영어 권장)
    filename    : 저장 파일명 (확장자 제외)
    aspect_ratio: widescreen_16_9 (유튜브 썸네일) | square_1_1 | social_story_9_16 (쇼츠)
    model       : realism | zen | flexible | fluid | super_real | editorial_portraits
    resolution  : 1k | 2k | 4k
    """
    print(f"\n[Freepik AI] 이미지 생성 요청 중...")
    print(f"  프롬프트: {prompt}")
    print(f"  비율: {aspect_ratio} | 모델: {model} | 해상도: {resolution}")

    payload = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "model": model,
        "resolution": resolution,
    }

    response = requests.post(API_URL, headers=HEADERS, json=payload)

    if response.status_code != 200:
        print(f"  오류: {response.status_code} — {response.text}")
        return None

    task_id = response.json()["data"]["task_id"]
    print(f"  task_id: {task_id}")

    # 완료까지 폴링
    print("  생성 중", end="", flush=True)
    for _ in range(60):
        time.sleep(3)
        status_resp = requests.get(f"{API_URL}/{task_id}", headers=HEADERS)
        if status_resp.status_code != 200:
            break
        data = status_resp.json()["data"]
        status = data.get("status")
        print(".", end="", flush=True)

        if status == "COMPLETED":
            image_urls = data.get("generated", [])
            if not image_urls:
                print("\n  완료됐지만 이미지 URL 없음")
                return None

            # 이미지 다운로드
            saved_files = []
            for i, url in enumerate(image_urls):
                suffix = f"_{i+1}" if len(image_urls) > 1 else ""
                save_path = os.path.join(OUTPUT_DIR, f"{filename}{suffix}.jpg")
                img_data = requests.get(url).content
                with open(save_path, "wb") as f:
                    f.write(img_data)
                saved_files.append(save_path)
                print(f"\n  저장 완료: {save_path}")

            return saved_files

        elif status == "FAILED":
            print(f"\n  생성 실패: {data}")
            return None

    print("\n  시간 초과 — 나중에 다시 시도하세요")
    return None


# ── 실행 예시 ──────────────────────────────────────────
if __name__ == "__main__":
    # 아래 값을 채워서 실행하세요
    PROMPT   = ""   # 예: "A dramatic scene of a key and an empty house in Korea, cinematic lighting"
    FILENAME = ""   # 예: "전세제도_썸네일"

    # 유튜브 썸네일: aspect_ratio="widescreen_16_9"
    # 쇼츠용:       aspect_ratio="social_story_9_16"
    ASPECT_RATIO = "widescreen_16_9"
    MODEL        = "realism"
    RESOLUTION   = "2k"

    if PROMPT and FILENAME:
        generate_thumbnail(PROMPT, FILENAME, ASPECT_RATIO, MODEL, RESOLUTION)
    else:
        print("PROMPT와 FILENAME을 입력하세요.")
