# 무료 이미지/영상 API 사이트 정보

## 이미지 + 영상 둘 다 제공

| 사이트 | API 제한 | 영상 포함 | 상업적 사용 | API 키 |
|--------|---------|---------|------------|--------|
| **Pexels** | 200회/시간, 20,000회/월 | O | O | 필요 (무료 발급) |
| **Pixabay** | 100회/분 | O | O | 필요 (무료 발급) |

## 이미지 전용

| 사이트 | API 제한 | 상업적 사용 | API 키 | 특징 |
|--------|---------|------------|--------|------|
| **Wikimedia Commons** | 속도 제한만 있음 (사실상 무제한) | O | 불필요 | 역사·문헌 자료 특화 |
| **Unsplash** | 시간당 50회 (승인 시 확장) | O | 필요 (무료 발급) | 감성적 현대 이미지 |

---

## 사이트별 특징 상세

### Pexels
- 고화질 스톡 이미지 + 영상 클립 다수 보유
- 현대적·세련된 이미지 위주
- API 문서: https://www.pexels.com/api/

### Pixabay
- 이미지/영상/일러스트/벡터 모두 포함
- Pexels보다 일러스트 계열 풍부
- API 문서: https://pixabay.com/api/docs/

### Wikimedia Commons
- 위키피디아 문서에 사용되는 모든 미디어의 원본 저장소
- **역사 사진, 지도, 문서 원본, 저작권 만료 자료** 특히 풍부
- 1억 개 이상 파일 보유
- API 키 없이 curl로 바로 검색·다운로드 가능
- 유튜브 역사/지식 채널에 최적
- API 문서: https://commons.wikimedia.org/w/api.php

### Unsplash
- 감성적이고 퀄리티 높은 사진 위주
- 인물/자연/라이프스타일 이미지 강점

---

## 용도별 추천 조합

| 영상 주제 | 추천 사이트 |
|---------|------------|
| 역사·지식 (소금, 전세 등) | Wikimedia Commons + Pexels |
| 현대 사회·경제 | Pexels + Pixabay |
| 감성적 브이로그 스타일 | Unsplash + Pexels |

---

## Wikimedia Commons API 사용법 (API 키 불필요)

### 키워드 검색
```bash
curl "https://commons.wikimedia.org/w/api.php?action=query&list=search&srsearch=검색어&srnamespace=6&format=json"
```

### 파일 다운로드 URL 조회
```bash
curl "https://commons.wikimedia.org/w/api.php?action=query&titles=File:파일명.jpg&prop=imageinfo&iiprop=url&format=json"
```

### 이미지 다운로드
```bash
curl -o output.jpg "https://upload.wikimedia.org/..."
```

---

## Pexels + Pixabay API 사용법

### Pexels 이미지 검색
```bash
curl -H "Authorization: YOUR_API_KEY" \
  "https://api.pexels.com/v1/search?query=검색어&per_page=10"
```

### Pexels 영상 검색
```bash
curl -H "Authorization: YOUR_API_KEY" \
  "https://api.pexels.com/videos/search?query=검색어&per_page=10"
```

### Pixabay 이미지 검색
```bash
curl "https://pixabay.com/api/?key=YOUR_API_KEY&q=검색어&image_type=photo&per_page=10"
```

### Pixabay 영상 검색
```bash
curl "https://pixabay.com/api/videos/?key=YOUR_API_KEY&q=검색어&per_page=10"
```
