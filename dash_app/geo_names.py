"""수도권 지도 시군구명과 DB 시군구명의 불일치 정규화.

불일치 원인:
- 인천 남구 → 2018년 미추홀구로 개명 (지도 데이터는 2013년)
- 경기 시+구 복합명: 지도는 공백 없음(고양시덕양구), DB 는 공백 있음(고양시 덕양구)
- 화성시: 지도는 `화성시` 단일, DB 는 `화성시 동탄구` / `화성시 병점구` 로 분할

경로:
- `normalize_geo_name(name, code)` — 지도 로드 시 적용 (로컬 ground truth 를 DB 형식에 맞춤)
- `collapse_db_sgg_to_geo(values_by_sgg)` — DB 집계 결과를 지도 이름에 맞춰 합산
"""

from __future__ import annotations

from collections.abc import Mapping

_OLD_TO_NEW_INCHEON = {"남구": "미추홀구"}

_COMPOUND_SI_GU = {
    # 지도에는 공백 없는 복합명. 공백을 추가해 DB 와 동일하게 정규화.
    "고양시덕양구": "고양시 덕양구",
    "고양시일산동구": "고양시 일산동구",
    "고양시일산서구": "고양시 일산서구",
    "부천시소사구": "부천시 소사구",
    "부천시오정구": "부천시 오정구",
    "부천시원미구": "부천시 원미구",
    "성남시분당구": "성남시 분당구",
    "성남시수정구": "성남시 수정구",
    "성남시중원구": "성남시 중원구",
    "수원시권선구": "수원시 권선구",
    "수원시영통구": "수원시 영통구",
    "수원시장안구": "수원시 장안구",
    "수원시팔달구": "수원시 팔달구",
    "안산시단원구": "안산시 단원구",
    "안산시상록구": "안산시 상록구",
    "안양시동안구": "안양시 동안구",
    "안양시만안구": "안양시 만안구",
    "용인시기흥구": "용인시 기흥구",
    "용인시수지구": "용인시 수지구",
    "용인시처인구": "용인시 처인구",
}


def normalize_geo_name(name: str, sido_code_prefix: str) -> str:
    """지도의 feature.properties.name → DB 와 호환되는 canonical 이름."""
    if not name:
        return name
    if sido_code_prefix == "23" and name in _OLD_TO_NEW_INCHEON:
        return _OLD_TO_NEW_INCHEON[name]
    return _COMPOUND_SI_GU.get(name, name)


def collapse_db_sgg_to_geo(
    values_by_sgg: Mapping[str, float],
    *,
    aggregator: str = "mean",
) -> dict[str, float]:
    """DB 집계 결과를 지도 feature 기준으로 재정렬.

    화성시처럼 지도는 단일 polygon 인데 DB 에 세분화된 sgg 가 있는 경우,
    해당 parent 로 합산(`sum`) 또는 평균(`mean`). `sum` 은 거래건수 류, `mean` 은 비율 류.
    """
    parents: dict[str, tuple[float, int]] = {}
    out: dict[str, float] = {}
    for k, v in values_by_sgg.items():
        if v is None:
            continue
        if k.startswith("화성시 "):
            total, n = parents.get("화성시", (0.0, 0))
            parents["화성시"] = (total + float(v), n + 1)
        else:
            out[k] = float(v)
    for parent, (total, n) in parents.items():
        if parent in out:
            continue
        out[parent] = (total / n) if (aggregator == "mean" and n) else total
    return out
