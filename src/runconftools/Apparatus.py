from enum import Enum

class Apparatus(Enum):
    NP02 = "np02"
    NP04 = "np04"
    NP02_EMU = "np02_emu"
    NP04_EMU = "np04_emu"

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
            case Apparatus.NP04_EMU : return "https://gitlab.cern.ch/dune-daq/online/np04-emu-configs.git"

        raise ValueError(f"{self.value} is missing the https URL")

    def ssh_url(self) -> str :
        match self :
            case Apparatus.NP02 : return "ssh://git@gitlab.cern.ch:7999/dune-daq/online/np02-configs-operation.git" 
            case Apparatus.NP04 : return "ssh://git@gitlab.cern.ch:7999/dune-daq/online/np04-configs-operation.git" 
            case Apparatus.NP02_EMU : return "ssh://git@gitlab.cern.ch:7999/dune-daq/online/np02-emu-configs.git"
            case Apparatus.NP04_EMU : return "ssh://git@gitlab.cern.ch:7999/dune-daq/online/np04-emu-configs.git"

        raise ValueError(f"{self.value} is missing the ssh URL")

