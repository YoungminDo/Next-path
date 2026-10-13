"""Build apps/api/hellomyme/reference/kr_institutions.csv from the public school list.

Source: 공공데이터포털 '전국대학및전문대학정보표준데이터' (교육부·대학알리미), as fetched by Hello My Me
(`public/data/schools-info.json`, fetched 2026-05-21). Public data (공공누리): names, campus,
level, kind, foundation and region only.

    python scripts/build_kr_institutions.py <hello-my-me>/public/data/schools-info.json

Rules (nothing is invented):
- One row per name. Campuses published under the same name as the main campus are one school;
  campuses with their own name (e.g. 고려대학교(세종)) stay separate.
- Region as the short form already used in the app (서울특별시 -> 서울).
- Aliases only by fixed rules on the official name: "OO대학교"/"OO대학" -> "OO대",
  "OO여자대학교" -> "OO여대", "OO교육대학교" -> "OO교대", "OO대학교(X)" -> "OO대(X)".
  An alias that two schools would share, or that is another school's name, is dropped.
"""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "apps/api/hellomyme/reference/kr_institutions.csv"
REGIONS = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
    "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종",
    "경기도": "경기", "강원특별자치도": "강원", "강원도": "강원", "충청북도": "충북", "충청남도": "충남",
    "전북특별자치도": "전북", "전라북도": "전북", "전라남도": "전남", "경상북도": "경북",
    "경상남도": "경남", "제주특별자치도": "제주",
}
FOUNDATION = {"사립": "PRIVATE", "국립": "NATIONAL", "국립대법": "NATIONAL", "국립대법인": "NATIONAL",
              "공립": "PUBLIC", "특별법국": "NATIONAL", "특별법국립": "NATIONAL",
              "특별법법": "SPECIAL_ACT", "특별법법인": "SPECIAL_ACT"}
LEVEL = {"대학": "UNIVERSITY", "전문대학": "JUNIOR_COLLEGE"}


def norm(t: str) -> str:
    return "".join(ch for ch in t.lower() if ch.isalnum())


def aliases(name: str) -> list[str]:
    core, suffix = name, ""
    if name.endswith(")") and "(" in name:
        core, suffix = name[: name.index("(")], name[name.index("("):]
    out = []
    for long, short in (("여자대학교", "여대"), ("교육대학교", "교대"), ("대학교", "대"), ("대학", "대")):
        if core.endswith(long) and len(core) > len(long) + 1:
            out.append(core[: -len(long)] + short + suffix)
            if long == "여자대학교":
                out.append(core[: -len(long)] + "여자대" + suffix)
            break
    return [a for a in out if a != name]


def main(src: str) -> None:
    schools = json.load(open(src, encoding="utf-8"))["schools"]
    by_name: dict[str, dict] = {}
    for s in sorted(schools, key=lambda s: s["branch"] != "본교"):  # main campus first
        by_name.setdefault(s["name"].strip(), s)
    rows = []
    for name, s in sorted(by_name.items()):
        rows.append({
            "name": name, "name_en": (s.get("nameEn") or "").strip(),
            "school_level": LEVEL[s["type"]], "school_kind": s["subType"],
            "institution_type": FOUNDATION.get(s["foundation"], ""),
            "region": REGIONS.get(s["region"], s["region"]), "aliases": aliases(name),
        })
    names = {norm(r["name"]) for r in rows}
    counts = Counter(norm(a) for r in rows for a in r["aliases"])
    for r in rows:
        r["aliases"] = "|".join(a for a in r["aliases"] if counts[norm(a)] == 1 and norm(a) not in names)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} schools ({Counter(r['school_level'] for r in rows)}) -> {OUT}")
    unmapped = defaultdict(set)
    for s in schools:
        if s["region"] not in REGIONS:
            unmapped["region"].add(s["region"])
        if s["foundation"] not in FOUNDATION:
            unmapped["foundation"].add(s["foundation"])
    print("unmapped:", dict(unmapped) or "none")


if __name__ == "__main__":
    main(sys.argv[1])
