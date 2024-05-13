

class BallchasingException(Exception):
    """Base exception class"""
    pass

class MissingAPIKey(BallchasingException):
    pass

class BallchasingFault(BallchasingException):
    pass

class UserFault(BallchasingException):
    pass

class DuplicateReplay(BallchasingException):
    pass