"""Every answer is data: draft history, desired roles, and the statistics views over them.

- anonymous_draft_revision: each save of a draft as sent (append-only); the draft row keeps the
  latest answer. Nothing typed is overwritten, with or without login.
- anonymous_draft.internal: the team's own browsers (?internal=1), left out of statistics.
- name_key(): a grouping key for typed names (spacing, punctuation, 대학교/학과-style suffixes).
  The raw text is never changed; the key only groups spellings for counting.
- desired_role: what a member wants to do next, written once from the draft at login and appended
  on change. 'NONE' (no desired role yet) is an answer of its own, unlike a skipped question.
- analytics views: one row per draft (acq_input), its desired roles (acq_desired_role), and the
  typed names nobody has standardised yet, by how many people typed them (acq_unlisted_backlog).

Revision ID: 0026
Revises: 0025
"""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

OLD_EVENTS = (
    "'career_input_started','career_input_completed','career_query_requested',"
    "'login_wall_viewed','signup_completed','career_map_viewed','filter_applied',"
    "'unlock_viewed','unlock_purchased','credit_purchased','mentor_viewed',"
    "'mentor_contact_clicked','mentor_order_created','career_updated','career_reconfirmed',"
    "'landing_viewed','login_clicked','result_step_viewed','result_left',"
    "'intent_selected','school_requested'"
)
NEW_EVENTS = OLD_EVENTS + (",'desired_role_selected','interview_step_viewed','interview_skipped',"
                           "'interview_code_sent','interview_submitted','interview_withdrawn'")


def upgrade() -> None:
    op.execute(f"""
    ALTER TABLE anonymous_draft
        ADD COLUMN internal boolean NOT NULL DEFAULT false,
        ADD COLUMN revision integer NOT NULL DEFAULT 1 CHECK (revision > 0);

    CREATE TABLE anonymous_draft_revision (
        draft_id     uuid NOT NULL REFERENCES anonymous_draft,
        revision     integer NOT NULL CHECK (revision > 0),
        payload_json jsonb NOT NULL,
        created_at   timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (draft_id, revision)
    );
    CREATE TRIGGER anonymous_draft_revision_append_only
        BEFORE UPDATE OR DELETE ON anonymous_draft_revision
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
    ALTER TABLE anonymous_draft_revision ENABLE ROW LEVEL SECURITY;
    INSERT INTO anonymous_draft_revision (draft_id, revision, payload_json, created_at)
        SELECT draft_id, 1, payload_json, updated_at FROM anonymous_draft;

    CREATE FUNCTION name_key(kind text, t text) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path = public AS $$
        SELECT CASE kind
            WHEN 'INSTITUTION' THEN regexp_replace(normalize_label(t), '(대학교|대학|대)$', '')
            WHEN 'MAJOR' THEN regexp_replace(
                regexp_replace(normalize_label(t), '(학과|학부|전공|계열|과)$', ''), '학$', '')
            WHEN 'ROLE' THEN regexp_replace(normalize_label(t), '(직무|담당자|담당|업무|직)$', '')
            ELSE normalize_label(t) END
    $$;

    CREATE TABLE desired_role (
        desired_role_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        person_id             uuid NOT NULL REFERENCES person ON DELETE CASCADE,
        -- CHOSEN: one row per role in the member's order; NONE / UNSURE / KEEP_CURRENT: one row.
        status                text NOT NULL CHECK (status IN
                                  ('CHOSEN','NONE','UNSURE','KEEP_CURRENT')),
        rank                  integer NOT NULL CHECK (rank BETWEEN 1 AND 3),
        role_taxonomy_node_id uuid REFERENCES taxonomy_node,
        role_raw              text,
        source_surface        text NOT NULL,
        anonymous_draft_id    uuid REFERENCES anonymous_draft,
        captured_at           timestamptz NOT NULL,
        created_at            timestamptz NOT NULL DEFAULT now(),
        CHECK ((status = 'CHOSEN') = (role_taxonomy_node_id IS NOT NULL OR role_raw IS NOT NULL)),
        CHECK (status = 'CHOSEN' OR rank = 1)
    );
    CREATE INDEX desired_role_person_idx ON desired_role (person_id, captured_at);
    CREATE UNIQUE INDEX desired_role_draft_uq ON desired_role (anonymous_draft_id, rank)
        WHERE anonymous_draft_id IS NOT NULL;
    CREATE TRIGGER desired_role_append_only BEFORE UPDATE ON desired_role
        FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
    ALTER TABLE desired_role ENABLE ROW LEVEL SECURITY;

    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({NEW_EVENTS}));

    -- Ids are compared as text: a view never fails on one malformed answer.
    CREATE VIEW analytics.acq_input AS
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

    CREATE VIEW analytics.acq_desired_role AS
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

    CREATE VIEW analytics.acq_unlisted_backlog AS
    WITH typed AS (
        SELECT 'INSTITUTION' AS kind, institution_key AS key, institution_raw AS raw,
               session_hash, created_at
          FROM analytics.acq_input
         WHERE NOT internal AND NOT institution_listed AND institution_raw IS NOT NULL
        UNION ALL
        SELECT 'MAJOR', major_key, major_raw, session_hash, created_at
          FROM analytics.acq_input
         WHERE NOT internal AND NOT major_listed AND major_raw IS NOT NULL
        UNION ALL
        SELECT 'ROLE', role_key, role_raw, session_hash, last_saved_at
          FROM analytics.acq_desired_role
         WHERE NOT internal AND NOT role_listed AND role_raw IS NOT NULL)
    SELECT kind, key, count(DISTINCT session_hash) AS people,
           mode() WITHIN GROUP (ORDER BY raw) AS most_typed,
           array_agg(DISTINCT raw) AS spellings, min(created_at) AS first_seen,
           max(created_at) AS last_seen
    FROM typed WHERE key <> '' GROUP BY kind, key;
    """)


def downgrade() -> None:
    op.execute(f"""
    DROP VIEW analytics.acq_unlisted_backlog;
    DROP VIEW analytics.acq_desired_role;
    DROP VIEW analytics.acq_input;
    DELETE FROM analytics.event WHERE event_name NOT IN ({OLD_EVENTS});
    ALTER TABLE analytics.event DROP CONSTRAINT event_event_name_check;
    ALTER TABLE analytics.event ADD CONSTRAINT event_event_name_check
        CHECK (event_name IN ({OLD_EVENTS}));
    DROP TABLE desired_role;
    DROP FUNCTION name_key(text, text);
    DROP TABLE anonymous_draft_revision;
    ALTER TABLE anonymous_draft DROP COLUMN revision, DROP COLUMN internal;
    """)
