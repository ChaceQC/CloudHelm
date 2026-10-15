"""Stable public diagnostics, without archive bytes or host paths."""


class ArtifactContentError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
