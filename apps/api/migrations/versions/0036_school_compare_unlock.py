"""A 튜브 product: the same question answered for other schools (docs/10 §결과 카드).

The member's result shows their own school·major for free; "다른 학교, 같은 과" opens with 튜브
like the path deep dive. Cost lives here, in unlock_policy, never in code.

Revision ID: 0036
Revises: 0035
"""
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

OLD = "'PATH_DEEP_DIVE','COMPANY_BREAKDOWN','REPRESENTATIVE_PATHS','TIMING_TENURE'"


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE unlock_policy DROP CONSTRAINT unlock_policy_insight_type_check;
    ALTER TABLE unlock_policy ADD CONSTRAINT unlock_policy_insight_type_check
        CHECK (insight_type IN ({OLD},'SCHOOL_COMPARE'));
    INSERT INTO unlock_policy (insight_type, cost_tube, entitlement_days, version, status)
    VALUES ('SCHOOL_COMPARE', 1, NULL, 'unlock_v1', 'ACTIVE');
    """)


def downgrade() -> None:
    op.execute(f"""
    DELETE FROM unlock_policy p WHERE insight_type = 'SCHOOL_COMPARE'
       AND NOT EXISTS (SELECT 1 FROM unlock_event e WHERE e.unlock_policy_id = p.unlock_policy_id);
    ALTER TABLE unlock_policy DROP CONSTRAINT unlock_policy_insight_type_check;
    ALTER TABLE unlock_policy ADD CONSTRAINT unlock_policy_insight_type_check
        CHECK (insight_type IN ({OLD}));
    """)
