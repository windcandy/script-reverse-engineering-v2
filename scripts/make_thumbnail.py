"""
유튜브 썸네일 생성 스크립트

사용법:
    python3 make_thumbnail.py

설정값은 하단 __main__ 블록에서 입력.

썸네일 스펙:
    - 사이즈: 1280×720
    - 폰트: Cafe24 Ohsquare
    - 폰트 사이즈: 134pt
    - 라인 하이트: 143pt
    - 왼쪽 여백: 46px / 아래 여백: 40px
    - 딤 레이어: 딤.png 오버레이
    - 드랍쉐도우: opacity 88%, angle 131°, distance 10, size 40
"""

import os
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

# 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEDIA_DIR = os.path.join(BASE_DIR, "..", "01_영상, 썸네일")
FONT_PATH = os.path.expanduser("~/Library/Fonts/Cafe24Ohsquare.ttf")
DIM_PATH  = os.path.join(MEDIA_DIR, "딤.png")

# 썸네일 스펙
WIDTH, HEIGHT = 1280, 720
FONT_SIZE     = 134
LINE_HEIGHT   = 143
MARGIN_LEFT   = 46
MARGIN_BOTTOM = 40

# 드랍쉐도우 스펙
SHADOW_OPACITY = int(255 * 0.88)   # 88%
SHADOW_ANGLE   = 131               # 포토샵 기준 각도 (빛 방향)
SHADOW_DIST    = 10
SHADOW_BLUR    = 40                # size → blur radius

# 컬러 정의
COLOR_WHITE  = (255, 255, 255)
COLOR_RED    = (255,   9,   9)
COLOR_YELLOW = (252, 255,   0)

COLOR_MAP = {
    "white":  COLOR_WHITE,
    "red":    COLOR_RED,
    "yellow": COLOR_YELLOW,
}


def apply_lighter_color_blend(base_img, blend_img):
    """
    딤.png 블렌드 모드: Lighter Color
    각 픽셀의 휘도를 비교해 더 밝은 쪽을 유지한 뒤, blend_img의 알파값으로 합성.
    """
    base  = np.array(base_img.convert("RGBA"), dtype=np.float32)
    blend = np.array(blend_img.convert("RGBA"), dtype=np.float32)

    blend_alpha = blend[:, :, 3:4] / 255.0  # (H, W, 1)

    # 휘도 계산
    base_lum  = (0.299 * base[:, :, 0]
                + 0.587 * base[:, :, 1]
                + 0.114 * base[:, :, 2])
    blend_lum = (0.299 * blend[:, :, 0]
                + 0.587 * blend[:, :, 1]
                + 0.114 * blend[:, :, 2])

    # 더 밝은 픽셀 선택
    use_blend    = (blend_lum > base_lum)[:, :, np.newaxis]
    lighter_rgb  = np.where(use_blend, blend[:, :, :3], base[:, :, :3])

    # blend_alpha로 opacity 적용
    result_rgb = base[:, :, :3] * (1 - blend_alpha) + lighter_rgb * blend_alpha
    result_rgb = np.clip(result_rgb, 0, 255).astype(np.uint8)

    result_a   = base[:, :, 3:4].astype(np.uint8)
    return Image.fromarray(np.concatenate([result_rgb, result_a], axis=2), "RGBA")


def calc_shadow_offset(angle_deg, distance):
    """포토샵 드랍쉐도우 각도 → 픽셀 오프셋 변환"""
    shadow_angle_deg = angle_deg + 180  # 빛 반대 방향이 그림자 방향
    rad = math.radians(shadow_angle_deg)
    x = int(round(distance * math.cos(rad)))
    y = int(round(-distance * math.sin(rad)))  # 화면 Y축 반전
    return x, y


