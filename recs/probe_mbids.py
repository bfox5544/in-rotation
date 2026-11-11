"""Find out which kind of MusicBrainz ID the dataset's mbid column holds.

    python -m recs.probe_mbids --albums data/model/albums.parquet --contact you@example.com

Looks up a small random sample (default 20) as release-group, then release, then
recording, at under one request per second with your contact in the User-Agent, as
MusicBrainz requires. Needs internet access and costs at most 3 requests per ID.
"""
from __future__ import annotations

import argparse
import collections
import time
import urllib.error
import urllib.request
from collections.abc import Callable

KINDS = ("release-group", "release", "recording")


def classify(mbid: str, fetch: Callable[[str, str], int]) -> str:
    for kind in KINDS:
        if fetch(kind, mbid) == 200:
            return kind
    return "unknown"


def make_fetch(contact: str, delay: float = 1.1) -> Callable[[str, str], int]:
    agent = f"InRotationProbe/0.1 ({contact})"

    def fetch(kind: str, mbid: str) -> int:
        time.sleep(delay)
        req = urllib.request.Request(f"https://musicbrainz.org/ws/2/{kind}/{mbid}?fmt=json", headers={"User-Agent": agent})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404
            raise

    return fetch


def main() -> None:
    import pandas as pd

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--albums", required=True)
    p.add_argument("--contact", required=True, help="email or URL for the User-Agent")
    p.add_argument("--sample", type=int, default=20)
    a = p.parse_args()
    ids = pd.read_parquet(a.albums)["mbid"].dropna()
    sample = ids.sample(min(a.sample, len(ids)), random_state=1).tolist()
    fetch = make_fetch(a.contact)
    counts = collections.Counter(classify(m, fetch) for m in sample)
    print(dict(counts), f"out of {len(sample)} sampled IDs")


if __name__ == "__main__":
    main()
