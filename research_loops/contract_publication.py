"""Recoverable, exact checkpoint contract publication."""
from __future__ import annotations
import hashlib, json, shutil, tempfile, os, stat
from pathlib import Path
from typing import Any, Mapping

from .topic_authoring import compute_lock, obligation

class ContractPublicationError(RuntimeError): pass

def checkpoint_publisher(root: Path):
    return _BundlePublisher(root)

class _BundlePublisher:
    def __init__(self, root: Path): self.root = root
    def __call__(self, proposal, edits): return self.publish_bundle([(proposal, edits)])[0]
    def publish_bundle(self, selected):
        record = self.prepare_bundle(selected)
        return self.publish_prepared(record)
    def prepare_bundle(self, selected):
        if not selected: return []
        topic_id = selected[0][0].get("topic_id")
        if not isinstance(topic_id, str) or any(p.get("topic_id") != topic_id for p, _ in selected): raise ContractPublicationError("bundle must target one topic")
        topic = self.root / "topics" / topic_id
        if any((topic / name).is_symlink() for name in ("TOPIC.md", "SEMANTIC-STATE.json")):
            raise ContractPublicationError("contract paths must not be symlinks")
        journal = topic / ".checkpoint-contract-publication.json"
        identity = hashlib.sha256(json.dumps([{"proposal": p, "edits": e} for p, e in selected], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if journal.exists():
            prior = json.loads(journal.read_text())
            if prior.get("identity") != identity: raise ContractPublicationError("another contract publication is pending")
            return prior
        # Validate and build the entire resulting inventory in an isolated copy.
        with tempfile.TemporaryDirectory(dir=topic.parent) as tmp:
            staged = Path(tmp) / "topic"; shutil.copytree(topic, staged)
            for proposal, edits in selected:
                result = _publish(staged, proposal, edits)
                finalize_checkpoint_publication(result)
            state = (staged / "SEMANTIC-STATE.json").read_text()
            contract = (staged / "TOPIC.md").read_text()
            lock = compute_lock(staged)
        record = {"identity": identity, "count": len(selected), "topic_dir": str(topic), "state": json.loads(state), "topic": contract}
        # Controller may persist this record before target writes. Compatibility
        # callers retain a journal here for crash recovery.
        _atomic_write(journal, json.dumps(record, indent=2, sort_keys=True)+"\n")
        return record
    def publish_prepared(self, record):
        topic = Path(record["topic_dir"]); journal = topic / ".checkpoint-contract-publication.json"
        result = _finish(topic, record, journal, finalize=False)
        return [result for _ in range(int(record["count"]))]
    def finalize(self, result):
        for item in result:
            finalize_checkpoint_publication(item)

def _publish(topic: Path, proposal: Mapping[str, Any], edits: Mapping[str, Any] | None) -> dict[str, str]:
    kind = proposal.get("kind")
    if kind == "scope_request":
        raise ContractPublicationError("scope_request needs explicit new authority publication and cannot be approved here")
    state_path, topic_path = topic / "SEMANTIC-STATE.json", topic / "TOPIC.md"
    if not state_path.is_file() or not topic_path.is_file(): raise ContractPublicationError("approved topic contract is missing")
    journal = topic / ".checkpoint-contract-publication.json"
    key = str(proposal.get("proposal_id")) + ":" + str(proposal.get("proposal_version"))
    if journal.exists():
        record = json.loads(journal.read_text())
        if record.get("key") != key: raise ContractPublicationError("another contract publication is pending")
        return _finish(topic, record, journal, finalize=False)
    state = json.loads(state_path.read_text())
    text = topic_path.read_text()
    content = edits if edits is not None else proposal.get("content")
    if not isinstance(content, Mapping): raise ContractPublicationError("approved proposal has no exact content")
    obligations = state.get("obligations")
    if not isinstance(obligations, list): raise ContractPublicationError("semantic obligations are missing")
    if kind == "addition":
        body, source = content.get("text"), content.get("source_ref")
        if not isinstance(body, str) or not body.strip() or not isinstance(source, str) or not source.strip(): raise ContractPublicationError("addition requires exact text and source_ref")
        identifier = f"CHECKPOINT-{len(obligations)+1:02d}"
        if any(x.get("id") == identifier for x in obligations if isinstance(x, dict)): raise ContractPublicationError("generated obligation id already exists")
        obligations.append(obligation(identifier, body.strip(), source.strip()))
        marker = "## Required deliverables"
        if marker not in text: raise ContractPublicationError("TOPIC.md has no required-deliverables boundary")
        text = text.replace(marker, f"- **{identifier}** — {body.strip()}\n\n{marker}", 1)
    elif kind == "amendment":
        target, current, proposed = content.get("target_id"), content.get("current_text"), content.get("proposed_text")
        match = next((x for x in obligations if isinstance(x, dict) and x.get("id") == target), None)
        if not isinstance(target, str) or not isinstance(current, str) or not isinstance(proposed, str) or not proposed.strip() or not match or match.get("text") != current: raise ContractPublicationError("amendment does not match the exact current obligation")
        needle = f"**{target}** — {current}"
        if needle not in text: raise ContractPublicationError("TOPIC.md does not contain the exact current amendment text")
        # Changed wording must be re-researched. Keep prior evidence in the
        # ledger, but clear its terminal assessment on the amended obligation.
        match.update({"text": proposed.strip(), "disposition": "open", "confidence": None, "evidence_refs": [], "counterevidence_reviewed": False, "acceptance_summary": None, "counterevidence_summary": None, "gap_state": f"unaddressed: {target}", "adequate_search": None})
        text = text.replace(needle, f"**{target}** — {proposed.strip()}", 1)
    else: raise ContractPublicationError("unsupported proposal kind")
    state["contract_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    record = {"key": key, "state": state, "topic": text, "proposal_id": proposal.get("proposal_id")}
    journal.write_text(json.dumps(record, indent=2, sort_keys=True)+"\n")
    return _finish(topic, record, journal, finalize=False)

def _finish(topic: Path, record: Mapping[str, Any], journal: Path, *, finalize: bool) -> dict[str, str]:
    # Write replacements before dropping the journal; retries overwrite the same
    # deterministic content and never append an obligation twice.
    _atomic_write(topic / "SEMANTIC-STATE.json", json.dumps(record["state"], indent=2, sort_keys=True)+"\n")
    _atomic_write(topic / "TOPIC.md", str(record["topic"]))
    lock = compute_lock(topic)
    # The checkpoint service owns the decision commit. It may finalize this
    # journal only after persisting the returned lock/inventory in controller
    # state; keeping it makes a post-filesystem crash recoverable.
    if finalize: journal.unlink()
    return {"completion_lock": lock, "inventory_version": lock,
            "publication_journal": str(journal),
            # Cleanup verifies this before unlinking: the journal PATH is
            # reused across the topic's publications, so a stale pathname
            # must never delete a LATER publication's recovery marker
            # (Astra R2-1, 2026-09-10).
            "publication_identity": str(record.get("identity") or record.get("key") or "")}

def finalize_checkpoint_publication(result: Mapping[str, Any]) -> None:
    """Remove a committed publication's journal — and ONLY its own.

    A replayed old decision carries the winner's saved result; by the time it
    replays, the same journal path may belong to a newer in-flight or
    committed publication. Identity mismatch or an unreadable journal leaves
    the file for its owner. A legacy result without a recorded identity only
    removes a journal that also lacks one.
    """
    journal = result.get("publication_journal")
    if not isinstance(journal, str):
        return
    path = Path(journal)
    try:
        current = json.loads(path.read_text())
    except FileNotFoundError:
        return
    except (OSError, ValueError):
        return  # unreadable: never guess ownership
    if not isinstance(current, dict):
        return  # decodable but non-object: no usable identity, leave it
    journal_identity = str(current.get("identity") or current.get("key") or "")
    result_identity = str(result.get("publication_identity") or "")
    if journal_identity == result_identity:
        path.unlink(missing_ok=True)

def _atomic_write(path: Path, content: str) -> None:
    """Replace a regular file without following attacker-controlled links."""
    if path.is_symlink():
        raise ContractPublicationError(f"refusing symlink publication path: {path.name}")
    directory = path.parent
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix=".publication-", dir=directory)
    try:
        os.fchmod(fd, mode)
        if path.exists():
            metadata = path.stat()
            os.fchown(fd, metadata.st_uid, metadata.st_gid)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
        # replace unlinks a malicious final symlink rather than following it.
        os.replace(temporary, path)
        dirfd = os.open(directory, os.O_RDONLY); os.fsync(dirfd); os.close(dirfd)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
