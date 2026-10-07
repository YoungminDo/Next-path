import argparse
import json
import sys
from datetime import date

from hellomyme.db import get_engine
from hellomyme.domain.aggregation import run_aggregation
from hellomyme.importer.preseed import ImportAborted, run_import
from hellomyme.importer.retire import RetireRefused, retire_dataset


def _dump(report: dict) -> None:
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2, default=str)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import a HELLOMYME PRE_SEED package (.xlsx workbook from v1.3, CSV dir before)")
    parser.add_argument("path", help="v1.3+ workbook (.xlsx) or a v1.2 CSV directory")
    parser.add_argument("--dataset-version", help="e.g. v1.3 (workbook: read from 00_README)")
    parser.add_argument("--as-of", type=date.fromisoformat,
                        help="dataset as-of date YYYY-MM-DD (workbook: read from 00_README)")
    parser.add_argument("--date-precision", default="MONTH", choices=["DAY", "MONTH", "YEAR"],
                        help="fallback when a row carries no precision of its own")
    parser.add_argument("--retire", action="append", default=[], metavar="VERSION",
                        help="after a successful import, erase this superseded PRE_SEED version")
    parser.add_argument("--no-aggregate", action="store_true",
                        help="skip transition/cohort aggregation after import")
    args = parser.parse_args()

    version, as_of = args.dataset_version, args.as_of
    if args.path.lower().endswith(".xlsx") and (version is None or as_of is None):
        from hellomyme.importer.workbook import readme
        info = readme(args.path)
        version = version or "v" + info.get("Dataset", "").rsplit(" v", 1)[-1]
        as_of = as_of or date.fromisoformat(info["As-of date"])
    if version is None or as_of is None:
        parser.error("--dataset-version and --as-of are required for a CSV package")

    engine = get_engine()
    try:
        report = run_import(engine, args.path, as_of=as_of, dataset_version=version,
                            date_precision=args.date_precision)
    except ImportAborted as exc:
        _dump(exc.report)
        sys.exit(2)
    retired = []
    for old in args.retire:
        if old == version:
            parser.error("cannot retire the version that was just imported")
        try:
            retired.append(retire_dataset(engine, old, reason=f"superseded by PRE_SEED {version}"))
        except RetireRefused as exc:
            retired.append({"status": "NOT_RETIRED", "version": old, "reason": str(exc)})
    if retired:
        report["retired"] = retired
    if not args.no_aggregate:
        report["aggregation"] = run_aggregation(engine, as_of=as_of)
    _dump(report)


if __name__ == "__main__":
    main()
