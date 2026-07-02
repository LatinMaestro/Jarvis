import re


PREFERRED_PLAYERS = [
    "Andrecinho10",
    "Fandangleberry",
    "bLindDisc",
    "AncientChunk",
    "Rhyscomes69",
    "LatinMaestro",
    "NevSONIC",
    "Nev Pounder",
    "Nuffmans",
    "Nev_blade7",
    "Quake_",
    "barber_sturgeo",
    "Maarrvvnn",
    "Hayd4n",
    "xX_Harold_Xx",
]


def norm_key(name: str) -> str:
    return re.sub(r"[\s\._]+", "", (name or "").strip().lower())


_CANONICAL_PLAYERS = {norm_key(player): player for player in PREFERRED_PLAYERS}
_CANONICAL_PLAYERS[norm_key("Nuffman")] = "Nuffmans"


def norm_simple(name: str) -> str:
    """Return a stable lowercase alphanumeric player key."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").strip().lower())


def canonical_player_name(name: str) -> str:
    return _CANONICAL_PLAYERS.get(norm_key(name), name)
