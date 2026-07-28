from enum import Enum

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

    def https_url(self) -> str :
        match self :
            case Apparatus.NP02 : return "https://gitlab.cern.ch/dune-daq/online/np02-configs-operation.git"
            case Apparatus.NP04 : return "https://gitlab.cern.ch/dune-daq/online/np04-configs-operation.git"
            case Apparatus.NP02_EMU : return "https://gitlab.cern.ch/dune-daq/online/np02-emu-configs.git"

        raise ValueError(f"{self.value} is missing the https URL")

