from sqlalchemy import text
from sqlalchemy.orm import Session


def normalize_document(document_number: str) -> str:
    return "".join(
        character for character in document_number if character.isdigit()
    )


def payer_lock_key(document_number: str) -> str:
    return f"pix-antifraud:payer:{normalize_document(document_number)}"


def lock_payer(session: Session, document_number: str) -> None:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": payer_lock_key(document_number)},
    )
