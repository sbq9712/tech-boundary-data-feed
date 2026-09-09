# Tech Boundary Data Feed

This public repository contains only the experimental Feed format documentation,
schemas, and fully synthetic test packages used to exercise a consumer.

## Safety and scope

- All current records are fictional test data.
- `tech-boundary-synthetic` / `test-v0` are test identities, not production.
- This repository contains no private application code, credentials, user data,
  uploaded material, private prompts, internal analysis, or production feed data.
- Payload files are inert JSON Lines data. A consumer must never execute content
  from this repository as code, SQL, or scripts.

## Synthetic sequence

The fixture lives at [`feeds/tech-boundary-synthetic/test-v0/`](feeds/tech-boundary-synthetic/test-v0/):

1. `synthetic-001`: add A revision 1 and B revision 1.
2. `synthetic-002`: update A to revision 2, delete B, and add C revision 1.

See [`PROTOCOL.md`](PROTOCOL.md) for the package contract. The raw-file layout
is an **experimental transport fixture**, not a final production transport
decision. Git files and GitHub Releases can be changed independently of the
Feed protocol.

Every pull request is checked by the repository's read-only, standard-library
validator. It verifies package bytes and continuity without secrets and never
executes payload content:

```bash
python scripts/validate_feed.py .
```
