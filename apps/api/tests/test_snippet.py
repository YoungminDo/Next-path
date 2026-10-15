"""Search result -> career_extraction.v1 (docs/12). Pure: no database."""
import json
from datetime import date

from hellomyme.ingest.pipeline import check
from hellomyme.ingest.snippet import MASK, profile_key, to_extraction

AS_OF = date(2026, 10, 15)
TITLE = "홍길동 - 백엔드 개발자 - 토스 | LinkedIn"
SNIPPET = ("경력: 토스, 카카오 · 토스 2022.03 - 현재 · 카카오 2019 - 2022 · 학력: 고려대학교 · "
           "고려대학교 컴퓨터학과 2013 - 2019 · 홍길동님의 프로필")


def test_profile_key_ignores_subdomain_query_and_case():
    a = profile_key("https://kr.linkedin.com/in/Hong-GilDong/?trk=x")
    b = profile_key("https://www.linkedin.com/in/hong-gildong")
    assert a == b and len(a) == 64
    assert profile_key("https://www.linkedin.com/company/toss") is None


def test_passes_the_pipeline_checks_without_blocks():
    doc = to_extraction(TITLE, SNIPPET, "k1")
    assert not [i for i in check(doc, AS_OF) if i.severity == "BLOCK"]


def test_dates_only_from_the_same_segment_and_no_invented_month():
    doc = to_extraction(TITLE, SNIPPET, "k1")
    jobs = {w["organization_raw"]: w for w in doc["work_events"]}
    assert jobs["토스"]["start"] == {"value": "2022-03", "precision": "MONTH"}
    assert jobs["토스"]["is_current"] is True
    assert jobs["카카오"]["start"] == {"value": "2019", "precision": "YEAR"}
    assert jobs["카카오"]["end"] == {"value": "2022", "precision": "YEAR"}
    edu = doc["educations"][0]
    assert edu["institution_raw"] == "고려대학교" and edu["major_raw"] == "컴퓨터학과"
    assert edu["start"]["value"] == "2013" and edu["end"]["value"] == "2019"


def test_a_lone_year_is_not_attached_to_any_job():
    doc = to_extraction("Kim Lee – PM – Coupang | LinkedIn",
                        "Experience: Coupang, Naver · Seoul · 2019", "k2")
    assert doc["work_events"]
    assert all("start" not in w for w in doc["work_events"])


def test_segment_match_is_whole_word_so_a_similar_name_is_not_taken():
    doc = to_extraction("A - 개발자 - 토스 | LinkedIn",
                        "토스뱅크 2020 - 2021 · 토스 2022 - 현재", "k5")
    job = next(w for w in doc["work_events"] if w["organization_raw"] == "토스")
    assert job["start"] == {"value": "2022", "precision": "YEAR"}
    assert job["is_current"] is True


def test_name_is_masked_in_any_case_and_in_every_token():
    doc = to_extraction("홍길동 - PM - 쿠팡 | LinkedIn", "쿠팡 2020 - 현재 홍길동님", "k6")
    dumped = json.dumps(doc, ensure_ascii=False)
    assert "홍길동" not in dumped and "[person_pii]님" in dumped

    doc = to_extraction("Gil Hong - PM - Coupang | LinkedIn", "Coupang 2020 - Present GIL HONG", "k7")
    dumped = json.dumps(doc, ensure_ascii=False).lower()
    assert "gil" not in dumped and "hong" not in dumped


def test_a_one_character_name_is_not_masked():
    doc = to_extraction("A - 개발자 - Kakao | LinkedIn", "Kakao 2020 - Present", "k8")
    job = next(w for w in doc["work_events"] if w["organization_raw"] == "Kakao")
    assert job["evidence"][0]["text"] == "Kakao 2020 - Present"


def test_the_name_never_leaves_the_function():
    doc = to_extraction(TITLE, SNIPPET, "k1")
    assert "홍길동" not in json.dumps(doc, ensure_ascii=False)
    assert doc["person"]["display_name_raw"] is None
    assert doc["person"]["headline_raw"] == "백엔드 개발자 - 토스"
    # A company shown only in the title has the title line as its evidence: the name is masked there.
    doc = to_extraction("홍길동 - PM - 쿠팡 | LinkedIn", "서울", "k4")
    dumped = json.dumps(doc, ensure_ascii=False)
    assert "홍길동" not in dumped and MASK in dumped


def test_nothing_read_is_empty():
    assert to_extraction("박영희 | LinkedIn", "서울 · 1촌 300명 이상", "k3") is None
