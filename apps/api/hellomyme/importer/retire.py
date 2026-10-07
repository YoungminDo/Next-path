"""Retire a superseded PRE_SEED dataset version (e.g. v1.2 once v1.3 is the official one).

PRE_SEED is generated data that is never shown as a person, so a superseded version is erased
outright instead of being kept beside the new one. Erasure uses the same audited switch as
personal-data deletion (hellomyme.erasure); the import_batch row and its report remain as the
record that the version existed and was retired.
"""
from __future__ import annotations

from sqlalchemy import Engine, text

from hellomyme.importer.preseed import source_system


class RetireRefused(Exception):
    pass


def retire_dataset(engine: Engine, dataset_version: str, reason: str) -> dict:
    system = source_system(dataset_version)
    with engine.begin() as conn:
        batches = conn.execute(
            text("""SELECT import_batch_id FROM import_batch
                    WHERE source_system = :s AND data_layer = 'PRE_SEED' AND status = 'COMPLETED'"""),
            {"s": system},
        ).scalars().all()
        if not batches:
            raise RetireRefused(f"no completed PRE_SEED import for {system}")

        person_ids = conn.execute(
            text("""SELECT p.person_id FROM entity_key_map k JOIN person p ON p.person_id = k.entity_id
                    WHERE k.source_system = :s AND k.entity_type = 'PERSON'
                      AND p.origin_layer = 'PRE_SEED'"""),
            {"s": system},
        ).scalars().all()
        # These must never exist for PRE_SEED; if they do, stop rather than cascade into them.
        blockers = conn.execute(
            text("""SELECT
                      (SELECT count(*) FROM person WHERE person_id = ANY(:ids)
                         AND account_id IS NOT NULL) AS with_account,
                      (SELECT count(*) FROM identity_match WHERE candidate_person_id = ANY(:ids)
                         OR target_person_id = ANY(:ids)) AS identity_matches,
                      (SELECT count(*) FROM anonymous_draft
                         WHERE claimed_person_id = ANY(:ids)) AS claimed_drafts"""),
            {"ids": person_ids},
        ).one()
        if any(blockers):
            raise RetireRefused(f"PRE_SEED persons are linked to real data: {blockers._asdict()}")

        conn.execute(text("SET LOCAL hellomyme.erasure = 'on'"))
        deleted_persons = conn.execute(
            text("DELETE FROM person WHERE person_id = ANY(:ids)"), {"ids": person_ids}
        ).rowcount
        deleted_sources = conn.execute(
            text("""DELETE FROM source_record WHERE source_system = :s AND data_layer = 'PRE_SEED'
                      AND NOT EXISTS (SELECT 1 FROM verification_log v
                                      WHERE v.source_id = source_record.source_id)"""),
            {"s": system},
        ).rowcount
        conn.execute(text("DELETE FROM entity_key_map WHERE source_system = :s"), {"s": system})
        conn.execute(
            text("""UPDATE import_batch SET status = 'RETIRED', retired_at = now(),
                        retired_reason = :r WHERE import_batch_id = ANY(:b)"""),
            {"r": reason, "b": list(batches)},
        )
    return {"status": "RETIRED", "source_system": system, "import_batches": [str(b) for b in batches],
            "deleted_persons": deleted_persons, "deleted_source_records": deleted_sources}
