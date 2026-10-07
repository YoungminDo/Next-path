"""Read-only profiling of the HELLOMYME PRE_SEED CSV package.

Reproduces the numbers in docs/00_ARCHITECTURE_REVIEW.md section 3.
Does not modify or generate data.

Usage: python3 -I scripts/profile_preseed.py <csv_dir> [as_of_date]
"""
import sys

import pandas as pd


def load(csv_dir, name):
    return pd.read_csv(
        f"{csv_dir}/{name}.csv", encoding="utf-8-sig", dtype=str, keep_default_na=False
    )


def main(csv_dir, as_of):
    P, E, W, S = (load(csv_dir, n) for n in ("persons", "educations", "work_events", "work_event_sources"))
    W["sd"] = pd.to_datetime(W.start_date, errors="coerce")
    W["ed"] = pd.to_datetime(W.end_date, errors="coerce")
    cur = W.is_current == "True"

    out = {
        "persons": len(P),
        "educations": len(E),
        "work_events": len(W),
        "work_event_sources": len(S),
        "user_stage": P.user_stage.value_counts().to_dict(),
        "event_type": W.event_type.value_counts().to_dict(),
        "end_before_start": int((W.ed < W.sd).sum()),
        "end_equals_start": int((W.ed == W.sd).sum()),
        f"start_after_{as_of}": int((W.sd > as_of).sum()),
        f"current_but_start_after_{as_of}": int((cur & (W.sd > as_of)).sum()),
        f"end_after_{as_of}": int((W.ed > as_of).sum()),
        "all_dates_first_of_month": bool((W.sd.dt.day == 1).all()),
        "persons_multi_current": int((W[cur].person_id.value_counts() > 1).sum()),
        "job_seekers_with_current_employment": int(
            W[cur & W.person_id.isin(P[P.user_stage == "JOB_SEEKER"].person_id)].person_id.nunique()
        ),
        "professionals_without_current": int(
            (~P[P.user_stage == "PROFESSIONAL"].person_id.isin(W[cur].person_id)).sum()
        ),
        "founder_role_as_employment": int(((W.role_id == "ROLE021") & (W.event_type == "EMPLOYMENT")).sum()),
    }

    ws = W.sort_values(["person_id", "sd"]).copy()
    ws["prev_end"] = ws.groupby("person_id").ed.shift()
    ws["prev_type"] = ws.groupby("person_id").event_type.shift()
    overlap = ws[ws.sd < ws.prev_end]
    out["overlap_pairs"] = (overlap.prev_type + ">" + overlap.event_type).value_counts().to_dict()

    sm = E.groupby(["institution_id", "major_id"]).size()
    smg = E.groupby(["institution_id", "major_id", "graduation_year"]).size()
    out["cohort_school_major"] = {"cells": len(sm), "below_30": int((sm < 30).sum())}
    out["cohort_school_major_gradyear"] = {
        "cells": len(smg), "below_30": int((smg < 30).sum()), "max": int(smg.max())
    }

    for k, v in out.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "2026-10-07")
