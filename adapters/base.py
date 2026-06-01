from abc import ABC, abstractmethod


class ContentAdapter(ABC):
    @abstractmethod
    def fetch(self) -> list[dict]:
        ...

    @abstractmethod
    def source_name(self) -> str:
        ...

    def ping(self) -> bool:
        """Lightweight health check without fetching data."""
        return True