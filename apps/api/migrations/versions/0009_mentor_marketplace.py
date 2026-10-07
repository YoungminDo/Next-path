"""Mentor marketplace: opt-in profiles, offers, orders, transactions, fees, payouts.

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

OFFER_TYPES = (
    "'QNA','15_MIN_CHAT','30_MIN_MENTORING','60_MIN_MENTORING','PORTFOLIO_REVIEW',"
    "'RESUME_REVIEW','LECTURE','SALON','ACTIVITY','COMPANY_VISIT','PROJECT','OTHER'"
)


def upgrade() -> None:
    op.execute(f"""
    CREATE TABLE mentor_profile (
        mentor_profile_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        person_id         uuid NOT NULL UNIQUE REFERENCES person ON DELETE CASCADE,
        account_id        uuid NOT NULL REFERENCES account,
        status            text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','PAUSED','CLOSED')),
        visibility        text NOT NULL DEFAULT 'MATCH_ONLY' CHECK (visibility IN ('PUBLIC','MATCH_ONLY')),
        opted_in_at       timestamptz NOT NULL DEFAULT now(),
        headline          text,
        bio               text,
        is_accepting      boolean NOT NULL DEFAULT true,
        rating_avg        numeric(3,2) CHECK (rating_avg BETWEEN 1 AND 5),
        rating_count      integer NOT NULL DEFAULT 0,
        response_rate     numeric(4,3) CHECK (response_rate BETWEEN 0 AND 1),
        completed_count   integer NOT NULL DEFAULT 0,
        created_at        timestamptz NOT NULL DEFAULT now(),
        updated_at        timestamptz NOT NULL DEFAULT now()
    );
    CREATE TRIGGER mentor_profile_updated_at BEFORE UPDATE ON mentor_profile
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    ALTER TABLE decision_event ADD CONSTRAINT decision_event_mentor_fk
        FOREIGN KEY (helped_by_mentor_profile_id) REFERENCES mentor_profile ON DELETE SET NULL;

    CREATE TABLE mentor_offer (
        offer_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        mentor_profile_id uuid NOT NULL REFERENCES mentor_profile ON DELETE CASCADE,
        offer_type        text NOT NULL CHECK (offer_type IN ({OFFER_TYPES})),
        title             text NOT NULL,
        description       text,
        duration_minutes  integer CHECK (duration_minutes > 0),
        price_my          integer CHECK (price_my >= 0),
        price_krw         integer CHECK (price_krw >= 0),
        status            text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','PAUSED','CLOSED')),
        created_at        timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX mentor_offer_profile_idx ON mentor_offer (mentor_profile_id, status);

    CREATE TABLE orders (
        order_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        buyer_account_id uuid NOT NULL REFERENCES account,
        offer_id         uuid NOT NULL REFERENCES mentor_offer,
        status           text NOT NULL CHECK (status IN
                             ('CREATED','PAID','ACCEPTED','COMPLETED','CANCELLED','REFUNDED')),
        question_text    text,
        price_my         integer,
        price_krw        integer,
        idempotency_key  text NOT NULL UNIQUE,
        created_at       timestamptz NOT NULL DEFAULT now(),
        updated_at       timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX orders_buyer_idx ON orders (buyer_account_id, created_at);
    CREATE TRIGGER orders_updated_at BEFORE UPDATE ON orders
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    CREATE TABLE transaction (
        transaction_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        order_id       uuid NOT NULL REFERENCES orders,
        kind           text NOT NULL CHECK (kind IN ('CHARGE','REFUND')),
        method         text NOT NULL CHECK (method IN ('MY_CREDIT','PG')),
        provider       text,
        provider_ref   text,
        amount_my      integer,
        amount_krw     integer,
        ledger_id      uuid REFERENCES credit_ledger,
        status         text NOT NULL CHECK (status IN ('PENDING','SUCCEEDED','FAILED')),
        created_at     timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE platform_fee (
        platform_fee_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        transaction_id  uuid NOT NULL UNIQUE REFERENCES transaction,
        fee_rate        numeric(5,4) NOT NULL CHECK (fee_rate BETWEEN 0 AND 1),
        amount_my       integer,
        amount_krw      integer,
        created_at      timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE payout (
        payout_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        mentor_profile_id uuid NOT NULL REFERENCES mentor_profile,
        amount_krw        integer NOT NULL CHECK (amount_krw >= 0),
        period_start      date NOT NULL,
        period_end        date NOT NULL,
        status            text NOT NULL CHECK (status IN ('PENDING','PAID','FAILED')),
        created_at        timestamptz NOT NULL DEFAULT now(),
        paid_at           timestamptz
    );
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE payout;
    DROP TABLE platform_fee;
    DROP TABLE transaction;
    DROP TABLE orders;
    DROP TABLE mentor_offer;
    ALTER TABLE decision_event DROP CONSTRAINT decision_event_mentor_fk;
    DROP TABLE mentor_profile;
    """)
