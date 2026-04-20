"""pytest 세션 픽스처.

testcontainers PostgreSQL 은 `--with-db` 옵션 또는 `USE_TESTCONTAINERS=1` 환경변수를
지정한 경우에만 기동한다 (기본 실행은 빠르게 유지).
"""

from __future__ import annotations

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--with-db",
        action="store_true",
        default=False,
        help="testcontainers PostgreSQL 컨테이너를 기동하고 DB 통합 테스트 실행",
    )


@pytest.fixture(scope="session")
def postgres_url(request: pytest.FixtureRequest) -> str:
    """DATABASE_URL 대체용. --with-db 가 있을 때만 컨테이너 기동."""
    if not (request.config.getoption("--with-db") or os.getenv("USE_TESTCONTAINERS")):
        pytest.skip("DB 통합 테스트 — `--with-db` 또는 USE_TESTCONTAINERS=1 필요")

    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer("postgres:18")
    container.start()
    request.addfinalizer(container.stop)
    return container.get_connection_url()
