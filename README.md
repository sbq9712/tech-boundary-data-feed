# Tech Boundary Data Feed

Public data feed for Tech Boundary DB. Published packages are indexed by
[`LATEST.json`](LATEST.json) and stored as date ZIPs in [`daily/`](daily/).
The index includes legacy feed-pkg/v1 packages and feed-pkg/v2 change packages.

See [`PROTOCOL.md`](PROTOCOL.md) for the observed format and validation scope.

```sh
python -m unittest discover -s tests -v
python scripts/validate_feed.py .
```
