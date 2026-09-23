"""Delivery and installation coverage check for the KHIND sales flow.

The verdict is made here, in code, from KHIND's fixed coverage lists (source: section 2,
"Khind Service Coverage Area", of khind_acson_knowledge_base.md in the RAG corpus). The
model only extracts the postcode, town and state from the chat and passes them to
advance_purchase_stage.

- All of Peninsular Malaysia is covered.
- Sabah and Sarawak: only the listed towns are covered, so a town is needed.
- W.P. Labuan and places outside Malaysia are not covered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SARAWAK_TOWNS = (
    "Sarikei", "Asajaya", "Miri", "Kuching", "Kota Samarahan", "Balingian Mukah", "Sibu",
    "Siburan", "Sri Aman", "Bau", "Serian", "Bintulu",
)
SABAH_TOWNS = (
    "Kudat", "Papar", "Menumbok", "Ranau", "Tuaran", "Sandakan", "Tambunan", "Kota Kinabalu",
    "Bongawan", "Keningau", "Kuala Penyu", "Lahad Datu", "Tenom", "Penampang",
    "Kota Kinabatangan", "Sook", "Beaufort", "Tawau", "Kundasang", "Tamparuli", "Semporna",
    "Kota Belud", "Kunak", "Telupid", "Beluran", "Membakut", "Kota Marudu", "Sipitang",
)
# Other names customers use for a listed town.
TOWN_ALIASES = {
    "kk": "Kota Kinabalu",
    "samarahan": "Kota Samarahan",
    "mukah": "Balingian Mukah",
    "balingian": "Balingian Mukah",
    "kinabatangan": "Kota Kinabatangan",
}

# Names that place an area in Peninsular Malaysia (states and federal territories).
PENINSULA_NAMES = (
    "semenanjung", "peninsular", "perlis", "kedah", "pulau pinang", "penang", "p pinang",
    "perak", "selangor", "kuala lumpur", "kl", "putrajaya", "negeri sembilan", "n9",
    "n sembilan", "melaka", "malacca", "johor", "johore", "pahang", "terengganu",
    "trengganu", "kelantan",
)
# Places outside Malaysia that customers mention. Any other unknown place is asked about
# again, never handed off.
FOREIGN_NAMES = (
    "singapore", "singapura", "brunei", "indonesia", "thailand", "philippines", "filipina",
    "vietnam", "myanmar", "cambodia", "kemboja", "china", "india", "bangladesh", "australia",
    "japan", "jepun", "korea", "taiwan", "hong kong", "united kingdom", "england",
    "united states", "amerika",
)

REGION_NAMES = {"sabah": "Sabah", "sarawak": "Sarawak"}
_POSTCODE = re.compile(r"\b\d{5}\b")


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


# Words that name a region or state rather than a town ("Kapit, Sarawak" still names Kapit).
_REGION_WORDS = {
    "sabah", "sarawak", "labuan", "wp", "w", "p", "wilayah", "persekutuan", "malaysia",
    "negeri", "darul", "bahagian", "daerah", "bandar",
} | {word for name in PENINSULA_NAMES for word in _tokens(name)}


@dataclass(frozen=True)
class Coverage:
    status: str  # covered | not_covered | need_town | need_state | need_location
    region: str  # peninsula | sabah | sarawak | labuan | foreign | "" (unknown)
    area: str  # place name for the reply, e.g. "Kajang, Selangor"
    location: str  # full place for the handoff note, e.g. "43000 Kajang, Selangor"


def _find(haystack: list[str], name: str) -> bool:
    """True if the words of `name` appear together, as whole words, in `haystack`."""
    needle = _tokens(name)
    return any(haystack[i:i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1))


def _listed_town(words: list[str]) -> tuple[str, str] | None:
    """(region, town) for a covered Sabah or Sarawak town named in `words`."""
    for alias, town in TOWN_ALIASES.items():
        if _find(words, alias):
            return ("sabah" if town in SABAH_TOWNS else "sarawak"), town
    for region, towns in (("sabah", SABAH_TOWNS), ("sarawak", SARAWAK_TOWNS)):
        for town in towns:
            if _find(words, town):
                return region, town
    return None


def _postcode_region(postcode: str) -> str:
    code = int(postcode)
    if 1000 <= code <= 86999:
        return "peninsula"
    if 87000 <= code <= 87999:
        return "labuan"
    if 88000 <= code <= 91999:
        return "sabah"
    if 93000 <= code <= 98999:
        return "sarawak"
    return ""


def _named_region(words: list[str]) -> str:
    if _find(words, "labuan"):
        return "labuan"
    if _find(words, "sabah"):
        return "sabah"
    if _find(words, "sarawak"):
        return "sarawak"
    if any(_find(words, name) for name in PENINSULA_NAMES):
        return "peninsula"
    if any(_find(words, name) for name in FOREIGN_NAMES):
        return "foreign"
    return ""


def _labels(postcode: str, town: str, state: str) -> tuple[str, str]:
    """(area for the reply, full location for the handoff note)."""
    place = town or postcode
    if state and state.lower() not in place.lower():
        place = f"{place}, {state}" if place else state
    full = f"{postcode} {place}" if postcode and postcode not in place else place
    return place, full


def check_coverage(postcode: str = "", town: str = "", state: str = "") -> Coverage:
    """Decide coverage from what the customer said.

    postcode: a 5-digit Malaysian postcode, if given.
    town: the town or area name the customer wrote.
    state: the Malaysian state, or the country if outside Malaysia.
    """
    found = _POSTCODE.search(" ".join((postcode or "", town or "", state or "")))
    postcode = found.group(0) if found else ""
    town = _POSTCODE.sub("", town or "").strip(" ,.")
    state = (state or "").strip(" ,.")
    town_words, state_words = _tokens(town), _tokens(state)

    if "foreign" in (_named_region(town_words), _named_region(state_words)):
        return Coverage("not_covered", "foreign", *_labels("", town, state))

    listed = _listed_town(town_words)
    if listed:
        region, listed_name = listed
        return Coverage("covered", region, *_labels(postcode, listed_name, REGION_NAMES[region]))

    region = (_postcode_region(postcode) if postcode else "") or _named_region(town_words + state_words)
    labels = _labels(postcode, town, state)
    if region == "peninsula":
        return Coverage("covered", region, *labels)
    if region == "labuan":
        return Coverage("not_covered", region, *(labels if labels[0] else ("Labuan", "Labuan")))

    has_town = any(word not in _REGION_WORDS for word in town_words)
    if region in ("sabah", "sarawak"):
        return Coverage("not_covered" if has_town else "need_town", region, *labels)
    return Coverage("need_state" if has_town else "need_location", "", *labels)
