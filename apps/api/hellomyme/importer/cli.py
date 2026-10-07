import argparse
import json
import sys
from datetime import date

from hellomyme.db import get_engine
from hellomyme.domain.aggregation import run_aggregation
from hellomyme.importer.preseed import ImportAborted, run_import


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a HELLOMYME PRE_SEED CSV package")
    parser.add_argument("csv_dir")
    parser.add_argument("--dataset-version", required=True, help="e.g. v1.2")
    parser.add_argument("--as-of", type=date.fromisoformat, required=True,
                        help="dataset as-of date (YYYY-MM-DD)")
    parser.add_argument("--date-precision", default="MONTH", choices=["DAY", "MONTH", "YEAR"])
    parser.add_argument("--no-aggregate", action="store_true",
                        help="skip transition/cohort aggregation after import")
    args = parser.parse_args()

    engine = get_engine()
    try:
        report = run_import(engine, args.csv_dir, as_of=args.as_of,
                            dataset_version=args.dataset_version,
                            date_precision=args.date_precision)
    except ImportAborted as exc:
        json.dump(exc.report, sys.stdout, ensure_ascii=False, indent=2, default=str)
        sys.exit(2)
    if not args.no_aggregate:
        report["aggregation"] = run_aggregation(engine, as_of=args.as_of)
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2, default=str)
    print()


if __name__ == "__main__":
    main()
