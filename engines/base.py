from abc import ABC, abstractmethod
from pathlib import Path

from config import Settings


class AgentEngine(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def run(self, repo_path: Path, prompt: str, settings: Settings) -> str:
        """Run the engine against the repo. Returns stdout+stderr output."""
        ...