def make_shadow_layer(text_mask, blur_radius, offset_x, offset_y, opacity, spread=0):
    """텍스트 마스크로 드랍쉐도우 레이어 생성
    spread: 블러 전 그림자 팽창 픽셀 수 (포토샵 spread 근사)
    """
    # spread 적용 — MaxFilter로 마스크 팽창
    expanded_mask = text_mask
    if spread > 0:
        expanded_mask = text_mask.filter(ImageFilter.MaxFilter(size=spread * 2 + 1))

    shadow = Image.new("RGBA", text_mask.size, (0, 0, 0, 0))
    black  = Image.new("RGBA", text_mask.size, (0, 0, 0, opacity))
    shadow.paste(black, mask=expanded_mask)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=blur_radius / 2))
    shifted = Image.new("RGBA", text_mask.size, (0, 0, 0, 0))
    shifted.paste(shadow, (offset_x, offset_y))
    return shifted


def draw_text_layer(lines, canvas_size):
    """
    텍스트 + 드랍쉐도우 레이어 생성

    lines: [
        [("텍스트", "white"), ("텍스트2", "red")],   # 1행
        [("텍스트", "yellow"), ("나머지", "white")],  # 2행
    ]
    반환: RGBA 이미지
    """
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

    total_lines = len(lines)
    total_h = total_lines * FONT_SIZE + (total_lines - 1) * (LINE_HEIGHT - FONT_SIZE)
    start_y = canvas_size[1] - MARGIN_BOTTOM - total_h

    shadow_ox, shadow_oy = calc_shadow_offset(SHADOW_ANGLE, SHADOW_DIST)

    # ── 1) 쉐도우 레이어 ──────────────────────────────
    shadow_layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    for line_idx, segments in enumerate(lines):
        y = start_y + line_idx * LINE_HEIGHT
        line_text = "".join(seg[0] for seg in segments)

        mask = Image.new("L", canvas_size, 0)
        ImageDraw.Draw(mask).text((MARGIN_LEFT, y), line_text, font=font, fill=255)

        shadow = make_shadow_layer(mask, SHADOW_BLUR, shadow_ox, shadow_oy, SHADOW_OPACITY, spread=4)
        shadow_layer = Image.alpha_composite(shadow_layer, shadow)

    # ── 2) 컬러 텍스트 레이어 ─────────────────────────
    text_layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    text_draw  = ImageDraw.Draw(text_layer)
    for line_idx, segments in enumerate(lines):
        y = start_y + line_idx * LINE_HEIGHT
        x = MARGIN_LEFT
        for text, color_name in segments:
            color = COLOR_MAP.get(color_name, COLOR_WHITE)
            text_draw.text((x, y), text, font=font, fill=color + (255,))
            bbox = font.getbbox(text)
            x += bbox[2] - bbox[0]

    # ── 3) 쉐도우 위에 텍스트 합성 ───────────────────
    result = Image.alpha_composite(shadow_layer, text_layer)
    return result


def composite_subject(bg, subject_path, scale=0.7, position="right", bottom_offset=0):
    """
    배경 위에 인물/오브젝트 PNG를 합성한다.

    subject_path : 배경이 제거된 PNG 파일 경로 (투명 배경)
    scale        : 캔버스 높이 대비 인물 크기 비율 (기본 0.7 = 70%)
    position     : "left" | "center" | "right" — 수평 배치
    bottom_offset: 하단에서 올리는 픽셀 (기본 0 = 하단 정렬)

    배경 제거 방법:
      - remove.bg (https://www.remove.bg) — 무료 50회/월
      - Photoshop / 픽슬러 — 수동 제거
      결과를 PNG로 저장 후 subject_path에 지정
    """
    subject = Image.open(subject_path).convert("RGBA")

    # 인물 크기 조정 (캔버스 높이 기준 비율)
    target_h = int(HEIGHT * scale)
    ratio    = target_h / subject.height
    target_w = int(subject.width * ratio)
    subject  = subject.resize((target_w, target_h), Image.LANCZOS)

    # 수평 위치 결정
    if position == "left":
        x = int(WIDTH * 0.05)
    elif position == "center":
        x = (WIDTH - target_w) // 2
    else:  # right
        x = WIDTH - target_w - int(WIDTH * 0.05)

    # 수직 위치 — 하단 정렬 후 offset 만큼 올림
    y = HEIGHT - target_h - bottom_offset

    # 합성
    canvas = bg.copy()
    canvas.paste(subject, (x, y), subject)
    return canvas


