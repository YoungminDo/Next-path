"""Index the foreign keys that point at people, career events and source records.

Erasing a person (a member's deletion, or retiring a PRE_SEED version) cascades into these
tables; without an index every deleted row scanned them whole, so retiring 30k pre-seed people
took tens of minutes. Partial indexes where the column is mostly empty. Also speeds up reading
a person's transitions and snapshot.

Revision ID: 0033
Revises: 0032
"""
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

INDEXES = [
    ("career_transition_person_idx", "career_transition", "person_id", None),
    ("career_transition_from_event_idx", "career_transition", "from_work_event_id", None),
    ("career_transition_to_event_idx", "career_transition", "to_work_event_id", None),
    ("career_person_snapshot_person_idx", "career_person_snapshot", "person_id", None),
    ("career_person_snapshot_event_idx", "career_person_snapshot", "current_work_event_id",
     "current_work_event_id IS NOT NULL"),
    ("person_primary_source_idx", "person", "primary_source_id", "primary_source_id IS NOT NULL"),
    ("person_gender_source_idx", "person", "gender_source_id", "gender_source_id IS NOT NULL"),
    ("person_first_employment_source_idx", "person", "reported_first_employment_source_id",
     "reported_first_employment_source_id IS NOT NULL"),
    ("verification_log_source_idx", "verification_log", "source_id", "source_id IS NOT NULL"),
    ("identity_match_target_idx", "identity_match", "target_person_id", None),
    ("anonymous_draft_claimed_person_idx", "anonymous_draft", "claimed_person_id",
     "claimed_person_id IS NOT NULL"),
    ("decision_event_related_event_idx", "decision_event", "related_work_event_id",
     "related_work_event_id IS NOT NULL"),
    ("source_submission_person_idx", "source_submission", "loaded_person_id",
     "loaded_person_id IS NOT NULL"),
    ("source_submission_source_idx", "source_submission", "source_id", "source_id IS NOT NULL"),
    ("work_event_field_resolution_source_idx", "work_event_field_resolution", "winning_source_id",
     "winning_source_id IS NOT NULL"),
    ("organization_industry_source_idx", "organization_industry", "source_id",
     "source_id IS NOT NULL"),
]


def upgrade() -> None:
    for name, table, column, where in INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"
                   + (f" WHERE {where}" if where else ""))


def downgrade() -> None:
    for name, *_ in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
