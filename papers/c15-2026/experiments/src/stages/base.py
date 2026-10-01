from abc import ABC, abstractmethod


class Stage(ABC):
    name: str
    seccion_paper: str
    output_dir: str

    @abstractmethod
    def is_done(self) -> bool:
        """True si el output ya existe en disco. Si retorna True, main.py hace skip (no recomputa)."""
        ...

    @abstractmethod
    def run(self) -> dict:
        """Ejecuta el análisis. Retorna un dict que se guarda como manifest JSON y se indexa."""
        ...
