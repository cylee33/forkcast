import functools
import pathlib
import re

import yaml

PATH = pathlib.Path(__file__).with_name("cuisine_taxonomy.yaml")


@functools.lru_cache
def load() -> dict:
    return yaml.safe_load(PATH.read_text())


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9' ]+", " ", s.lower())


def cuisine_for(name: str, categories: list[str]) -> str | None:
    text = _norm(name) + " " + _norm(" ".join(c.replace("_", " ") for c in categories))
    best = None
    for key, spec in load()["cuisines"].items():
        for alias in spec["aliases"]:
            norm_alias = _norm(alias)
            if re.search(rf"\b{re.escape(norm_alias)}\b", text):
                if best is None or len(norm_alias) > len(best[1]):
                    best = (key, norm_alias)
    return best[0] if best else None


def is_chain(name: str) -> bool:
    n = _norm(name)
    return any(_norm(c) in n for c in load()["chains"])
