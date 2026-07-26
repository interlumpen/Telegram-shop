class SingletonMeta(type):
    """One instance per class using this metaclass."""

    _instances: dict[type, object] = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]

    def reset_instance(cls) -> None:
        """Forget the cached instance so the next call constructs a fresh one.

        Used by the test suite to swap the Database engine for an in-memory one.
        """
        SingletonMeta._instances.pop(cls, None)
