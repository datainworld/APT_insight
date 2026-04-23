FROM python:3.13-slim

WORKDIR /app

# 시스템 패키지
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# uv 설치
RUN pip install --no-cache-dir uv

# 의존성 설치
COPY pyproject.toml uv.lock ./
RUN uv pip install --system .

# 소스 코드
COPY shared/ ./shared/
COPY pipeline/ ./pipeline/
COPY agents/ ./agents/
COPY scripts/ ./scripts/
COPY dash_app/ ./dash_app/
COPY app.py chainlit.md ./
COPY public/ ./public/
COPY .chainlit/ ./.chainlit/

# 정적 자원 (지도 GeoJSON 등) — /app/data 는 Dokploy 볼륨이 덮으므로 별도 경로로 복사
COPY data/maps/ ./assets/maps/

# uploads 디렉토리
RUN mkdir -p /app/uploads /app/data

EXPOSE 8000 8050

# 기본: Chainlit 앱 실행 (pipeline/dashboard 서비스에서 CMD override)
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
