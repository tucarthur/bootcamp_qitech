CREATE TABLE customers(
    id                              SERIAL PRIMARY KEY,
    customer_key                    CHAR(36) NOT NULL UNIQUE,
    document_number                 CHAR(14) NOT NULL UNIQUE,
    email                           VARCHAR(255) NOT NULL UNIQUE,
    name                            VARCHAR(255) NOT NULL,
    birthdate                       DATE NOT NULL,
    created_at                      TIMESTAMP NOT NULL DEFAULT(NOW())
);

CREATE TABLE account(
    id                              SERIAL PRIMARY KEY,
    account_key                     CHAR(36) NOT NULL UNIQUE,
    customer_id                     INTEGER NOT NULL REFERENCES customers(id),
    balance_cents                   BIGINT NOT NULL DEFAULT 0 CHECK (balance_cents >= 0),
    created_at                      TIMESTAMP NOT NULL DEFAULT(NOW())
);

CREATE TABLE "transaction"(
    id                              SERIAL PRIMARY KEY,
    transaction_key                 CHAR(36) NOT NULL UNIQUE,
    idempotency_key                 VARCHAR(255) NOT NULL UNIQUE,
    "type"                          VARCHAR(20) NOT NULL CHECK ("type" IN ('DEPOSIT', 'WITHDRAWAL', 'TRANSFER')),
    source_account_id               INTEGER REFERENCES account(id),
    destination_account_id          INTEGER REFERENCES account(id),
    amount_cents                    BIGINT NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000000),
    fee_cents                       BIGINT NOT NULL DEFAULT 0 CHECK (fee_cents >= 0),
    created_at                      TIMESTAMP NOT NULL DEFAULT(NOW())
);

CREATE TABLE ledger_entry(
    id                              BIGSERIAL PRIMARY KEY,
    transaction_id                  INTEGER NOT NULL REFERENCES "transaction"(id),
    account_id                      INTEGER NOT NULL REFERENCES account(id),
    direction                       VARCHAR(10) NOT NULL CHECK (direction IN ('DEBIT', 'CREDIT')),
    kind                            VARCHAR(20) NOT NULL CHECK (kind IN ('PRINCIPAL', 'FEE')),
    amount_cents                    BIGINT NOT NULL CHECK (amount_cents > 0),
    balance_after_cents             BIGINT NOT NULL CHECK (balance_after_cents >= 0),
    created_at                      TIMESTAMP NOT NULL DEFAULT(NOW())
);

CREATE INDEX ix_ledger_entry_account_id_id_desc ON ledger_entry (account_id, id DESC);