"""Convert the gateway.records rows earlier writers stored, once (task 2b-repair-4 F2).

    python -m research_gateway.registry.migrate           # convert them; exit 0 once none is left
    python -m research_gateway.registry.migrate --check   # count them; exit 1 while any is left

A row is current (`restriction_inputs` true) when the members a reader derives its permissions
from carry the source's own statements about them (core/canonical.py MEMBER_RESTRICTIONS): in
its canonical provenance (the cache's writer) or, with none there, in its record_sources rows
(the harvest's writer: a registry states a content licence and nothing more). Earlier writers
left their rows false:
  * gen-1's cache writer kept each member's citation fields only (before it, no members at all:
    record_sources held them). The LEAD member's statements are the record's own fields
    (dedup.cluster copies the lead record; a merge never sets them);
  * task 2b's kept each member's four permission facts, not the statements behind them;
  * the harvest loader, before this task, never set the marker.
Each row is rewritten from what it holds, each member keeping its own restrictions and none
spreading to another: the lead's statements onto the lead member (added from the record's own
identity when the row keeps none for it); `redistribution: prohibited` as `redistributable:
false`, its one cause in task 2b's licences.content_redistribution; `access: personal_use` that
no kept statement explains as `inferred_personal_use`: the stored facts show THAT the member was
personal use, not why (its source's verdict then, or third-party terms), so the restriction is
kept as inferred from legacy data, never as a statement of its source. A statement a member
already carries wins. A row with no members of its own and no lead statement is only marked:
its record_sources rows are its members, and hold all it knows.

Bounded and idempotent: one pass over the rows unconverted when it starts, each converted and
marked by one UPDATE, BATCH rows per commit; a converted row is never selected again, so a
rerun converts nothing. Done is `unconverted() == 0`, which the run reports and every cache
checks before it opens (core/cache.py). A row an older gateway writes meanwhile is left for
the next run: stop older gateways first. On a real database this is a release step the
operator approves; nothing runs it implicitly.
"""
from __future__ import annotations

import argparse
import json
import sys

from ..core import db
from ..core.cache import UNCONVERTED, stored_members
from ..core.canonical import MEMBER_RESTRICTIONS, member_summary

BATCH = 500


def converted(canonical: dict, stored: list[dict]) -> dict:
    """`canonical` in the current representation; `stored`: its record_sources rows as members,
    used when it keeps no members of its own."""
    lead = {k: canonical[k] for k in MEMBER_RESTRICTIONS if isinstance(canonical.get(k), bool)}
    members = [dict(m) for m in canonical.get("provenance") or [] if isinstance(m, dict)]
    if not members:
        if not lead:
            return canonical
        members = stored
    at = next((i for i, m in enumerate(members) if m.get("source_id") == canonical.get("source_id")), None)
    if at is None:
        members.insert(0, {"source_id": canonical.get("source_id"), "identity": canonical.get("identity")})
        at = 0
    members[at] = {**lead, **members[at]}
    for i, m in enumerate(members):
        facts = m.get("permissions") if isinstance(m.get("permissions"), dict) else {}
        derived = {"redistributable": False} if facts.get("redistribution") == "prohibited" else {}
        if facts.get("access") == "personal_use" and m.get("third_party_restricted") is not True:
            derived["inferred_personal_use"] = True
        members[i] = {**derived, **m}
    return {**canonical, "provenance": [member_summary(m) for m in members]}


def unconverted(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(UNCONVERTED)
        left = cur.fetchone()[0]
    conn.commit()
    return left


def migrate(conn, *, batch: int = BATCH) -> int:
    """Convert every row unconverted when it starts; returns how many it converted."""
    with conn.cursor() as cur:
        cur.execute("SELECT identity FROM gateway.records WHERE NOT restriction_inputs ORDER BY identity")
        pending = [r[0] for r in cur.fetchall()]
    conn.commit()
    done = 0
    for start in range(0, len(pending), batch):
        with conn.cursor() as cur:
            cur.execute("SELECT identity, canonical FROM gateway.records WHERE identity = ANY(%s) AND NOT restriction_inputs "
                        "ORDER BY identity FOR UPDATE", (pending[start:start + batch],))
            for identity, canonical in cur.fetchall():
                stored = [] if canonical.get("provenance") else stored_members(cur, identity)
                cur.execute("UPDATE gateway.records SET canonical = %s, restriction_inputs = true WHERE identity = %s",
                            (json.dumps(converted(canonical, stored), default=str), identity))
                done += 1
        conn.commit()
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="count the rows left to convert, converting none")
    args = ap.parse_args(argv)
    with db.connect() as conn:
        done = 0 if args.check else migrate(conn)
        left = unconverted(conn)
    print(f"converted {done} stored records; {left} left to convert")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
