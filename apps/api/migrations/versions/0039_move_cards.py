"""Five more result cards at 1 튜브 each (docs/10 §결과 카드).

Students: whether people moved to a bigger company than their first (SIZE_MOVE) and how many times
they moved (JOB_MOVES). Professionals who held the role: whether the next job was another kind of
work (ROLE_SWITCH), a bigger company (ROLE_SIZE_MOVE), and how many times they moved (ROLE_JOB_MOVES).

Revision ID: 0039
Revises: 0038
"""
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

OLD_INSIGHTS = (
    "'PATH_DEEP_DIVE','COMPANY_BREAKDOWN','REPRESENTATIVE_PATHS','TIMING_TENURE','SCHOOL_COMPARE',"
    "'FIRST_COMPANY_SIZE','FIRST_JOB_TENURE','ROLE_NOW','NEXT_COMPANY_SIZE','ROLE_TENURE'"
)
CARDS = ("SIZE_MOVE", "JOB_MOVES", "ROLE_SWITCH", "ROLE_SIZE_MOVE", "ROLE_JOB_MOVES")
NEW_INSIGHTS = OLD_INSIGHTS + "," + ",".join(f"'{c}'" for c in CARDS)


def upgrade() -> None:
    cards = ",\n        ".join(f"('{c}', 1, NULL, 'unlock_v1', 'ACTIVE')" for c in CARDS)
    op.execute(f"""
    ALTER TABLE unlock_policy DROP CONSTRAINT unlock_policy_insight_type_check;
    ALTER TABLE unlock_policy ADD CONSTRAINT unlock_policy_insight_type_check
        CHECK (insight_type IN ({NEW_INSIGHTS}));
    INSERT INTO unlock_policy (insight_type, cost_tube, entitlement_days, version, status) VALUES
        {cards};
    """)


def downgrade() -> None:
    names = ",".join(f"'{c}'" for c in CARDS)
    # Rows an unlock already points at stay (retired), so the widened check stays too.
    op.execute(f"""
    UPDATE unlock_policy SET status = 'RETIRED', effective_to = now() WHERE insight_type IN ({names});
    DELETE FROM unlock_policy p WHERE insight_type IN ({names})
       AND NOT EXISTS (SELECT 1 FROM unlock_event e WHERE e.unlock_policy_id = p.unlock_policy_id);
    """)
