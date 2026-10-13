"""Build apps/api/hellomyme/reference/kr_school_departments.csv (school, college, department).

Source: 공공데이터포털 '전국대학별학과정보표준데이터' (bachelor's programmes that are open), as fetched
by Hello My Me (`public/data/schools-majors.json`, fetched 2026-05-21). Only schools that are in
kr_institutions.csv. Used by the PRE_SEED generator to know which majors a school actually has.

    python scripts/build_kr_school_departments.py <hello-my-me>/public/data/schools-majors.json
"""
import csv
import json
import sys
from pathlib import Path

REF = Path(__file__).resolve().parent.parent / "apps/api/hellomyme/reference"


def main(src: str) -> None:
    data = json.load(open(src, encoding="utf-8"))["data"]
    names = {r["name"] for r in csv.DictReader(open(REF / "kr_institutions.csv", encoding="utf-8"))}
    rows = sorted({(school.strip(), college.strip(), dept.strip())
                   for school, colleges in data.items() if school.strip() in names
                   for college, depts in colleges.items() for dept in depts
                   if dept.strip() and "소속학과없음" not in dept})
    with open(REF / "kr_school_departments.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["school", "college", "department"])
        w.writerows(rows)
    schools = {r[0] for r in rows}
    print(f"{len(rows)} departments in {len(schools)} schools "
          f"({len(set(data) - names)} source schools not in the institution list)")


if __name__ == "__main__":
    main(sys.argv[1])
