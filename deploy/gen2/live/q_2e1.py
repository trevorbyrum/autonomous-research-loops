"""V7 §5 / v6 §14.1: baked only into the offline gateway's adapters package."""
from ..core import schema as S
from ..core.canonical import make_record
from .base import AdapterError, check, decode, members

SOURCE_ID, CAPABILITIES = "q_2e1", ("find",)
FIND = S.obj({"records": S.required(S.members(S.obj({"id": S.required(S.key()), "title": S.required(S.text())}))),
              "total": S.required(S.whole())})
SCHEMAS = {"find": FIND}


def find(client, query, *, limit=1, page=1):
    if (query, limit, page) != ("2e1-q-positive", 1, 1):
        raise AdapterError("finite fixture query only")
    reply = client.get(SOURCE_ID, "find", "http://172.31.251.3:18081/fixture", query=query)
    check(SOURCE_ID, reply, allow_404=False)
    decoded = decode(SOURCE_ID, FIND, reply)
    def record(row):
        if row["id"] != "q1" or row["title"] != "2e1 fixture":
            raise AdapterError("fixture record differs")
        return make_record(identity="q_2e1:q1", kind="article", source_id=SOURCE_ID,
                           title=row["title"], authors=[], identifiers={}, links=[], license="CC0", raw=row.raw)
    records = members(SOURCE_ID, decoded["records"], record)
    if decoded["total"] != 1 or len(records) != 1 or records[0] is None:
        raise AdapterError("fixture cardinality")
    return {"records": records, "total": 1, "exhausted": True, "next_page": None}
