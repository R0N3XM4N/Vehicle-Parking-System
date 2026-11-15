from flask import request


class DomainError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def wants_json():
    return (
        request.blueprint == "api"
        or request.headers.get("Authorization", "").startswith("Bearer ")
        or request.is_json
        or (request.accept_mimetypes.best == "application/json")
        or request.path.startswith(("/auth/", "/entries", "/slots", "/reservations"))
        or request.path == "/payments"
    )
