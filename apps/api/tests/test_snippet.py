"""Search result -> career_extraction.v1 (docs/12). Pure: no database."""
import json
from datetime import date

from hellomyme.ingest.pipeline import check
from hellomyme.ingest.snippet import MASK, profile_key, to_extraction

AS_OF = date(2026, 10, 15)
TITLE = "홍길동 - 백엔드 개발자 - 토스 | LinkedIn"
SNIPPET = ("경력: 토스, 카카오 · 토스 2022.03 - 현재 · 카카오 2019 - 2022 · 학력: 고려대학교 · "
           "고려대학교 컴퓨터학과 2013 - 2019 · 홍길동님의 프로필")


KEY = b"test-profile-key-secret"


def test_profile_key_ignores_subdomain_query_and_case():
    a = profile_key("https://kr.linkedin.com/in/Hong-GilDong/?trk=x", KEY)
    b = profile_key("https://www.linkedin.com/in/hong-gildong", KEY)
    assert a == b and len(a) == 64
    assert profile_key("https://www.linkedin.com/company/toss", KEY) is None


def test_profile_key_is_keyed_so_a_guessed_slug_cannot_be_checked_without_the_secret():
    import hashlib
    import hmac
    url = "https://www.linkedin.com/in/gildong-hong"
    key = profile_key(url, KEY)
    assert key != hashlib.sha256(b"linkedin:gildong-hong").hexdigest()
    assert key == hmac.new(KEY, b"linkedin:gildong-hong", hashlib.sha256).hexdigest()
    assert profile_key(url, b"another-secret") != key


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
    # evidence quotes the organization through its dates: the name inside that span is masked
    doc = to_extraction("홍길동 - PM - 쿠팡 | LinkedIn", "쿠팡 홍길동님 2020 - 현재", "k6")
    dumped = json.dumps(doc, ensure_ascii=False)
    assert "홍길동" not in dumped and "[person_pii]님" in dumped

    doc = to_extraction("Gil Hong - PM - Coupang | LinkedIn", "Coupang GIL HONG 2020 - Present", "k7")
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


# --- final review C1: no name reaches any value of the document -----------------------------

def _values(doc) -> str:
    return json.dumps(doc, ensure_ascii=False)


def test_free_text_school_is_only_the_school_and_the_name_never_leaks():
    cases = [
        ("홍길동 - 토스 | LinkedIn", "LinkedIn에서 홍길동님의 프로필 보기 고려대학교 컴퓨터학과", "홍길동"),
        ("홍길동 - 토스 | LinkedIn", "홍길동 고려대학교 경영학과", "홍길동"),
        ("홍길동 - 토스 | LinkedIn", "토스 백엔드 개발자 홍길동 고려대학교", "홍길동"),
        ("이영희 - 토스 | LinkedIn", "김철수 추천 고려대학교", "김철수"),
    ]
    for title, snippet, name in cases:
        doc = to_extraction(title, snippet, "c1")
        dumped = _values(doc)
        assert name not in dumped, (snippet, dumped)
        assert "LinkedIn" not in dumped and "프로필" not in dumped and "보기" not in dumped
        assert [e["institution_raw"] for e in doc["educations"]] == ["고려대학교"]


def test_free_text_english_school_takes_at_most_three_capitalised_words():
    doc = to_extraction("Gil Hong - PM - Coupang | LinkedIn",
                        "View Kim Minsu's profile on LinkedIn Seoul National University", "c2")
    dumped = _values(doc)
    assert "Minsu" not in dumped and "LinkedIn" not in dumped
    assert [e["institution_raw"] for e in doc["educations"]] == ["Seoul National University"]


def test_a_raw_field_holding_the_name_is_dropped():
    # the labelled path copies the label text: a name inside it drops the field (and the row)
    doc = to_extraction("홍길동 - 홍길동컴퍼니 | LinkedIn", "학력: 홍길동대학교", "c3")
    assert doc is None or "홍길동" not in _values(doc)
    doc = to_extraction("홍길동 - 개발자 - 토스 | LinkedIn",
                        "학력: 홍길동 고려대학교 · 토스 2022 - 현재", "c4")
    assert "홍길동" not in _values(doc)
    assert doc["educations"] == []
    assert [w["organization_raw"] for w in doc["work_events"]] == ["토스"]


