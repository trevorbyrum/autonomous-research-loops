"""Shared fixtures for the gen-2 store DDL tests (not collected as tests).

Every connection applies gen2/store/connection.sql — the integrity-bearing
per-connection pragmas (foreign_keys, recursive_triggers) — before the DDL,
exactly as the store module must (INVARIANTS C-11).

DDL_TEXT and CONNECTION_TEXT are module globals so that the mutation harness
(tools/gen2_mutations.py) can substitute a mutated schema in memory and rerun
the same tests; nothing else should reassign them.

Builders construct input rows only. Expected accept/reject outcomes are
written by hand in each test, never derived from the DDL under test.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import unittest
from pathlib import Path

STORE_DIR = Path(__file__).resolve().parents[1] / "store"
DDL_TEXT = (STORE_DIR / "schema.sql").read_text(encoding="utf-8")
CONNECTION_TEXT = (STORE_DIR / "connection.sql").read_text(encoding="utf-8")

T = "2026-09-25T12:00:00Z"
TOPIC = "fleet-a:t1"
OTHER = "fleet-a:t2"

# The one subject kind each operator-decision kind admits (hand-copied from
# the A2 rule, so builders can default it; tests that probe the rule pass
# subject_kind explicitly).
SUBJECT_KIND = {
    "brief_confirmation": "intake_brief", "scope_approval": "scoping_report",
    "rating_approval": "contract_revision", "contract_approval": "contract_revision",
    "amendment_approval": "contract_revision", "reframe_approval": "contract_revision",
    "completion_approval": "dossier", "retirement": "topic", "hold_clearance": "hold",
    "publication_approval": "publication_source",
    "blind_initial_disposition": "decision_receipt", "advised_feedback": "decision_receipt",
}


DROP = object()  # a receipt_overrides value: remove this top-level field from the receipt JSON


def _override(body: dict, overrides: dict | None) -> None:
    for key, value in (overrides or {}).items():
        if value is DROP:
            body.pop(key, None)
        else:
            body[key] = value


def h(ch: str) -> str:
    return "sha256:" + ch * 64


def importance(band=None, score=None, decision=None, psource=None, pscore=None, preceipt=None) -> dict:
    """The contract-v2 importance object (proposed vs operator rating kept apart)."""
    proposed = None if psource is None and pscore is None else {"source": psource, "score": pscore, "decision_receipt_id": preceipt}
    rating = None if band is None and score is None and decision is None else {"band": band, "score": score, "operator_decision_id": decision}
    return {"proposed": proposed, "operator_rating": rating}


def facet(fid: str, **imp) -> dict:
    return {"facet_id": fid, "label": fid, "kind": "effect", "importance": importance(**imp)}


def obligation(oid: str, facet_ids=("F-1",), *, template: tuple = ("T1", 1, "effect"), stopping_profile: str = "SP-1",
               exploratory: bool = False, **imp) -> dict:
    """A contract-v2 obligation entry carrying the fields its normalized row
    duplicates (template id/version/claim type, facet tags, stopping profile,
    exploratory flag, importance)."""
    return {"obligation_id": oid, "template": {"template_id": template[0], "template_version": template[1], "claim_type": template[2]},
            "facet_ids": list(facet_ids), "exploratory": exploratory, "stopping_profile_id": stopping_profile, "importance": importance(**imp)}


def connect(apply_connection_contract: bool = True) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:", isolation_level=None)
    if apply_connection_contract:
        db.executescript(CONNECTION_TEXT)
    else:
        db.execute("PRAGMA foreign_keys = ON")  # FK enforcement only; recursive_triggers left at SQLite's default (off)
    db.executescript(DDL_TEXT)
    return db


class StoreTestCase(unittest.TestCase):
    APPLY_CONNECTION_CONTRACT = True

    def setUp(self) -> None:
        self.db = connect(self.APPLY_CONNECTION_CONTRACT)
        for tid in (TOPIC, OTHER):
            self.x("INSERT INTO queue_entries (topic_id, fleet_id, priority, status, created_at, updated_at) VALUES (?, 'fleet-a', 1, 'awaiting_brief_confirmation', ?, ?)", tid, T, T)
            self.contract(tid, 1)

    def tearDown(self) -> None:
        self.db.close()

    def x(self, sql: str, *params):
        return self.db.execute(sql, params)

    def rows(self, sql: str, *params) -> list[tuple]:
        return self.db.execute(sql, params).fetchall()

    def rejects(self, fragment: str, sql: str, *params) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.x(sql, *params)
        self.assertIn(fragment, str(ctx.exception))

    def snapshot(self, table: str) -> list[tuple]:
        return self.rows(f"SELECT * FROM {table} ORDER BY rowid")

    # -- builders --------------------------------------------------------
    CONTRACT_INSERT = ("INSERT INTO contract_revisions (topic_id, revision, parent_revision, protocol_revision, framing_version, content_hash, document, status, approved_by_decision_id, created_at) "
                       "VALUES (?, ?, ?, 1, 1, ?, ?, ?, ?, ?)")

    @staticmethod
    def contract_row(tid: str, rev: int, parent: int | None, content: str, facets: tuple = (), obligations: tuple = (),
                     status: str = "draft", approved_by: str | None = None) -> tuple:
        """The CONTRACT_INSERT parameters of one revision, its document agreeing with its columns."""
        doc = json.dumps({"topic_id": tid, "revision": rev, "parent_revision": parent, "created_at": T, "content_hash": content, "protocol_revision": 1,
                          "facet_map": {"framing_version": 1, "facets": list(facets)}, "obligations": list(obligations),
                          "eligibility_protocol": {"protocol_version": 1}})
        return (tid, rev, parent, content, doc, status, approved_by, T)

    def contract(self, tid: str, rev: int, status: str = "draft", approved_by: str | None = None, ch: str | None = None,
                 facets: tuple = (), obligations: tuple = (), content_hash: str | None = None, parent: int | None = None) -> str:
        """A draft revision; its parent is the previous revision unless `parent` is given."""
        content = content_hash or h(ch or ("a" if tid == TOPIC else "b") if rev == 1 else ch or str(rev))
        parent = parent if parent is not None else (None if rev == 1 else rev - 1)
        self.x(self.CONTRACT_INSERT, *self.contract_row(tid, rev, parent, content, facets, obligations, status, approved_by))
        return content

    def contract_cycle(self, tid: str, a: int, b: int, facets: tuple = (), obligations: tuple = ()) -> None:
        """Revisions a and b of `tid`, each naming the other as its parent,
        written by ONE multi-row INSERT — the foreign key is checked at
        statement end, when both rows exist — so the parent chain would be a
        cycle (RA2-R). Both carry these entries."""
        self.x(self.CONTRACT_INSERT + ", (?, ?, ?, 1, 1, ?, ?, ?, ?, ?)",
               *self.contract_row(tid, a, b, self.chash(tid, a), facets, obligations),
               *self.contract_row(tid, b, a, self.chash(tid, b), facets, obligations))

    def decision(self, did: str, kind: str, tid: str | None = TOPIC, disposition: str = "approved", *, ref: str | None = None,
                 rev: int | None = None, hsh: str | None = None, subject_kind: str | None = None, payload: dict | None = None) -> str:
        """Record an operator decision. Subject defaults: contract/dossier/topic
        subjects are referenced by topic id; other refs must be passed. A
        rating decision carries its rating payload (default: rates nothing)."""
        sk = subject_kind or SUBJECT_KIND[kind]
        if ref is None:
            ref = tid if sk in ("contract_revision", "dossier", "topic") else "ref-" + did
        if kind == "rating_approval" and payload is None:
            payload = {"facets": {}, "obligations": {}}
        self.x("INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'user', ?, ?)",
               did, tid, kind, disposition, sk, ref, rev, hsh, T, None if payload is None else json.dumps(payload))
        return did

    @staticmethod
    def unrated(entry: dict) -> dict:
        """The entry as it stood in the draft the operator rated (no operator rating yet)."""
        out = copy.deepcopy(entry)
        out["importance"]["operator_rating"] = None
        return out

    def rate(self, did: str, tid: str = TOPIC, *, facets: tuple = (), obligations: tuple = (), disposition: str = "approved",
             parent: int | None = None, payload: dict | None = None) -> int:
        """S3's rating step (RA2). Writes the next revision of `tid` as the draft
        the operator rates — these entries with no operator rating — and
        records rating decision `did` about it, whose retained payload is the
        band/score each entry carries (or `payload`). The caller then writes the
        rated revision (draft + 1), whose entries carry the ratings citing
        `did`. Returns the draft revision."""
        rev = self.rows("SELECT coalesce(max(revision), 0) + 1 FROM contract_revisions WHERE topic_id = ?", tid)[0][0]
        self.contract(tid, rev, facets=tuple(map(self.unrated, facets)), obligations=tuple(map(self.unrated, obligations)),
                      content_hash=self.chash(tid, rev), parent=parent)
        if payload is None:
            def rated(entries, key):
                return {e[key]: {"band": e["importance"]["operator_rating"]["band"], "score": e["importance"]["operator_rating"]["score"]}
                        for e in entries if (e["importance"]["operator_rating"] or {}).get("operator_decision_id") == did}
            payload = {"facets": rated(facets, "facet_id"), "obligations": rated(obligations, "obligation_id")}
        self.decision(did, "rating_approval", tid, disposition, rev=rev, hsh=self.chash(tid, rev), payload=payload)
        return rev

    @staticmethod
    def _importance_columns(entry: dict) -> tuple:
        proposed = entry["importance"]["proposed"] or {}
        rating = entry["importance"]["operator_rating"] or {}
        return (proposed.get("source"), proposed.get("score"), proposed.get("decision_receipt_id"),
                rating.get("band"), rating.get("score"), rating.get("operator_decision_id"))

    def insert_facet(self, tid: str, rev: int, entry: dict) -> None:
        self.x("INSERT INTO facets (topic_id, contract_revision, facet_id, proposed_importance_source, proposed_importance_score, proposed_decision_receipt_id, "
               "operator_importance_band, operator_importance_score, operator_rating_decision_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
               tid, rev, entry["facet_id"], *self._importance_columns(entry))

    def insert_obligation(self, tid: str, rev: int, entry: dict, **column_overrides) -> None:
        """The normalized row of an obligation entry (column_overrides make it disagree)."""
        t = entry["template"]
        cols = {"topic_id": tid, "contract_revision": rev, "obligation_id": entry["obligation_id"], "template_id": t["template_id"],
                "template_version": t["template_version"], "claim_type": t["claim_type"], "facet_ids": json.dumps(entry["facet_ids"]),
                "stopping_profile_id": entry["stopping_profile_id"], "exploratory": int(entry["exploratory"])}
        cols.update(zip(("proposed_importance_source", "proposed_importance_score", "proposed_decision_receipt_id",
                         "operator_importance_band", "operator_importance_score", "operator_rating_decision_id"), self._importance_columns(entry)))
        cols.update(column_overrides)
        self.x(f"INSERT INTO obligations ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", *cols.values())

    def contract_with_rows(self, tid: str, rev: int, facets: tuple = (), obligations: tuple = (), **kwargs) -> str:
        """A draft revision whose document carries these entries, plus their normalized rows."""
        content = self.contract(tid, rev, facets=facets, obligations=obligations, **kwargs)
        for entry in facets:
            self.insert_facet(tid, rev, entry)
        for entry in obligations:
            self.insert_obligation(tid, rev, entry)
        return content

    @staticmethod
    def chash(tid: str, rev: int) -> str:
        """A content hash unique per (topic, revision) — contract hashes are unique store-wide."""
        return "sha256:" + (tid.encode().hex() + f"{rev:06d}").ljust(64, "0")[:64]

    def approved_with_obligation(self, tid: str = TOPIC) -> int:
        """The S3 path to an approved protocol with a critical facet F-1 and an
        obligation O-1 tagging it: draft n carries them unrated; the operator's
        rating decision is about draft n; revision n + 1 carries the ratings,
        citing that decision, and is approved (any earlier approved revision is
        superseded first). Returns n + 1."""
        n = self.rows("SELECT coalesce(max(revision), 0) + 1 FROM contract_revisions WHERE topic_id = ?", tid)[0][0]
        did = f"opd_rate{tid[-2:]}{n:02d}"
        rated = dict(band="critical", score=8, decision=did)
        entries = dict(facets=(facet("F-1", **rated),), obligations=(obligation("O-1", ("F-1",), **rated),))
        self.rate(did, tid, **entries)
        self.contract_with_rows(tid, n + 1, **entries, content_hash=self.chash(tid, n + 1))
        for (old,) in self.rows("SELECT revision FROM contract_revisions WHERE topic_id = ? AND status = 'approved'", tid):
            self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = ?", tid, old)
        self.approve_contract(tid, n + 1)
        return n + 1

    def content_hash_of(self, tid: str, rev: int) -> str:
        return self.rows("SELECT content_hash FROM contract_revisions WHERE topic_id = ? AND revision = ?", tid, rev)[0][0]

    def approve_contract(self, tid: str, rev: int, did: str | None = None, kind: str = "contract_approval") -> str:
        did = did or f"opd_ca{rev:02d}{tid[-2:]}xx".replace(":", "")
        self.decision(did, kind, tid, rev=rev, hsh=self.content_hash_of(tid, rev))
        self.x("UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = ? WHERE topic_id = ? AND revision = ?", did, tid, rev)
        return did

    def set_status(self, tid: str, status: str, decision: str | None = None) -> None:
        self.x("UPDATE queue_entries SET status = ?, status_decision_id = ?, state_revision = state_revision + 1 WHERE topic_id = ?", status, decision, tid)

    # One allowed path from intake to each status (hand-written from the draft
    # queue vocabulary in gen2/store/README.md; the DDL trigger is under test).
    QUEUE_PATH = {
        "awaiting_brief_confirmation": (), "scoping": ("scoping",),
        "awaiting_scope_approval": ("scoping", "awaiting_scope_approval"),
        "awaiting_contract_approval": ("scoping", "awaiting_scope_approval", "awaiting_contract_approval"),
        "queued": ("scoping", "awaiting_scope_approval", "awaiting_contract_approval", "queued"),
        "active": ("scoping", "awaiting_scope_approval", "awaiting_contract_approval", "queued", "active"),
        "resting": ("scoping", "awaiting_scope_approval", "awaiting_contract_approval", "queued", "active", "resting"),
        "held": ("scoping", "awaiting_scope_approval", "awaiting_contract_approval", "queued", "held"),
        "capability_blocked": ("scoping", "awaiting_scope_approval", "awaiting_contract_approval", "queued", "capability_blocked"),
        "stopped_for_resources": ("scoping", "awaiting_scope_approval", "awaiting_contract_approval", "queued", "active", "stopped_for_resources"),
        "awaiting_judgment": ("scoping", "awaiting_scope_approval", "awaiting_contract_approval", "queued", "active", "awaiting_judgment"),
    }

    def walk_to(self, tid: str, status: str) -> None:
        """Leaving intake needs a confirmed brief (G-4); the walk confirms one."""
        if self.QUEUE_PATH[status]:
            self.confirm_brief(tid)
        for step in self.QUEUE_PATH[status]:
            self.set_status(tid, step)

    def state_revision(self, tid: str = TOPIC) -> int:
        return self.rows("SELECT state_revision FROM queue_entries WHERE topic_id = ?", tid)[0][0]

    def lease(self, lid: str, gen: int, tid: str = TOPIC, scope: str = "research") -> None:
        self.x("INSERT INTO leases (lease_id, topic_id, scope, generation, station_id, granted_at, expires_at) VALUES (?, ?, ?, ?, 'st1', ?, ?)", lid, tid, scope, gen, T, T)

    def approved_revision(self, tid: str) -> int:
        """The topic's approved contract revision, approving draft revision 1 if
        none is approved yet (contract/1 admission needs one)."""
        rows = self.rows("SELECT revision FROM contract_revisions WHERE topic_id = ? AND status = 'approved'", tid)
        if rows:
            return rows[0][0]
        self.approve_contract(tid, 1)
        return 1

    @staticmethod
    def brief_hash(tid: str, brief: str = "brief-1", version: int = 1) -> str:
        """h("b") for TOPIC's brief-1 v1 (the brief most tests pin); a hash
        unique per (topic, brief, version) otherwise (brief hashes are unique
        store-wide)."""
        if (tid, brief, version) == (TOPIC, "brief-1", 1):
            return h("b")
        return "sha256:" + (tid + "/" + brief).encode().hex()[:52].ljust(52, "0") + f"{version:012d}"

    def brief(self, tid: str = TOPIC, brief: str = "brief-1", version: int = 1, parent: int | None = None, *,
              content_hash: str | None = None, owner: str = "user", deadline: str = T) -> str:
        """An intake brief version, written awaiting confirmation; its
        document's identity fields agree with its columns. Returns its hash."""
        content = content_hash or self.brief_hash(tid, brief, version)
        doc = {"brief_version": "intake-brief/1", "topic_id": tid, "brief_id": brief, "version": version, "parent_version": parent,
               "created_at": T, "content_hash": content, "objective_in_operator_words": "why is intake slow", "feeds": "rebuild or not",
               "evidence_that_would_change_it": ["stage latencies"], "constraints": [], "operator_hypotheses": [], "surfaced_assumptions": []}
        self.x("INSERT INTO intake_briefs (topic_id, brief_id, version, parent_version, content_hash, document, owner_operator_id, status, created_at, review_deadline) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, 'awaiting_confirmation', ?, ?)", tid, brief, version, parent, content, json.dumps(doc), owner, T, deadline)
        return content

    def confirm_brief(self, tid: str = TOPIC, brief: str = "brief-1", version: int = 1, did: str | None = None) -> tuple:
        """The S1 confirmation (G-4): the brief version is stored, the operator's
        brief_confirmation decision names it exactly, and the version moves
        to confirmed recording that decision. Idempotent."""
        did = did or f"opd_brief_{tid}_{brief}_v{version}"
        bhash = self.brief_hash(tid, brief, version)
        if not self.rows("SELECT 1 FROM intake_briefs WHERE topic_id = ? AND brief_id = ? AND version = ?", tid, brief, version):
            self.brief(tid, brief, version, parent=None if version == 1 else version - 1)
        if not self.rows("SELECT 1 FROM operator_decisions WHERE decision_id = ?", did):
            self.decision(did, "brief_confirmation", tid, ref=brief, rev=version, hsh=bhash)
        if not self.rows("SELECT 1 FROM intake_briefs WHERE topic_id = ? AND brief_id = ? AND version = ? AND status = 'confirmed'", tid, brief, version):
            self.x("UPDATE intake_briefs SET status = 'confirmed', confirmed_by_decision_id = ? WHERE topic_id = ? AND brief_id = ? AND version = ?", did, tid, brief, version)
        return brief, version, bhash, did

    def invocation(self, iid: str, kind: str = "research_pass", lease: str | None = "lease_aaaaaaaa", tid: str = TOPIC, parent: str | None = None,
                   *, pre_contract: bool = False, contract_rev: int | None = None, requested_by: str | None = None) -> None:
        if kind == "delegate":
            pins = self.rows("SELECT admission_context, contract_revision, brief_ref, brief_version, brief_hash, brief_confirmation_decision_id FROM invocations WHERE invocation_id = ?", parent)
            pins = pins[0] if pins else ("contract/1", self.approved_revision(tid), None, None, None, None)
        elif pre_contract:
            pins = ("pre-contract/1", None, *self.confirm_brief(tid))
        else:
            pins = ("contract/1", contract_rev or self.approved_revision(tid), None, None, None, None)
        self.x("INSERT INTO invocations (invocation_id, kind, topic_id, parent_invocation_id, requested_by_invocation_id, lease_id, capability_id, config_bundle_hash, "
               "admission_context, contract_revision, brief_ref, brief_version, brief_hash, brief_confirmation_decision_id, state, admitted_at, deadline_at, state_changed_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'admitted', ?, ?, ?)",
               iid, kind, tid, parent, requested_by, lease, "cap_" + iid[4:], h("c"), *pins, T, T, T)

    def raw_invocation(self, **cols) -> tuple:
        """INSERT for an invocation row with every column explicit: defaults are a
        contract-admitted research pass on lease_aaaaaaaa (the topic's contract
        is approved first); pass column=value to override. Returns (sql, *params)
        so it can be splatted into x()/rejects()."""
        tid = cols.get("topic_id", TOPIC)
        row = {"invocation_id": "inv_rawrawra", "kind": "research_pass", "topic_id": tid, "parent_invocation_id": None,
               "requested_by_invocation_id": None, "lease_id": "lease_aaaaaaaa", "capability_id": None, "config_bundle_hash": h("c"),
               "admission_context": "contract/1", "contract_revision": None, "brief_ref": None, "brief_version": None, "brief_hash": None,
               "brief_confirmation_decision_id": None, "state": "admitted", "admitted_at": T, "deadline_at": T, "state_changed_at": T}
        row.update(cols)
        if row["capability_id"] is None:
            row["capability_id"] = "cap_" + row["invocation_id"][4:]
        if row["admission_context"] == "contract/1" and "contract_revision" not in cols:
            row["contract_revision"] = self.approved_revision(tid)
        names = ", ".join(row)
        return (f"INSERT INTO invocations ({names}) VALUES ({', '.join('?' * len(row))})", *row.values())

    def receipt_body(self, op: str, rid: str, kind: str, inv: str, tid: str, before: int, *, digest: str | None = None, fingerprint: str | None = None,
                     admission: tuple | None = None, validator: str = "v1", policy: str = "p1") -> dict:
        """The commit receipt JSON (commit-outcome.schema.json#/$defs/receipt)
        for these column values. Admission references come from the
        invocation's pins; `admission=(context, contract_revision, brief_hash)`
        overrides the three pinned columns (the JSON follows, so only the
        column/invocation comparison can refuse it)."""
        digest, fingerprint = digest or h("d"), fingerprint or h("f")
        found = self.rows("SELECT admission_context, contract_revision, brief_ref, brief_version, brief_hash, brief_confirmation_decision_id FROM invocations WHERE invocation_id = ?", inv)
        context, contract_rev, brief_ref, brief_version, brief_hash, confirmation = found[0] if found else ("contract/1", 1, None, None, None, None)
        if admission is not None:
            context, contract_rev, brief_hash = admission
        adm: dict = {"context": context}
        if contract_rev is not None:
            chash = self.rows("SELECT content_hash FROM contract_revisions WHERE topic_id = ? AND revision = ?", tid, contract_rev)
            adm["contract"] = {"revision": contract_rev, "content_hash": chash[0][0] if chash else None}
        if brief_hash is not None:
            adm["brief"] = {"brief_id": brief_ref, "version": brief_version, "content_hash": brief_hash}
            adm["brief_confirmation_decision_id"] = confirmation
        return {"receipt_version": "commit-receipt/1", "receipt_id": rid, "operation_id": op, "operation_kind": kind,
                "invocation_id": inv, "topic_id": tid, "request_fingerprint": fingerprint, "payload_digest": digest,
                "hash_contract": {"canonicalization": "jcs-rfc8785/1", "fingerprint": "commit-fingerprint/1"},
                "admission": adm, "committed_at": T, "state_revision_before": before, "state_revision_after": before + 1,
                "validation": {"validator_version": validator, "policy_version": policy, "validated_hashes": [digest]},
                "effects": {"evidence_revision": None, "research_ordinal": None, "queue_transition": None, "lease_release": None,
                            "holds_created": [], "retry_intent": None, "trigger_identities": [], "outbox_event_ids": [],
                            "decision_receipt_ids": [], "audit_event_id": "aud_" + op[3:]}}

    def receipt(self, op: str, inv: str, lease: str = "lease_aaaaaaaa", gen: int = 1, before: int = 0, kind: str = "final_outcome", tid: str = TOPIC,
                rid: str | None = None, digest: str = "d", admission: tuple | None = None, receipt_overrides: dict | None = None) -> None:
        """A commit receipt carrying the invocation's own admission pins (pass
        `admission=(context, contract_revision, brief_hash)` to probe a mismatch;
        receipt_overrides replace top-level JSON fields; DROP removes one)."""
        rid = rid or "rcpt_" + op[3:]
        body = self.receipt_body(op, rid, kind, inv, tid, before, digest=h(digest), admission=admission)
        _override(body, receipt_overrides)
        context = body["admission"]["context"]
        contract_rev = (body["admission"].get("contract") or {}).get("revision") if admission is None else admission[1]
        brief_hash = (body["admission"].get("brief") or {}).get("content_hash") if admission is None else admission[2]
        self.x("INSERT INTO operation_receipts (operation_id, receipt_id, operation_kind, invocation_id, topic_id, request_fingerprint, payload_digest, lease_id, lease_generation, "
               "admission_context, contract_revision, brief_hash, config_bundle_hash, state_revision_before, state_revision_after, validator_version, policy_version, receipt, committed_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'v1', 'p1', ?, ?)",
               op, rid, kind, inv, tid, h("f"), h(digest), lease, gen, context if admission is None else admission[0], contract_rev, brief_hash, h("c"),
               before, before + 1, json.dumps(body), T)

    CHECKS_OK = {"numeric_units": "checked_ok", "denominators": "checked_ok", "negation": "checked_ok", "qualifications": "checked_ok"}

    def verify(self, rid: str, *, claim: tuple = ("clm_00000001", 1), work: str = "wrk_00000001", tier: str = "full_text", required: str = "full_text",
               use: str = "load_bearing", method: str = "verifier_extraction", extraction: str = "inv_vvvvvvvv", validation: str | None = None,
               producer: str = "inv_pppppppp", verifier: str = "inv_vvvvvvvv", verdict: str = "supports", checks: dict | None = None,
               quote: tuple = ("matched", "qc-1"), source_artifact: str | None = None, tier0: str | None = None, adjudication: dict | None = None,
               gateway: str | None = "gw-call-1", obtained: str | None = None, capability: str | None = None,
               receipt_overrides: dict | None = None, column_overrides: dict | None = None, drop: tuple = ()) -> None:
        """A verification receipt whose JSON (verification-receipt.schema.json
        shape) and normalized columns are built from the same values; pass
        receipt_overrides / column_overrides to make them disagree."""
        obtained = obtained or h("7")
        status, check_id = quote
        capability = capability or self.rows("SELECT capability_id FROM invocations WHERE invocation_id = ?", verifier)[0][0]
        spans = [{"start": 0, "end": 5, "locator": {"kind": "page", "value": "3"}}]
        acquisition = {"route": "gateway:crossref", "retrieved_at": T, "gateway_call_ref": gateway, "cache_reuse": False}
        doc = {"receipt_version": "verification-receipt/1", "verification_receipt_id": rid, "topic_id": TOPIC,
               "claim": {"claim_id": claim[0], "claim_revision": claim[1]}, "source": {"work_id": work, "source_version": "v1"},
               "cited_spans": spans, "obtained_content_hash": obtained, "access_tier": tier,
               "requested_for": {"use": use, "required_access_tier": required}, "acquisition": acquisition,
               "extraction": {"method": method, "extractor": "x-1", "produced_by_invocation_id": extraction, "validation_ref": validation},
               "producer_invocation_id": producer, "verifier_invocation_id": verifier, "verifier_capability_id": capability,
               "quote_check_id": check_id,
               "checks": {"exact_quote": {"status": status, "normalization_version": "n1", "source_artifact_hash": source_artifact or h("7")},
                          **(checks or self.CHECKS_OK), **({"tier0": {"checker": "minicheck", "checker_version": "1", "signal": tier0}} if tier0 else {})},
               "adjudication": adjudication, "verdict": verdict, "verified_at": T}
        for key, value in (receipt_overrides or {}).items():
            doc[key] = value
        for path in drop:  # delete a (dotted) key: probes the absent-key case of NULL-sensitive CHECKs
            *parents, last = path.split(".")
            node = doc
            for part in parents:
                node = node[part]
            del node[last]
        cols = {"verification_receipt_id": rid, "topic_id": TOPIC, "claim_id": claim[0], "claim_revision": claim[1], "work_id": work, "source_version": "v1",
                "cited_spans": json.dumps(spans), "obtained_content_hash": obtained, "access_tier": tier, "use": use, "required_access_tier": required,
                "acquisition": json.dumps(acquisition), "extraction_method": method, "extraction_invocation_id": extraction,
                "extraction_validation_ref": validation, "producer_invocation_id": producer, "verifier_invocation_id": verifier,
                "quote_check_id": check_id, "verdict": verdict, "receipt": json.dumps(doc), "verified_at": T}
        cols.update(column_overrides or {})
        self.x(f"INSERT INTO verification_receipts ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", *cols.values())

    def quote_check(self, check_id: str, *, claim: tuple = ("clm_00000001", 1), source: str | None = None, match: str = "matched",
                    nli: str = "not_run", quarantined: int | None = None) -> None:
        quarantined = quarantined if quarantined is not None else int(match == "mismatch" or nli == "alarm")
        self.x("INSERT INTO quote_checks (check_id, claim_id, claim_revision, source_artifact_hash, span_start, span_end, normalization_version, exact_match, nli_checker, nli_checker_version, nli_signal, quote_quarantined, checked_at) "
               "VALUES (?, ?, ?, ?, 0, 5, 'n1', ?, ?, ?, ?, ?, ?)", check_id, claim[0], claim[1], source or h("7"), match,
               None if nli == "not_run" else "minicheck", None if nli == "not_run" else "1", nli, quarantined, T)

    def spec(self, spec_id: str = "dspec_screen01", provider: str = "jev", cls: str = "screening", *, primitive: str | None = None,
             policy: tuple = ("P1", 1), options: tuple = ("include", "exclude"), protocol_topic: str | None = None,
             no_protocol: bool = False, document_overrides: dict | None = None, drop: tuple = ()) -> str:
        """A DecisionSpec row whose document follows decision-spec.schema.json in
        the fields the store reads. Screening/method_selection specs get a
        protocol bound to protocol_topic (default TOPIC); others none."""
        sh = "sha256:" + (spec_id.encode().hex() + "0" * 64)[:64]
        primitive = primitive or ("choice" if provider == "jev" else "label")
        if protocol_topic is None and cls in ("screening", "method_selection") and not no_protocol:
            protocol_topic = TOPIC
        protocol = None if protocol_topic is None else {"topic_id": protocol_topic, "contract": {"revision": 1, "content_hash": h("a")},
                                                         "eligibility_protocol_version": 1 if cls == "screening" else None}
        doc = {"spec_version": "decision-spec/1", "spec_id": spec_id, "decision_class": cls, "provider": provider, "primitive": primitive,
               "action_policy": {"policy_id": policy[0], "version": policy[1]}, "protocol": protocol,
               "options": {o: {"criteria": f"criteria for {o}"} for o in options}}
        doc.update(document_overrides or {})
        for key in drop:
            del doc[key]
        self.x("INSERT INTO decision_specs (spec_hash, spec_id, decision_class, provider, primitive, policy_id, policy_version, protocol_topic_id, document, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               sh, spec_id, cls, provider, primitive, policy[0], policy[1], protocol_topic, json.dumps(doc), T)
        return sh

    def raw_artifact(self, digest: str) -> str:
        if not self.rows("SELECT 1 FROM artifacts WHERE content_hash = ?", digest):
            self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", digest, T)
        return digest

    def decision_receipt(self, did: str, inv: str, spec_hash: str, provider: str = "jev", answer: dict | None = None, authority: str = "shadow",
                         qualification: str | None = None, action: str = "shadow_log_only", commit_op: str | None = None, hold: str | None = None,
                         cls: str = "screening", tid: str = TOPIC, *, subject: tuple = ("work", "wrk_00000001"), proposal: str | None = None,
                         status: str = "answered", input_status: str = "complete", raw: str | None = "5", policy: tuple = ("P1", 1),
                         blind: bool = False, stage_raw: bool = True, receipt_overrides: dict | None = None, column_overrides: dict | None = None) -> None:
        """A decision receipt whose JSON (decision-receipt.schema.json shape) and
        columns come from the same values; the raw response bytes are a staged
        artifact whose hash is the digest (pass raw=None for no bytes)."""
        if answer is None and status == "answered":
            answer = {"primitive": "choice", "selected_option_id": "include", "distribution": {"include": 0.8, "exclude": 0.2}, "confidence": 0.7}
        digest = None if raw is None else (self.raw_artifact(h(raw)) if stage_raw else h(raw))
        spec_id = self.rows("SELECT spec_id FROM decision_specs WHERE spec_hash = ?", spec_hash)
        doc = {"receipt_version": "decision-receipt/1", "decision_receipt_id": did, "invocation_id": inv, "topic_id": tid, "decided_at": T,
               "hash_contract": {"canonicalization": "jcs-rfc8785/1"},
               "spec": {"spec_id": spec_id[0][0] if spec_id else "dspec_unknown", "spec_hash": spec_hash}, "decision_class": cls, "provider": provider,
               "subject": {"kind": subject[0], "ref": subject[1]},
               "input_manifest": {"snapshot_digest": h("6"), "input_record_ids": [], "input_status": input_status},
               "provider_response": {"status": status, "raw_response_digest": digest,
                                     "raw_response_artifact": None if digest is None else {"content_hash": digest, "size_bytes": 10, "media_type": "application/json"},
                                     "answer": answer},
               "policy": {"policy_id": policy[0], "version": policy[1]},
               "authorization": {"authority_level": authority, "qualification_ref": qualification},
               "action": action, "outcome": {"commit_operation_id": commit_op, "proposal_ref": proposal, "hold_id": hold},
               "blind_sample": {"selected": blind, "initial_disposition_ref": None}}
        _override(doc, receipt_overrides)
        cols = {"decision_receipt_id": did, "invocation_id": inv, "topic_id": tid, "spec_hash": spec_hash, "decision_class": cls, "provider": provider,
                "input_status": input_status, "response_status": status, "raw_response_digest": digest,
                "answer": None if answer is None else json.dumps(answer), "subject_kind": subject[0], "subject_ref": subject[1],
                "policy_id": policy[0], "policy_version": policy[1], "authority_level": authority, "qualification_ref": qualification,
                "action": action, "commit_operation_id": commit_op, "hold_id": hold, "proposal_ref": proposal, "blind_sample": int(blind),
                "receipt": json.dumps(doc), "decided_at": T}
        cols.update(column_overrides or {})
        self.x(f"INSERT INTO decision_receipts ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", *cols.values())

    def to_launching(self, iid: str) -> None:
        self.x("UPDATE invocations SET state = 'launching', launch_intent_at = ?, job_handle = ? WHERE invocation_id = ?", T, "job-" + iid, iid)

    def to_running(self, iid: str) -> None:
        self.to_launching(iid)
        self.x("UPDATE invocations SET state = 'running', host_id = 'dev', boot_id = 'b1', start_fingerprint = 'st=1' WHERE invocation_id = ?", iid)

    def to_unknown(self, iid: str, since: str = T) -> None:
        """Enter outcome_unknown: a new episode, with its own (next) identity (RA4)."""
        self.x("UPDATE invocations SET state = 'outcome_unknown', outcome_unknown_since = ?, unknown_episode = unknown_episode + 1 WHERE invocation_id = ?", since, iid)

    def reconcile(self, iid: str, resolution: str, *, digest: str | None = None, rid: str | None = None, method: str | None = None,
                  descendants: str | None = None, since: str | None = None, episode: int | None = None) -> None:
        """Record the reconciliation of the invocation's current unknown episode
        (evidence: the retained lookup record, artifact h("7"))."""
        if not self.rows("SELECT 1 FROM artifacts WHERE content_hash = ?", h("7")):
            self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", h("7"), T)
        current_since, current_episode = self.rows("SELECT outcome_unknown_since, unknown_episode FROM invocations WHERE invocation_id = ?", iid)[0]
        since = since or current_since
        episode = episode if episode is not None else current_episode
        method = method or ("execution_group_termination" if resolution == "terminated_group" else "job_handle_lookup")
        if descendants is None and resolution in ("confirmed_failed", "terminated_group"):
            descendants = T
        self.x("INSERT INTO invocation_reconciliations (reconciliation_id, invocation_id, unknown_episode, unknown_since, resolution, method, evidence_ref, result_payload_digest, descendants_confirmed_at, resolved_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rid or f"rec_{iid[4:]}e{episode}", iid, episode, since, resolution, method, h("7"), digest, descendants, T)

    # -- one coherent row in every table -------------------------------------
    def populate_every_table(self) -> None:
        """A positive control that the whole schema admits one coherent history,
        and the population the history-rewrite sweep attacks. Keep one row in
        every table: test_every_table_is_populated fails if a table is added
        without extending this."""
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, topic_id, staged_at) VALUES (?, 10, 'application/json', ?, ?)", h("7"), TOPIC, T)
        self.confirm_brief(TOPIC)  # S1: the topic's intake brief, confirmed (intake_briefs)
        # S3: the operator rates draft revision 2; revision 3 carries the ratings and is approved
        rev = self.approved_with_obligation(TOPIC)
        self.x("UPDATE queue_entries SET active_contract_revision = ? WHERE topic_id = ?", rev, TOPIC)
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.to_running("inv_pppppppp")
        self.x("INSERT INTO invocation_transitions (invocation_id, seq, from_state, to_state, at, cause) VALUES ('inv_pppppppp', 1, NULL, 'admitted', ?, 'admit')", T)
        self.to_unknown("inv_pppppppp")
        self.reconcile("inv_pppppppp", "found_running")
        self.x("UPDATE invocations SET state = 'running' WHERE invocation_id = 'inv_pppppppp'")
        self.x("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, 1, ?, 1, 'eval-1', ?, ?, ?)", TOPIC, rev, h("3"), h("7"), T)
        self.receipt("op_00000001", "inv_pppppppp", kind="final_outcome", before=0)
        self.x("INSERT INTO research_ordinals VALUES (?, 1, 'inv_pppppppp', 'op_00000001')", TOPIC)
        self.x("INSERT INTO review_episodes (episode_id, topic_id, kind, opened_at, opened_by_operation_id) VALUES ('ep-1', ?, 'method_fit', ?, 'op_00000001')", TOPIC, T)
        self.x("INSERT INTO review_triggers (trigger_identity, topic_id, reason_code, signal_source, cause_ref, observed_at, episode_id, handled_at) VALUES (?, ?, 'persistent_contradiction', 'deterministic', 'CL-3', ?, 'ep-1', ?)", h("1"), TOPIC, T, T)
        self.x("INSERT INTO capability_facts (fact_id, capability, state, detail, since, affected_lanes, recorded_at) VALUES ('cf-1', 'secrets_backend', 'failing', 'vault 403', ?, '[\"semantic_scholar\"]', ?)", T, T)
        self.x("INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, deadline_at, clears_when, capability_fact_id, created_at) "
               "VALUES ('hold_00000001', ?, 'lane:semantic_scholar', 'capability', 'vault 403', 'needs_remediation', 'router', 'router', ?, 'secrets backend healthy', 'cf-1', ?)", TOPIC, T, T)
        self.x("INSERT INTO search_observations (observation_id, invocation_id, topic_id, request_identity, attempt, lane, request, obligation_ids, started_at, coverage_state, result_count, completeness, policy_version) "
               "VALUES ('o1', 'inv_pppppppp', ?, ?, 1, 'crossref', '{}', '[\"O-1\"]', ?, 'searched_ok', 1, 'complete', 'pol1')", TOPIC, h("4"), T)
        self.x("INSERT INTO retrieval_events (event_id, observation_id, topic_id, provider_record_id, rank, captured_at) VALUES ('e1', 'o1', ?, 'rec-1', 1, ?)", TOPIC, T)
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000001', 'doi', '10.1/x', ?)", T)
        self.x("INSERT INTO record_work_links (event_id, work_id, dedup_method_version, linked_at) VALUES ('e1', 'wrk_00000001', 'dedup-1', ?)", T)
        self.x("INSERT INTO screening_assessments (assessment_id, topic_id, work_id, contract_revision, eligibility_protocol_version, framing_version, stage, decision, reason_code, criterion_results, actor_kind, invocation_id, recorded_by_operation_id, created_at) "
               "VALUES ('sa1', ?, 'wrk_00000001', ?, 1, 1, 'abstract', 'include', NULL, '{}', 'primary', 'inv_pppppppp', 'op_00000001', ?)", TOPIC, rev, T)
        self.x("INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES ('clm_00000001', 1, ?, ?, 'inv_pppppppp', 1, 'full_text', 'provisional', ?)", TOPIC, h("7"), T)
        self.x("INSERT INTO claim_source_links (claim_id, claim_revision, work_id, source_version, topic_id, contract_revision, obligation_id, spans, contribution, evidence_origin_lineage, created_at) "
               "VALUES ('clm_00000001', 1, 'wrk_00000001', 'v1', ?, ?, 'O-1', '[]', 'answer', 'study-1', ?)", TOPIC, rev, T)
        self.lease("lease_vvvvvvvv", 2, scope="verification")
        self.invocation("inv_vvvvvvvv", kind="verification", lease="lease_vvvvvvvv")
        self.quote_check("qc-1")
        self.verify("ver_00000001")
        self.x("UPDATE claims SET status = 'accepted_support' WHERE claim_id = 'clm_00000001' AND revision = 1")
        jev = self.spec()
        self.decision_receipt("dec_00000001", "inv_pppppppp", jev)
        self.decision("opd_publish01", "publication_approval", ref="dossier-1", rev=1, hsh=h("3"))
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_publish01", h("6"), source_rev=1, source_hash=h("3"), connectors={"warehouse": "sql"})
        self.delivery()
        self.x("INSERT INTO connector_watermarks (topic_id, connector_id, generation, options_revision, delivered_at) VALUES (?, 'warehouse', 1, 1, ?)", TOPIC, T)
        self.x("INSERT INTO audit_events (audit_event_id, at, kind, topic_id, detail) VALUES ('aud_00000001', ?, 'commit', ?, '{}')", T, TOPIC)

    def delivery(self, *, receipt_overrides: dict | None = None, **row) -> None:
        """One export_delivery_receipts row: a delivered attempt of connector
        `warehouse` (sql) for man_00000001 unless `row` says otherwise, stored
        with its receipt document. The document is built from the row (and
        reports man_00000001's default topic and pair, TOPIC (1, 1)), so it
        agrees with the columns unless `receipt_overrides` says otherwise.
        Unless given, the written count follows the status: a delivery
        observed 12, a partial write 7 partial, an unknown outcome unknown,
        anything else an observed 0."""
        full = {"export_receipt_id": "exr_00000001", "manifest_id": "man_00000001", "connector_id": "warehouse", "connector_type": "sql",
                "attempt": 1, "status": "delivered", "tombstones_acknowledged": 1, "reconciliation_required": 0, "error_class": None,
                "unknown_cause": None, "capability_fact_id": None, "hold_id": None, "attempted_at": T, "acked_at": T}
        full.update(row)
        if "written_status" not in full:
            full["written_status"], full["written_value"] = (
                ("partial", 7) if full["error_class"] == "partial_write" else ("unknown", None) if full["status"] == "outcome_unknown"
                else ("observed", 12) if full["status"] == "delivered" else ("observed", 0))
        written = {"status": full["written_status"], **({} if full["written_value"] is None else {"value": full["written_value"]}),
                   **({} if full["written_status"] == "observed" else {"reason": "not every write was acknowledged"})}
        receipt = {"receipt_version": "export-delivery-receipt/2", "export_receipt_id": full["export_receipt_id"], "manifest_id": full["manifest_id"],
                   "topic_id": TOPIC, "connector": {"connector_id": full["connector_id"], "connector_type": full["connector_type"]},
                   "generation": 1, "options_revision": 1, "attempt": full["attempt"], "status": full["status"], "written": written,
                   "tombstones_acknowledged": bool(full["tombstones_acknowledged"]), "reconciliation_required": bool(full["reconciliation_required"]),
                   "attempted_at": full["attempted_at"], "acked_at": full["acked_at"],
                   **{k: full[k] for k in ("error_class", "unknown_cause", "capability_fact_id", "hold_id") if full[k] is not None}}
        receipt.update(receipt_overrides or {})
        full["receipt"] = json.dumps(receipt)
        self.x(f"INSERT INTO export_delivery_receipts ({', '.join(full)}) VALUES ({', '.join('?' * len(full))})", *full.values())

    def outbox(self, eid: str, mid: str, gen: int, sup: int | None, decision: str, manifest_hash: str, *, source_rev: int = 3,
               source_hash: str | None = None, connectors: dict | None = None, kind: str = "completion_publication",
               tid: str = TOPIC, op: str = "op_00000001", manifest_overrides: dict | None = None, options: int = 1,
               sup_options: int | None = 1, bundle_hash: str | None = None, connectors_json: str | None = None) -> None:
        """One export manifest (outbox_events, task 0d). `connectors` maps a
        connector id to its type; `connectors_json` stores exact JSON text
        instead (the shape probes). `sup`/`sup_options` are the superseded
        pair; the manifest JSON always agrees with the columns unless
        `manifest_overrides` says otherwise."""
        source_hash = source_hash or h("5")
        bundle_hash = bundle_hash or h("e")
        if connectors_json is None:
            connectors = {"warehouse": "sql", "archive": "jsonl_file"} if connectors is None else connectors
            connectors_json = json.dumps({cid: {"connector_type": ctype} for cid, ctype in connectors.items()})
        sup_opt = None if sup is None else sup_options
        manifest = {"manifest_id": mid, "topic_id": tid, "artifact_kind": kind, "generation": gen, "options_revision": options,
                    "source": {"revision": source_rev, "content_hash": source_hash},
                    "approval": {"operator_decision_id": decision, "approved_revision": source_rev},
                    "bundle": {"bundle_id": "exb_" + mid[4:], "bundle_version": "export-bundle/1", "content_hash": bundle_hash},
                    "expected_connectors": json.loads(connectors_json),
                    "supersedes": None if sup is None else {"manifest_id": "man_prev0000", "generation": sup, "options_revision": sup_opt}}
        manifest.update(manifest_overrides or {})
        self.x("INSERT INTO outbox_events (outbox_event_id, topic_id, manifest_id, manifest_hash, artifact_kind, generation, options_revision, supersedes_generation, supersedes_options_revision, "
               "source_revision, source_content_hash, approval_decision_id, bundle_content_hash, expected_connectors, manifest, committed_by_operation_id, created_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               eid, tid, mid, manifest_hash, kind, gen, options, sup, sup_opt, source_rev, source_hash, decision, bundle_hash, connectors_json, json.dumps(manifest), op, T)

    def tables(self) -> list[str]:
        return [r[0] for r in self.rows("SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
