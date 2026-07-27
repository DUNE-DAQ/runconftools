class Apparatus(Enum):
    NP02 = "np02"
    NP04 = "np04"
    NP02_EMU = "np02-emu"

    def __str__(self):
        return self.value

    @classmethod
    def from_string(cls, s: str) -> "Apparatus":
        try:
            return cls(s)
        except ValueError:
            raise ValueError(f"{s!r} is not a valid {cls.__name__}")

    @classmethod
    def values(cls) -> list[str]:
        return [c.value for c in cls]

