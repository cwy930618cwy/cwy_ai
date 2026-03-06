class AgentFlowError(Exception):
    """Base exception for AgentFlow"""


class NotFoundError(AgentFlowError):
    pass


class AlreadyExistsError(AgentFlowError):
    pass


class InvalidParamError(AgentFlowError):
    pass


class InternalServerError(AgentFlowError):
    pass


class LockAcquireFailedError(AgentFlowError):
    pass


class LockNotHeldError(AgentFlowError):
    pass


class LockExpiredError(AgentFlowError):
    pass


class TaskAlreadyClaimedError(AgentFlowError):
    pass


class TaskNotAvailableError(AgentFlowError):
    pass


class TaskNotClaimedError(AgentFlowError):
    pass


class DependencyNotMetError(AgentFlowError):
    pass


class ExperienceRejectedError(AgentFlowError):
    pass


class EvolutionLimitReachedError(AgentFlowError):
    pass


class EvolutionSafetyBlockError(AgentFlowError):
    pass
