from uuid import UUID, uuid4

from django.core.exceptions import ValidationError


def new_key() -> str:
    """二重送信を防ぐキー。フォームを表示するたびに作る（architecture.md 5.4）。"""
    return str(uuid4())


def posted_key(request) -> UUID | None:
    try:
        return UUID(request.POST.get("idempotency_key", ""))
    except ValueError:
        return None


def add_service_error(form, error: ValidationError) -> None:
    for message in error.messages:
        form.add_error(None, message)
