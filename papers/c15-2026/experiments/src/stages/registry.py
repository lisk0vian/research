_REGISTRY: dict = {}


def register_stage(cls):
    """Register each Stage class in a global dict by its `name` attribute."""
    if cls.name in _REGISTRY:
        raise ValueError(f"duplicate Stage name '{cls.name}': {_REGISTRY[cls.name]} vs {cls}")
    _REGISTRY[cls.name] = cls
    return cls


def get_registry() -> dict:
    """Retorna todas las stages registradas."""
    return dict(_REGISTRY)
