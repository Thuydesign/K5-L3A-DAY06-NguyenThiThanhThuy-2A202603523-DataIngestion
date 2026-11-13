"""Download an attributed collection of NASA Science text pages for the lab."""
import hashlib
import json
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CORPUS_DIR = DATA_DIR / "nasa_space_science"
MIN_UNIT_CHARACTERS = 1500

# These are NASA Science reference/fact pages, not third-party mirrors.
SOURCES = [
    ("planet_mercury", "planets", "https://science.nasa.gov/mercury/facts/"),
    ("planet_venus", "planets", "https://science.nasa.gov/venus/venus-facts/"),
    ("planet_earth", "planets", "https://science.nasa.gov/earth/facts/"),
    ("planet_mars", "planets", "https://science.nasa.gov/mars/facts/"),
    ("planet_jupiter", "planets", "https://science.nasa.gov/jupiter/facts/"),
    ("planet_saturn", "planets", "https://science.nasa.gov/saturn/facts/"),
    ("planet_uranus", "planets", "https://science.nasa.gov/uranus/facts/"),
    ("planet_neptune", "planets", "https://science.nasa.gov/neptune/facts/"),
    ("dwarf_planet_ceres", "planets", "https://science.nasa.gov/dwarf-planets/ceres/facts/"),
    ("dwarf_planet_pluto", "planets", "https://science.nasa.gov/dwarf-planets/pluto/facts/"),
    ("solar_system_facts", "solar_system", "https://science.nasa.gov/solar-system/solar-system-facts/"),
    ("planet_definition", "planets", "https://science.nasa.gov/solar-system/planets/what-is-a-planet/"),
    ("kuiper_belt", "solar_system", "https://science.nasa.gov/solar-system/kuiper-belt/"),
    ("oort_cloud", "solar_system", "https://science.nasa.gov/solar-system/oort-cloud/"),
    ("planet_x", "solar_system", "https://science.nasa.gov/solar-system/planet-x/"),
    ("asteroids", "small_bodies", "https://science.nasa.gov/solar-system/asteroids/"),
    ("comets", "small_bodies", "https://science.nasa.gov/solar-system/comets/"),
    ("small_bodies_overview", "small_bodies", "https://science.nasa.gov/asteroids-comets-meteors/"),
    ("moon_composition", "moon", "https://science.nasa.gov/moon/composition/"),
    ("moon_dust", "moon", "https://science.nasa.gov/moon/moon-dust/"),
    ("moon_volcanism", "moon", "https://science.nasa.gov/moon/lunar-volcanism/"),
    ("moon_tides", "moon", "https://science.nasa.gov/moon/tides/"),
    ("moon_phases", "moon", "https://science.nasa.gov/moon/moon-phases/"),
    ("sun_facts", "sun", "https://science.nasa.gov/sun/facts/"),
    ("exoplanet_habitable_zone", "exoplanets", "https://science.nasa.gov/exoplanets/habitable-zone/"),
    ("exoplanet_search", "exoplanets", "https://science.nasa.gov/exoplanets/why-we-search/"),
    ("exoplanet_catalog", "exoplanets", "https://science.nasa.gov/exoplanets/exoplanet-catalog/"),
    ("black_holes", "universe", "https://science.nasa.gov/universe/black-holes/"),
    ("black_hole_anatomy", "universe", "https://science.nasa.gov/universe/black-holes/anatomy/"),
    ("galaxies", "universe", "https://science.nasa.gov/universe/galaxies/"),
    ("galaxy_types", "universe", "https://science.nasa.gov/universe/galaxies/types/"),
    ("stars", "universe", "https://science.nasa.gov/universe/stars/"),
    ("webb_telescope", "missions", "https://science.nasa.gov/mission/webb/"),
    ("hubble_telescope", "missions", "https://science.nasa.gov/mission/hubble/"),
    ("voyager_mission", "missions", "https://science.nasa.gov/mission/voyager/"),
    ("psyche_mission", "missions", "https://science.nasa.gov/mission/psyche/"),
]


class MainTextParser(HTMLParser):
    BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "li", "br", "tr"}
    SKIP_TAGS = {"script", "style", "nav", "footer", "aside", "form"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.main_depth = 0
        self.skip_depth = 0
        self.parts: list[str] = []
        self.in_h1 = False
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "main":
            self.main_depth += 1
        if self.main_depth and tag in self.SKIP_TAGS:
            self.skip_depth += 1
        if self.main_depth and not self.skip_depth and tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        if self.main_depth and not self.skip_depth and tag == "h1":
            self.in_h1 = True

    def handle_endtag(self, tag: str) -> None:
        if self.main_depth and not self.skip_depth and tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "h1":
            self.in_h1 = False
        if self.main_depth and tag in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        if tag == "main" and self.main_depth:
            self.main_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.main_depth and not self.skip_depth:
            self.parts.append(data)
            if self.in_h1:
                self.title_parts.append(data)


def _clean_text(value: str) -> str:
    lines = []
    for raw_line in value.splitlines():
        line = " ".join(raw_line.split())
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return "\n\n".join(lines).strip()


def _download(url: str) -> tuple[str, str]:
    request = Request(
        url,
        headers={"User-Agent": "DataIngestionEngineeringLab/1.0 (educational research)"},
    )
    try:
        with urlopen(request, timeout=45) as response:
            final_url = response.geturl()
            content_type = response.headers.get_content_type()
            body = response.read()
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"Could not download NASA source {url}: {error}") from error
    final_host = urlparse(final_url).hostname or ""
    if final_host != "science.nasa.gov":
        raise ValueError(f"Unexpected redirect outside NASA Science: {url} -> {final_url}")
    if content_type != "text/html":
        raise ValueError(f"Expected an HTML source page at {final_url}, got {content_type}")

    parser = MainTextParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    text = _clean_text("".join(parser.parts))
    title = _clean_text("".join(parser.title_parts))
    if not title or len(text) < MIN_UNIT_CHARACTERS:
        raise ValueError(
            f"NASA source did not yield a title and a {MIN_UNIT_CHARACTERS}-character unit: "
            f"{final_url} (title={title!r}, characters={len(text)})"
        )
    return final_url, f"{title}\n\n{text}"


def main() -> None:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    documents = []
    for source_id, category, url in SOURCES:
        final_url, text = _download(url)
        output_path = CORPUS_DIR / f"{source_id}.txt"
        output_path.write_text(text + "\n", encoding="utf-8")
        title = text.splitlines()[0]
        documents.append(
            {
                "document_id": source_id,
                "title": title,
                "source_path_or_url": final_url,
                "path": output_path.relative_to(DATA_DIR).as_posix(),
                "license_or_permission": (
                    "NASA Science, a U.S. Government source, accessed for this "
                    "noncommercial educational lab. Credit NASA and the linked source. "
                    "NASA notes that third-party material may have separate rights; "
                    "the source page does not state a separate text license, so verify "
                    "redistribution rights before publishing the corpus."
                ),
                "accessed_at": date.today().isoformat(),
                "metadata": {"category": category, "language": "en"},
                "unit_character_count": len(text),
                "snapshot_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )

    manifest_path = DATA_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps({"documents": documents}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Downloaded {len(documents)} NASA Science text units to {CORPUS_DIR}")
    print(f"Manifest: {manifest_path}")
    print(f"Minimum unit length: {min(doc['unit_character_count'] for doc in documents)} characters")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"NASA corpus download failed: {error}", file=sys.stderr)
        raise SystemExit(1)
