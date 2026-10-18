CREATE TABLE sample_entity_status(
    id		                        SERIAL PRIMARY KEY,
    enumerator                      VARCHAR(50) NOT NULL,
    created_at                      TIMESTAMP NOT NULL DEFAULT(NOW()),
    UNIQUE(enumerator)
);

INSERT INTO sample_entity_status (enumerator) VALUES
('created'),
('pending'),
('success'),
('failed');

CREATE TABLE sample_entity(
    id                              SERIAL PRIMARY KEY,
    sample_entity_key               CHAR(36) NOT NULL,
    status_id                       INTEGER NOT NULL REFERENCES sample_entity_status(id),
    sample_entity_data              JSONB NOT NULL,
    name                            VARCHAR(255) NOT NULL,
    email                           VARCHAR(255) NOT NULL,
    document_number                 CHAR(14) NOT NULL,
    birthdate                       DATE NOT NULL,
    counter                         INTEGER NOT NULL,
    created_at                      TIMESTAMP NOT NULL DEFAULT(NOW()),
    UNIQUE(sample_entity_key),
    UNIQUE(document_number),
    UNIQUE(email)
);

CREATE TABLE sample_entity_status_event(
    id                              SERIAL PRIMARY KEY,
    sample_entity_id                INTEGER NOT NULL REFERENCES sample_entity(id),
    status_id                       INTEGER NOT NULL REFERENCES sample_entity_status(id),
    event_datetime                  TIMESTAMP NOT NULL,
    created_at                      TIMESTAMP NOT NULL DEFAULT(NOW())
);



CREATE TABLE customer ( 
    id SERIAL PRIMARY KEY, 
    customer_key UUID NOT NULL UNIQUE, 
    document_number VARCHAR(11) NOT NULL UNIQUE, 
    email VARCHAR(200) NOT NULL UNIQUE, 
    name VARCHAR(200) NOT NULL, 
    birthdate DATE NOT NULL, 
    created_at TIMESTAMP NOT NULL DEFAULT NOW() 
); 

CREATE TABLE account ( 
    id SERIAL PRIMARY KEY, 
    account_key UUID NOT NULL UNIQUE, 
    customer_id INTEGER NOT NULL, 
    balance_cents BIGINT NOT NULL DEFAULT 0, 
    created_at TIMESTAMP NOT NULL DEFAULT NOW(), 
    CONSTRAINT fk_account_customer 
        FOREIGN KEY (customer_id) 
        REFERENCES customer(id), 
    CONSTRAINT chk_account_balance 
        CHECK (balance_cents >= 0) 
); 

CREATE TABLE bank_transaction ( 
    id SERIAL PRIMARY KEY, 
    transaction_key UUID NOT NULL UNIQUE, 
    idempotency_key VARCHAR(200) NOT NULL UNIQUE, 
    type VARCHAR(20) NOT NULL, 
    source_account_id INTEGER, 
    destination_account_id INTEGER, 
    amount_cents BIGINT NOT NULL, 
    fee_cents BIGINT NOT NULL DEFAULT 0, 
    created_at TIMESTAMP NOT NULL DEFAULT NOW(), 
    CONSTRAINT fk_transaction_source_account 
        FOREIGN KEY (source_account_id) 
        REFERENCES account(id), 
    CONSTRAINT fk_transaction_destination_account 
        FOREIGN KEY (destination_account_id) 
        REFERENCES account(id), 
    CONSTRAINT chk_transaction_type 
        CHECK (type IN ('DEPOSIT', 'WITHDRAWAL', 'TRANSFER')), 
    CONSTRAINT chk_transaction_amount 
        CHECK (amount_cents > 0), 
    CONSTRAINT chk_transaction_fee 
        CHECK (fee_cents >= 0), 
    CONSTRAINT chk_transaction_accounts 
        CHECK ( 
            (type = 'DEPOSIT' 
                AND source_account_id IS NULL 
                AND destination_account_id IS NOT NULL) 
            OR 
            (type = 'WITHDRAWAL' 
                AND source_account_id IS NOT NULL 
                AND destination_account_id IS NULL) 
            OR 
            (type = 'TRANSFER' 
                AND source_account_id IS NOT NULL 
                AND destination_account_id IS NOT NULL 
                AND source_account_id <> destination_account_id) 
        ) 
); 

