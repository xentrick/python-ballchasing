class BallchasingException(Exception):
    """Base exception class"""


class BallchasingResponseError(BallchasingException):
    pass


class MissingAPIKey(BallchasingException):
    pass


class BallchasingFault(BallchasingException):
    pass


class UserFault(BallchasingException):
    pass


class DuplicateReplay(BallchasingException):
    def __init__(self, json: dict | None = None):
        if json is None:
            json = {}

        self.status: int = 409
        self.id: str | None = json.get("id")
        self.location: str | None = json.get("location")
        self.error: str | None = json.get("error")
        super().__init__(f"Duplicate Replay - {self.id} ({self.location})")


class BackoffLimitExceeded(BallchasingException):
    pass
