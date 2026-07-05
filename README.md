# Sports Image Harvester

Automatically downloads and stores images of sports figures that are **released
free for public use**, sourced from [Wikimedia Commons](https://commons.wikimedia.org).

Current targets (see `config.json`): Wimbledon tennis figures (Alexandra Eala,
Iga Swiatek, Alcaraz, Sinner, …) and World Cup 2026 stars (Messi, Mbappé,
Yamal, Bellingham, …).

## How it works

- `harvest.py` searches Wikimedia Commons for each athlete in `config.json`.
- Only files under **Public Domain, CC0, CC BY, or CC BY-SA** licenses are kept.
  Anything Non-Commercial (NC), No-Derivatives (ND), or unlicensed is rejected.
- Images land in `images/<athlete_slug>/`; every file is recorded in
  `manifest.json` with license, artist, credit, source page, and hashes.
- A GitHub Actions workflow re-runs the harvest **every Monday 03:00 UTC**
  (or on demand via *Run workflow*) and commits anything new.

## Usage

```bash
python harvest.py                          # harvest everyone in config.json
python harvest.py --athlete "Alexandra Eala"
python harvest.py --limit 3                # cap new downloads per athlete
```

No dependencies — Python 3.10+ stdlib only.

## License compliance — read before reusing images

1. **Attribution**: CC BY and CC BY-SA require crediting the photographer.
   Use the `artist`, `license`, and `commons_page` fields in `manifest.json`.
2. **Share-alike**: derivatives of CC BY-SA images must carry the same license.
3. **Personality rights**: a free *copyright* license does not waive an
   athlete's publicity/personality rights. Editorial use is generally fine;
   commercial use of a person's likeness (ads, merch, thumbnails implying
   endorsement) may require separate clearance regardless of image license.

The code in this repository is MIT licensed. The images are governed by their
individual licenses listed in `manifest.json`.
