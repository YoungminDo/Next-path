"""Statistics leave out the team's own sessions even when the draft was saved before it carried
the flag: a draft counts as internal when its browser session sent any event marked internal
(?internal=1). Only the views change; drafts and events stay as they were stored.

Revision ID: 0028
Revises: 0027
"""
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    -- Hash of each anonymous session the team marked (same SHA-256 as anonymous_draft.session_id).
    CREATE VIEW analytics.team_session AS
    SELECT DISTINCT encode(sha256(convert_to(anonymous_session_id, 'UTF8')), 'hex') AS team_session_hash
    FROM analytics.event
    WHERE anonymous_session_id IS NOT NULL AND properties->>'internal' = 'true';

    CREATE OR REPLACE VIEW analytics.acq_input AS
    WITH team AS (SELECT * FROM analytics.team_session)
    SELECT d.draft_id, d.session_id AS session_hash, d.created_at, d.updated_at AS last_saved_at,
           d.revision, (d.internal OR d.session_id IN (SELECT team_session_hash FROM team)) AS internal, d.user_type,
           e->>'institution_id' AS institution_id, i.name AS institution_name,
           e->>'institution_raw' AS institution_raw,
           (i.institution_id IS NOT NULL) AS institution_listed,
           name_key('INSTITUTION', coalesce(i.name, e->>'institution_raw')) AS institution_key,
           e->>'major_node_id' AS major_node_id, mn.display_name AS major_label,
           mp.display_name AS major_group, e->>'major_raw' AS major_raw,
           (mn.taxonomy_node_id IS NOT NULL) AS major_listed,
           name_key('MAJOR', coalesce(mn.display_name, e->>'major_raw')) AS major_key,
           (e->>'admission_year')::int AS admission_year,
           (e->>'graduation_year')::int AS graduation_year,
           j->>'role_node_id' AS current_role_node_id, rn.display_name AS current_role_label,
           j->>'organization_name' AS current_company, (j->>'start_year')::int AS current_start_year,
           d.payload_json->>'desired_role_status' AS desired_role_status,
           jsonb_array_length(coalesce(d.payload_json->'desired_roles', '[]'::jsonb))
               AS n_desired_roles,
           d.claimed_account_id, d.claimed_at
    FROM anonymous_draft d
    CROSS JOIN LATERAL (SELECT d.payload_json->'education' AS e,
                               d.payload_json->'current_job' AS j) p
    LEFT JOIN institution i ON i.institution_id::text = e->>'institution_id'
    LEFT JOIN taxonomy_node mn ON mn.taxonomy_node_id::text = e->>'major_node_id'
    LEFT JOIN taxonomy_node mp ON mp.taxonomy_node_id = mn.parent_node_id
    LEFT JOIN taxonomy_node rn ON rn.taxonomy_node_id::text = j->>'role_node_id'
    WHERE d.payload_json->>'schema_version' = 'acq_v1';

    CREATE OR REPLACE VIEW analytics.acq_desired_role AS
    WITH team AS (SELECT * FROM analytics.team_session)
    SELECT d.draft_id, d.session_id AS session_hash, (d.internal OR d.session_id IN (SELECT team_session_hash FROM team)) AS internal, d.user_type,
           r.ordinality::int AS rank, r.value->>'role_node_id' AS role_node_id,
           n.display_name AS role_label, np.display_name AS role_group,
           r.value->>'role_raw' AS role_raw, (n.taxonomy_node_id IS NOT NULL) AS role_listed,
           name_key('ROLE', coalesce(n.display_name, r.value->>'role_raw')) AS role_key,
           d.updated_at AS last_saved_at
    FROM anonymous_draft d
    CROSS JOIN LATERAL jsonb_array_elements(coalesce(d.payload_json->'desired_roles', '[]'::jsonb))
         WITH ORDINALITY AS r(value, ordinality)
    LEFT JOIN taxonomy_node n ON n.taxonomy_node_id::text = r.value->>'role_node_id'
    LEFT JOIN taxonomy_node np ON np.taxonomy_node_id = n.parent_node_id
    WHERE d.payload_json->>'schema_version' = 'acq_v1';

    """)


def downgrade() -> None:
    op.execute("""
    CREATE OR REPLACE VIEW analytics.acq_input AS
    SELECT d.draft_id, d.session_id AS session_hash, d.created_at, d.updated_at AS last_saved_at,
           d.revision, d.internal, d.user_type,
           e->>'institution_id' AS institution_id, i.name AS institution_name,
           e->>'institution_raw' AS institution_raw,
           (i.institution_id IS NOT NULL) AS institution_listed,
           name_key('INSTITUTION', coalesce(i.name, e->>'institution_raw')) AS institution_key,
           e->>'major_node_id' AS major_node_id, mn.display_name AS major_label,
           mp.display_name AS major_group, e->>'major_raw' AS major_raw,
           (mn.taxonomy_node_id IS NOT NULL) AS major_listed,
           name_key('MAJOR', coalesce(mn.display_name, e->>'major_raw')) AS major_key,
           (e->>'admission_year')::int AS admission_year,
           (e->>'graduation_year')::int AS graduation_year,
           j->>'role_node_id' AS current_role_node_id, rn.display_name AS current_role_label,
           j->>'organization_name' AS current_company, (j->>'start_year')::int AS current_start_year,
           d.payload_json->>'desired_role_status' AS desired_role_status,
           jsonb_array_length(coalesce(d.payload_json->'desired_roles', '[]'::jsonb))
               AS n_desired_roles,
           d.claimed_account_id, d.claimed_at
    FROM anonymous_draft d
    CROSS JOIN LATERAL (SELECT d.payload_json->'education' AS e,
                               d.payload_json->'current_job' AS j) p
    LEFT JOIN institution i ON i.institution_id::text = e->>'institution_id'
    LEFT JOIN taxonomy_node mn ON mn.taxonomy_node_id::text = e->>'major_node_id'
    LEFT JOIN taxonomy_node mp ON mp.taxonomy_node_id = mn.parent_node_id
    LEFT JOIN taxonomy_node rn ON rn.taxonomy_node_id::text = j->>'role_node_id'
    WHERE d.payload_json->>'schema_version' = 'acq_v1';

    CREATE OR REPLACE VIEW analytics.acq_desired_role AS
    SELECT d.draft_id, d.session_id AS session_hash, d.internal, d.user_type,
           r.ordinality::int AS rank, r.value->>'role_node_id' AS role_node_id,
           n.display_name AS role_label, np.display_name AS role_group,
           r.value->>'role_raw' AS role_raw, (n.taxonomy_node_id IS NOT NULL) AS role_listed,
           name_key('ROLE', coalesce(n.display_name, r.value->>'role_raw')) AS role_key,
           d.updated_at AS last_saved_at
    FROM anonymous_draft d
    CROSS JOIN LATERAL jsonb_array_elements(coalesce(d.payload_json->'desired_roles', '[]'::jsonb))
         WITH ORDINALITY AS r(value, ordinality)
    LEFT JOIN taxonomy_node n ON n.taxonomy_node_id::text = r.value->>'role_node_id'
    LEFT JOIN taxonomy_node np ON np.taxonomy_node_id = n.parent_node_id
    WHERE d.payload_json->>'schema_version' = 'acq_v1';

    DROP VIEW analytics.team_session;
    """)
