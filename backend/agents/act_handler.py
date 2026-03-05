"""
Shared Nova Act exception handling for all agents.
Agents catch exceptions in their own search() and pass the exception to
ActExceptionHandler.handle(); the handler inspects the exception type and
returns the appropriate result (e.g. empty list) after logging.
"""

from typing import Any

from nova_act import ActAgentError

from logger import get_logger

log = get_logger(__name__)


class ActExceptionHandler:
    """
    Central handler for Nova Act agent exceptions. Agents do not run search
    logic here; they catch exceptions in their class and pass the exception
    to handle() to log and get the return value (e.g. empty list).
    """

    @staticmethod
    def handle(exc: Exception, agent_name: str, context: dict[str, Any]) -> list[dict]:
        """
        Inspect the exception type and take action: log appropriately, then
        return the value the agent should return (e.g. empty list).

        Parameters
        ----------
        exc : Exception
            The exception raised during agent search.
        agent_name : str
            Display name for logging (e.g. "Cleartrip", "Goibibo").
        context : dict
            Context for log messages (e.g. {"from": "Delhi", "to": "Mumbai", "date": "2026-03-10"}).

        Returns
        -------
        list[dict]
            Empty list so the agent can return gracefully; extend this later
            if you need to return partial results for specific exception types.
        """
        if isinstance(exc, ActAgentError):
            steps = getattr(getattr(exc, "metadata", None), "num_steps_executed", None)
            log.warning(
                "%s agent error %s: %s (steps=%s) — returning 0 results",
                agent_name,
                context,
                type(exc).__name__,
                steps,
            )
            return []
        log.error("%s search failed %s: %s", agent_name, context, exc)
        return []