def test_role_holding_the_name_is_dropped_and_headline_is_masked():
    doc = to_extraction("홍길동 - 홍길동 매니저 - 토스 | LinkedIn", "토스 2022 - 현재", "c5")
    dumped = _values(doc)
    assert "홍길동" not in dumped
    job = doc["work_events"][0]
    assert job["organization_raw"] == "토스" and "role_raw" not in job
    assert doc["person"]["headline_raw"] == f"{MASK} 매니저 - 토스"


def test_a_trailing_linkedin_title_segment_is_not_an_organization():
    for title in ("홍길동 – LinkedIn", "Gil Hong - LinkedIn", "홍길동 - LinkedIn | LinkedIn"):
        doc = to_extraction(title, "고려대학교 경영학과", "c6")
        assert doc["work_events"] == [], title
        assert doc["person"]["headline_raw"] is None


def test_education_whole_snippet_fallback_attaches_nothing_and_quotes_only_the_school():
    # 고려대학교에서: the school is not a whole word in any segment, so no segment is taken
    doc = to_extraction("이영희 | LinkedIn", "김철수 추천 고려대학교에서 컴퓨터학과 졸업 2013 - 2019", "c7")
    assert "김철수" not in _values(doc)
    edu = doc["educations"][0]
    assert edu["institution_raw"] == "고려대학교"
    assert "major_raw" not in edu and "start" not in edu and "end" not in edu
    assert edu["evidence"][0]["text"] == "고려대학교"


# --- final review I1: a month only from a real month name ----------------------------------

def test_a_word_before_a_year_is_not_a_month():
    doc = to_extraction("A - 마케터 - Coupang | LinkedIn", "Coupang Marketing 2019 - 2021", "i1a")
    job = doc["work_events"][0]
    assert job["start"] == {"value": "2019", "precision": "YEAR"}
    assert job["end"] == {"value": "2021", "precision": "YEAR"}
    doc = to_extraction("A - 주니어 - Coupang | LinkedIn", "Coupang Junior 2020 - Present", "i1b")
    job = doc["work_events"][0]
    assert job["start"] == {"value": "2020", "precision": "YEAR"} and job["is_current"] is True
    doc = to_extraction("A - PM - Coupang | LinkedIn", "Coupang Mar 2019 - Present", "i1c")
    assert doc["work_events"][0]["start"] == {"value": "2019-03", "precision": "MONTH"}
    doc = to_extraction("A - PM - Coupang | LinkedIn", "Coupang September 2019 - Present", "i1d")
    assert doc["work_events"][0]["start"] == {"value": "2019-09", "precision": "MONTH"}


# --- final review I2: a date range belongs to the nearest name before it -------------------

def test_another_jobs_dates_in_the_same_segment_are_not_attached():
    doc = to_extraction("A - 개발자 - 토스", "카카오 2019 - 2022, 토스 2022 - 현재", "i2a")
    job = next(w for w in doc["work_events"] if w["organization_raw"] == "토스")
    assert job["start"] == {"value": "2022", "precision": "YEAR"} and job["is_current"] is True
    doc = to_extraction("A - 개발자 - 토스",
                        "경력: 토스, 카카오 · 카카오 2019 - 2022, 토스 2022 - 현재", "i2b")
    jobs = {w["organization_raw"]: w for w in doc["work_events"]}
    assert jobs["토스"]["start"] == {"value": "2022", "precision": "YEAR"} and jobs["토스"]["is_current"]
    assert jobs["카카오"]["start"] == {"value": "2019", "precision": "YEAR"}
    assert jobs["카카오"]["end"] == {"value": "2022", "precision": "YEAR"}
    assert "is_current" not in jobs["카카오"]


def test_a_range_before_the_name_is_not_taken():
    doc = to_extraction("A - 개발자 - 토스", "2019 - 2022 토스", "i2c")
    assert "start" not in doc["work_events"][0]
