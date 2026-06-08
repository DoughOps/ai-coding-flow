import logging

from engines.base import AgentEngine
from engines.aider import AiderEngine
from engines.claudecode import ClaudeCodeEngine
from engines.opencode import OpenCodeEngine

logger = logging.getLogger(__name__)

_ENGINES: dict[str, type[AgentEngine]] = {
    "aider": AiderEngine,
    "claudecode": ClaudeCodeEngine,
    "opencode": OpenCodeEngine,
}


def get_engine(name: str) -> AgentEngine:
    engine_cls = _ENGINES.get(name)
    if engine_cls is None:
        logger.warning("Unknown engine %r — falling back to AiderEngine", name)
        return AiderEngine()
    return engine_cls()
