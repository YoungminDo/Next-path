"""v1.4 generic versioned taxonomy: unlimited-depth nodes, aliases, version crosswalk,
presentation depth per product surface.

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

TYPES = "'ROLE','INDUSTRY','MAJOR'"
STATUS = "'DRAFT','ACTIVE','RETIRED'"


def upgrade() -> None:
    op.execute(f"""
    -- Label normalization shared by the importer and alias lookups (one definition only).
    CREATE FUNCTION normalize_label(t text) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
        SELECT lower(regexp_replace(coalesce(t, ''), '[[:space:]·・,./()\\[\\]_&+-]+', '', 'g'))
    $$;

    CREATE TABLE taxonomy (
        taxonomy_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        taxonomy_type text NOT NULL CHECK (taxonomy_type IN ({TYPES})),
        name          text NOT NULL,
        version       text NOT NULL,
        status        text NOT NULL CHECK (status IN ({STATUS})),
        valid_from    date,
        valid_to      date,
        created_at    timestamptz NOT NULL DEFAULT now(),
        UNIQUE (taxonomy_type, version),
        CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from)
    );
    CREATE UNIQUE INDEX taxonomy_one_active_uq ON taxonomy (taxonomy_type) WHERE status = 'ACTIVE';

    -- Adjacency list; depth is derived from the parent on insert. Parents never change in place:
    -- restructuring is a new taxonomy version plus taxonomy_mapping rows.
    CREATE TABLE taxonomy_node (
        taxonomy_node_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        taxonomy_id      uuid NOT NULL REFERENCES taxonomy ON DELETE CASCADE,
        parent_node_id   uuid REFERENCES taxonomy_node,
        code             text NOT NULL,
        canonical_name   text NOT NULL,
        display_name     text NOT NULL,
        depth            smallint NOT NULL CHECK (depth >= 1),
        sort_order       integer NOT NULL DEFAULT 0,
        status           text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ({STATUS})),
        valid_from       date,
        valid_to         date,
        metadata         jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        created_at       timestamptz NOT NULL DEFAULT now(),
        updated_at       timestamptz NOT NULL DEFAULT now(),
        UNIQUE (taxonomy_id, code),
        CHECK (parent_node_id IS NULL OR parent_node_id <> taxonomy_node_id)
    );
    CREATE INDEX taxonomy_node_parent_idx ON taxonomy_node (parent_node_id);
    CREATE INDEX taxonomy_node_depth_idx ON taxonomy_node (taxonomy_id, depth);

    CREATE FUNCTION taxonomy_node_tree_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE parent record;
    BEGIN
        IF TG_OP = 'UPDATE' AND NEW.parent_node_id IS DISTINCT FROM OLD.parent_node_id THEN
            RAISE EXCEPTION 'taxonomy_node parent is immutable; publish a new taxonomy version'
                USING ERRCODE = 'restrict_violation';
        END IF;
        IF TG_OP = 'UPDATE' AND NEW.taxonomy_id <> OLD.taxonomy_id THEN
            RAISE EXCEPTION 'taxonomy_node cannot move between taxonomies'
                USING ERRCODE = 'restrict_violation';
        END IF;
        IF NEW.parent_node_id IS NULL THEN
            NEW.depth := 1;
        ELSE
            SELECT taxonomy_id, depth INTO parent FROM taxonomy_node
             WHERE taxonomy_node_id = NEW.parent_node_id;
            IF parent.taxonomy_id <> NEW.taxonomy_id THEN
                RAISE EXCEPTION 'parent node belongs to another taxonomy'
                    USING ERRCODE = 'check_violation';
            END IF;
            NEW.depth := parent.depth + 1;
        END IF;
        NEW.updated_at := now();
        RETURN NEW;
    END $$;
    CREATE TRIGGER taxonomy_node_tree BEFORE INSERT OR UPDATE ON taxonomy_node
        FOR EACH ROW EXECUTE FUNCTION taxonomy_node_tree_guard();

    -- Renames/status changes keep history; nothing is renamed destructively.
    CREATE TABLE taxonomy_node_history (
        history_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        taxonomy_node_id uuid NOT NULL REFERENCES taxonomy_node ON DELETE CASCADE,
        canonical_name   text NOT NULL,
        display_name     text NOT NULL,
        status           text NOT NULL,
        valid_until      timestamptz NOT NULL DEFAULT now()
    );
    CREATE FUNCTION taxonomy_node_keep_history() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF (NEW.canonical_name, NEW.display_name, NEW.status)
           IS DISTINCT FROM (OLD.canonical_name, OLD.display_name, OLD.status) THEN
            INSERT INTO taxonomy_node_history (taxonomy_node_id, canonical_name, display_name, status)
            VALUES (OLD.taxonomy_node_id, OLD.canonical_name, OLD.display_name, OLD.status);
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER taxonomy_node_history_log AFTER UPDATE ON taxonomy_node
        FOR EACH ROW EXECUTE FUNCTION taxonomy_node_keep_history();

    CREATE TABLE taxonomy_alias (
        alias_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        taxonomy_node_id uuid NOT NULL REFERENCES taxonomy_node ON DELETE CASCADE,
        alias_text       text NOT NULL,
        normalized_alias text GENERATED ALWAYS AS (normalize_label(alias_text)) STORED,
        source_type      text,
        locale           text NOT NULL DEFAULT 'ko',
        status           text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ({STATUS})),
        created_at       timestamptz NOT NULL DEFAULT now(),
        UNIQUE (taxonomy_node_id, alias_text, locale)
    );
    CREATE INDEX taxonomy_alias_lookup_idx ON taxonomy_alias (normalized_alias);

    CREATE TABLE taxonomy_mapping (
        mapping_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        from_node_id   uuid NOT NULL REFERENCES taxonomy_node,
        to_node_id     uuid NOT NULL REFERENCES taxonomy_node,
        mapping_type   text NOT NULL CHECK (mapping_type IN
                           ('SAME','RENAME','SPLIT','MERGE','MOVE','PARTIAL','RETIRED')),
        quality        numeric(4,3) CHECK (quality BETWEEN 0 AND 1),
        effective_from date,
        effective_to   date,
        review_status  text NOT NULL DEFAULT 'PENDING'
                           CHECK (review_status IN ('PENDING','APPROVED','REJECTED')),
        created_at     timestamptz NOT NULL DEFAULT now(),
        UNIQUE (from_node_id, to_node_id)
    );

    -- Presentation depth per product surface (depth 1 = top level). Data, not code.
    CREATE TABLE product_taxonomy_view (
        view_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        surface_code   text NOT NULL,
        taxonomy_type  text NOT NULL CHECK (taxonomy_type IN ({TYPES})),
        taxonomy_id    uuid REFERENCES taxonomy,   -- NULL = whichever version is ACTIVE
        default_depth  smallint NOT NULL,
        min_depth      smallint NOT NULL,
        max_depth      smallint NOT NULL,
        effective_from timestamptz NOT NULL DEFAULT now(),
        effective_to   timestamptz,
        status         text NOT NULL CHECK (status IN ({STATUS})),
        created_at     timestamptz NOT NULL DEFAULT now(),
        CHECK (1 <= min_depth AND min_depth <= default_depth AND default_depth <= max_depth)
    );
    CREATE UNIQUE INDEX product_taxonomy_view_active_uq
        ON product_taxonomy_view (surface_code, taxonomy_type) WHERE status = 'ACTIVE';
    INSERT INTO product_taxonomy_view (surface_code, taxonomy_type, default_depth, min_depth,
                                       max_depth, status)
    VALUES ('ACQUISITION', 'ROLE', 2, 1, 3, 'ACTIVE'),
           ('ACQUISITION', 'INDUSTRY', 2, 1, 3, 'ACTIVE'),
           ('ACQUISITION', 'MAJOR', 2, 1, 3, 'ACTIVE');

    -- Ancestor at a given depth (node itself when already at/above that depth).
    CREATE FUNCTION taxonomy_ancestor_at_depth(p_node uuid, p_depth integer) RETURNS uuid
        LANGUAGE sql STABLE AS $$
        WITH RECURSIVE up AS (
            SELECT taxonomy_node_id, parent_node_id, depth FROM taxonomy_node
             WHERE taxonomy_node_id = p_node
            UNION ALL
            SELECT n.taxonomy_node_id, n.parent_node_id, n.depth
              FROM taxonomy_node n JOIN up ON n.taxonomy_node_id = up.parent_node_id
             WHERE up.depth > p_depth
        )
        SELECT taxonomy_node_id FROM up ORDER BY depth ASC
         LIMIT 1
    $$;

    -- Node plus all descendants (subtree filter: "major = 경영·경제" matches 경영학 too).
    CREATE FUNCTION taxonomy_subtree(p_node uuid) RETURNS SETOF uuid
        LANGUAGE sql STABLE AS $$
        WITH RECURSIVE down AS (
            SELECT taxonomy_node_id FROM taxonomy_node WHERE taxonomy_node_id = p_node
            UNION ALL
            SELECT n.taxonomy_node_id FROM taxonomy_node n
              JOIN down ON n.parent_node_id = down.taxonomy_node_id
        )
        SELECT taxonomy_node_id FROM down
    $$;

    -- Guard for FK columns that must point at a node of a specific taxonomy type.
    -- Usage: EXECUTE FUNCTION assert_taxonomy_type('<column>', '<TYPE>')
    CREATE FUNCTION assert_taxonomy_type() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE node uuid; actual text;
    BEGIN
        node := (to_jsonb(NEW) ->> TG_ARGV[0])::uuid;
        IF node IS NOT NULL THEN
            SELECT t.taxonomy_type INTO actual FROM taxonomy_node n JOIN taxonomy t USING (taxonomy_id)
             WHERE n.taxonomy_node_id = node;
            IF actual IS DISTINCT FROM TG_ARGV[1] THEN
                RAISE EXCEPTION '%.% must reference a % node (got %)', TG_TABLE_NAME, TG_ARGV[0],
                    TG_ARGV[1], actual USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END $$;
    """)


def downgrade() -> None:
    op.execute("""
    DROP FUNCTION assert_taxonomy_type();
    DROP FUNCTION taxonomy_subtree(uuid);
    DROP FUNCTION taxonomy_ancestor_at_depth(uuid, integer);
    DROP TABLE product_taxonomy_view;
    DROP TABLE taxonomy_mapping;
    DROP TABLE taxonomy_alias;
    DROP TABLE taxonomy_node_history;
    DROP TABLE taxonomy_node;
    DROP FUNCTION taxonomy_node_keep_history();
    DROP FUNCTION taxonomy_node_tree_guard();
    DROP TABLE taxonomy;
    DROP FUNCTION normalize_label(text);
    """)
