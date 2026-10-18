CREATE TABLE IF NOT EXISTS pix_payer_behavior_profile (
    source_document_number           VARCHAR(14) PRIMARY KEY,
    history_snapshot                 BYTEA NOT NULL,
    updated_at                       TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP()
);