CREATE TABLE ledger_entry ( 
    id BIGSERIAL PRIMARY KEY, 
    transaction_id INTEGER NOT NULL, 
    account_id INTEGER NOT NULL, 
    direction VARCHAR(10) NOT NULL, 
    kind VARCHAR(20) NOT NULL, 
    amount_cents BIGINT NOT NULL, 
    balance_after_cents BIGINT NOT NULL, 
    created_at TIMESTAMP NOT NULL DEFAULT NOW(), 
    CONSTRAINT fk_ledger_transaction 
        FOREIGN KEY (transaction_id) 
        REFERENCES bank_transaction(id), 
    CONSTRAINT fk_ledger_account 
        FOREIGN KEY (account_id) 
        REFERENCES account(id), 
    CONSTRAINT chk_ledger_direction 
        CHECK (direction IN ('DEBIT', 'CREDIT')), 
    CONSTRAINT chk_ledger_kind 
        CHECK (kind IN ('PRINCIPAL', 'FEE')), 
    CONSTRAINT chk_ledger_amount 
        CHECK (amount_cents > 0), 
    CONSTRAINT chk_ledger_balance 
        CHECK (balance_after_cents >= 0) 
); 

CREATE INDEX idx_ledger_account_id_desc
ON ledger_entry (account_id, id DESC);

CREATE TABLE pix_transaction (
    id                              VARCHAR(200) PRIMARY KEY,
    amount                          BIGINT NOT NULL,
    transaction_date                TIMESTAMPTZ NOT NULL,
    received_at                     TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_account_branch            VARCHAR(20) NOT NULL,
    source_account_number            VARCHAR(50) NOT NULL,
    source_account_opening_date      TIMESTAMPTZ NOT NULL,
    source_document_number           VARCHAR(14) NOT NULL,
    destination_participant          VARCHAR(20) NOT NULL,
    destination_account_branch       VARCHAR(20) NOT NULL,
    destination_account_number       VARCHAR(50) NOT NULL,
    destination_account_opening_date TIMESTAMPTZ NOT NULL,
    destination_document_number      VARCHAR(14) NOT NULL,
    source_device_id                 VARCHAR(200) NOT NULL,
    source_channel                   VARCHAR(50) NOT NULL,
    source_ip                        VARCHAR(45) NOT NULL,
    source_latitude                  NUMERIC(10, 7),
    source_longitude                 NUMERIC(10, 7),
    CONSTRAINT chk_pix_transaction_amount CHECK (amount > 0),
    CONSTRAINT chk_pix_transaction_latitude CHECK (source_latitude BETWEEN -90 AND 90),
    CONSTRAINT chk_pix_transaction_longitude CHECK (source_longitude BETWEEN -180 AND 180)
);

CREATE INDEX idx_pix_transaction_source_account
ON pix_transaction (source_account_branch, source_account_number);

CREATE INDEX idx_pix_transaction_destination_account
ON pix_transaction (destination_participant, destination_account_branch, destination_account_number);

CREATE INDEX idx_pix_transaction_device_id
ON pix_transaction (source_device_id);

CREATE INDEX idx_pix_transaction_source_document_number
ON pix_transaction (source_document_number);

CREATE INDEX idx_pix_transaction_destination_document_number
ON pix_transaction (destination_document_number);

CREATE INDEX idx_pix_transaction_source_ip
ON pix_transaction (source_ip);

CREATE INDEX idx_pix_transaction_source_document_date
ON pix_transaction (source_document_number, transaction_date);

CREATE INDEX idx_pix_transaction_destination_document_date
ON pix_transaction (destination_document_number, transaction_date);

CREATE INDEX idx_pix_transaction_payer_payee
ON pix_transaction (source_document_number, destination_document_number);

CREATE INDEX idx_pix_transaction_device_date
ON pix_transaction (source_device_id, transaction_date);

CREATE INDEX idx_pix_transaction_transaction_date
ON pix_transaction (transaction_date);

CREATE TABLE pix_analysis (
    key                             UUID PRIMARY KEY,
    transaction_id                  VARCHAR(200) NOT NULL UNIQUE
                                        REFERENCES pix_transaction(id),
    status                          VARCHAR(50) NOT NULL,
    metadata                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE pix_account_blacklist (
    source_document_number           VARCHAR(14) PRIMARY KEY,
    triggering_transaction_id        VARCHAR(200) NOT NULL
                                        REFERENCES pix_transaction(id),
    blacklisted_at                   TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    authenticated_at                 TIMESTAMPTZ
);
