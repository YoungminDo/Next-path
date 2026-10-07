from datetime import date

import pytest

from hellomyme.config import Settings
from hellomyme.domain.aggregation import Event, build_person, split_tracks
from hellomyme.domain.career_map import distribution
from hellomyme.domain.cohort import build_cohort
from hellomyme.domain.policies import CohortPolicy, ScoringPolicy
from hellomyme.domain.similarity import Profile, bucket, score

AS_OF = date(2026, 10, 7)
POLICY = CohortPolicy("p", "test_v1", min_exact_n=30, graduation_window_years=2,
                      fallback_enabled=True, similarity_fallback_k=100, max_fallback_level=3,
                      dimension_fallback_order=("graduation_year", "current_job_family",
                                                "institution_id"), min_cell_n=5)
SIM = ScoringPolicy("s", "CAREER_SIMILARITY", "sim_test",
                    weights={"institution": 2, "major": 2, "graduation_year": 1,
                             "current_job_family": 2, "career_sequence": 1, "stage": 0.5},
                    params={"graduation_year_decay_years": 5, "major_family_partial": 0.5,
                            "bucket_thresholds": {"VERY_SIMILAR": 0.75, "SIMILAR": 0.5}})


def ev(i, typ, start, end=None, current=None, family="DATA"):
    return Event(f"e{i}", typ, start, end, current, f"r-{family}", family, "o", "IND", "LARGE",
                 False)


# --- transitions -----------------------------------------------------------------------------

def test_overlapping_side_business_is_parallel_not_a_transition():
    events = [ev(1, "EMPLOYMENT", date(2018, 1, 1), date(2021, 1, 1)),
              ev(2, "SIDE_BUSINESS", date(2019, 6, 1), None, True, "FOUNDER"),
              ev(3, "EMPLOYMENT", date(2021, 3, 1), None, True, "PRODUCT")]
    primary, parallel = split_tracks(events)
    assert [e.work_event_id for e in primary] == ["e1", "e3"]
    assert [e.work_event_id for e in parallel] == ["e2"]
    snap, transitions = build_person({"person_id": "p", "origin_layer": "PRE_SEED"},
                                     {"institution_id": "i", "major_id": "m", "major_family": "F",
                                      "graduation_year": 2018}, events, AS_OF)
    assert snap["current_job_family"] == "PRODUCT"
    assert snap["parallel_event_count"] == 1
    moves = [(t["from_job_family"], t["to_job_family"]) for t in transitions]
    assert moves == [(None, "DATA"), ("DATA", "PRODUCT")]
    assert transitions[1]["from_tenure_months"] == 36
    assert transitions[1]["gap_months"] == 2


def test_standalone_freelance_is_primary():
    primary, parallel = split_tracks([ev(1, "FREELANCE", date(2020, 1, 1), None, True)])
    assert len(primary) == 1 and not parallel


def test_pre_graduation_events_are_not_the_entry_and_unknowns_stay_null():
    events = [ev(1, "EMPLOYMENT", date(2017, 7, 1), date(2017, 9, 1)),  # internship
              ev(2, "EMPLOYMENT", date(2019, 2, 1))]  # no end date, not current: unknown
    _, transitions = build_person({"person_id": "p", "origin_layer": "PRE_SEED"},
                                  {"institution_id": None, "major_id": None, "major_family": None,
                                   "graduation_year": 2019}, events, AS_OF)
    entry = [t for t in transitions if t["from_work_event_id"] is None]
    assert entry[0]["to_work_event_id"] == "e2"
    assert entry[0]["years_since_graduation"] == 0
    assert transitions[-1]["from_tenure_months"] == 2


# --- adaptive cohort -------------------------------------------------------------------------

def people(n, **kw):
    return [Profile(person_id=f"{kw.get('institution_id')}-{kw.get('graduation_year')}-{i}-"
                    f"{kw.get('major_id')}", **kw) for i in range(n)]


def test_level0_exact_when_dense():
    pop = people(30, institution_id="A", major_id="M", graduation_year=2020)
    res = build_cohort(Profile(institution_id="A", major_id="M", graduation_year=2020), pop,
                       POLICY, SIM)
    assert (res.fallback_level, res.exact_n, res.effective_n, res.suppressed) == (0, 30, 30, False)
    assert res.cohort_policy_version == "test_v1"


def test_level1_graduation_window():
    pop = [p for y in range(2018, 2023) for p in people(7, institution_id="A", major_id="M",
                                                          graduation_year=y)]
    res = build_cohort(Profile(institution_id="A", major_id="M", graduation_year=2020), pop,
                       POLICY, SIM)
    assert res.fallback_level == 1 and res.exact_n == 7 and res.effective_n == 35
    assert res.applied_dimensions["graduation_window_years"] == 2


def test_level2_dimension_fallback_in_policy_order():
    pop = [p for y in range(2010, 2026, 5) for p in people(10, institution_id="A", major_id="M",
                                                             graduation_year=y)]
    res = build_cohort(Profile(institution_id="A", major_id="M", graduation_year=2015), pop,
                       POLICY, SIM)
    assert res.fallback_level == 2
    assert res.applied_dimensions == {"institution_id": "A", "major_id": "M"}
    assert res.effective_n == 40


def test_level3_similarity_top_k():
    pop = [p for inst in "BCDEFGH" for p in people(5, institution_id=inst, major_id="X",
                                                     major_family="F", graduation_year=2020)]
    q = Profile(institution_id="A", major_id="M", major_family="F", graduation_year=2020)
    res = build_cohort(q, pop, POLICY, SIM)
    assert res.fallback_level == 3 and res.effective_n == 35
    assert all(0 < s < 1 for s in res.similarity.values())


def test_suppressed_when_nothing_reaches_threshold():
    pop = people(10, institution_id="A", major_id="M", graduation_year=2020)
    res = build_cohort(Profile(institution_id="A", major_id="M", graduation_year=2020), pop,
                       POLICY, SIM)
    assert res.suppressed and res.person_ids == []
    assert res.exact_n == 10


def test_query_person_is_never_in_own_cohort():
    pop = people(31, institution_id="A", major_id="M", graduation_year=2020)
    me = pop[0]
    res = build_cohort(me, pop, POLICY, SIM)
    assert (res.fallback_level, res.exact_n) == (0, 30)
    assert me.person_id not in res.person_ids


# --- similarity / disclosure -----------------------------------------------------------------

def test_similarity_ignores_features_the_query_does_not_have():
    q = Profile(major_id="M", major_family="F")
    same_major = Profile(major_id="M", institution_id="Z", graduation_year=1990)
    assert score(q, same_major, SIM)[0] == 1.0
    assert bucket(0.8, SIM) == "VERY_SIMILAR" and bucket(0.1, SIM) == "RELATED"


def test_distribution_folds_small_cells_into_other():
    dist = distribution(["A"] * 20 + ["B"] * 4 + ["C"] * 3, min_cell_n=5)
    assert dist == [{"value": "A", "n": 20, "share_pct": 74},
                    {"value": "OTHER", "n": 7, "share_pct": 26}]


def test_production_refuses_preseed_and_dev_login():
    with pytest.raises(ValueError):
        Settings(env="production", career_map_data_layers=["PRE_SEED", "VERIFIED"],
                 auth_providers=["KAKAO"])
    with pytest.raises(ValueError):
        Settings(env="production", career_map_data_layers=["SEED", "VERIFIED"],
                 auth_providers=["DEV"])
    ok = Settings(env="production", career_map_data_layers=["SEED", "VERIFIED"],
                  auth_providers=["KAKAO", "GOOGLE"])
    assert not ok.is_simulation