def make_thumbnail(bg_path, lines, output_path,
                   subject_path=None, subject_scale=0.7,
                   subject_position="right", subject_bottom_offset=0):
    """
    bg_path             : 배경 이미지 경로 (없으면 다크 그라디언트 사용)
    lines               : [[(텍스트, 컬러), ...], ...]
    output_path         : 저장 경로
    subject_path        : 합성할 인물/오브젝트 PNG 경로 (투명 배경 필수)
                          None이면 합성 생략
    subject_scale       : 캔버스 높이 대비 인물 크기 비율 (기본 0.7)
    subject_position    : "left" | "center" | "right"
    subject_bottom_offset: 하단에서 올리는 픽셀
    """
    # ── 1) 배경 ─────────────────────────────────────────
    if bg_path and os.path.exists(bg_path):
        bg = Image.open(bg_path).convert("RGBA").resize((WIDTH, HEIGHT))
    else:
        bg = _make_gradient_bg()

    # ── 2) 딤 레이어 ────────────────────────────────────
    if os.path.exists(DIM_PATH):
        dim = Image.open(DIM_PATH).convert("RGBA").resize((WIDTH, HEIGHT))
        bg = Image.alpha_composite(bg, dim)

    # ── 3) 인물/오브젝트 합성 (선택) ────────────────────
    if subject_path and os.path.exists(subject_path):
        bg = composite_subject(
            bg, subject_path,
            scale=subject_scale,
            position=subject_position,
            bottom_offset=subject_bottom_offset,
        )

    # ── 4) 텍스트 + 쉐도우 레이어 ───────────────────────
    text_layer = draw_text_layer(lines, (WIDTH, HEIGHT))
    result = Image.alpha_composite(bg, text_layer)

    result.convert("RGB").save(output_path, "JPEG", quality=95)
    print(f"썸네일 저장 완료: {os.path.basename(output_path)}")


def _make_gradient_bg():
    """배경 이미지 없을 때 사용하는 다크 그라디언트"""
    bg = Image.new("RGBA", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(bg)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(20 + 10 * ratio)
        g = int(20 + 10 * ratio)
        b = int(35 + 15 * ratio)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b, 255))
    return bg


# ── 실행 예시 ──────────────────────────────────────────
if __name__ == "__main__":

    # 색상 기준:
    #   빨간색 — 역설의 대상 (시청자가 "설마?" 하는 핵심 명사)
    #   노란색 — 충격적 결과/행동 (동사·결과 키워드)
    #   흰색   — 조사, 어미, 연결어

    # ── 이란 썸네일 (합성 없음) ───────────────────────────
    make_thumbnail(
        bg_path=os.path.join(MEDIA_DIR, "이란_배경.jpg"),
        lines=[
            [("제재가", "red")],
            [("오히려 ", "white"), ("살려줬다", "yellow")],
        ],
        output_path=os.path.join(MEDIA_DIR, "이란_썸네일.jpg"),
    )

    # ── 소금 썸네일 (합성 없음) ───────────────────────────
    make_thumbnail(
        bg_path=os.path.join(MEDIA_DIR, "소금_배경.jpg"),
        lines=[
            [("금이랑 ", "red"), ("같은", "white")],
            [("무게로 ", "white"), ("바꿨다", "yellow")],
        ],
        output_path=os.path.join(MEDIA_DIR, "소금_썸네일.jpg"),
    )

    # ── 합성 사용 예시 (그린란드 예시) ────────────────────
    # 사전 준비: 인물 사진의 배경을 remove.bg 등으로 제거 후 PNG 저장
    #
    # make_thumbnail(
    #     bg_path=os.path.join(MEDIA_DIR, "그린란드_배경.jpg"),
    #     subject_path=os.path.join(MEDIA_DIR, "트럼프_컷아웃.png"),  # 투명 배경 PNG
    #     subject_scale=0.75,        # 캔버스 높이의 75%
    #     subject_position="right",  # 오른쪽 배치 (텍스트는 왼쪽)
    #     subject_bottom_offset=0,   # 하단 정렬
    #     lines=[
    #         [("그린란드가", "red")],
    #         [("미국 ", "white"), ("땅이 된다", "yellow")],
    #     ],
    #     output_path=os.path.join(MEDIA_DIR, "그린란드_썸네일.jpg"),
    # )
