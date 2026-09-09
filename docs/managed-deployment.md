# Managed controller deployment and recovery

This is an explicit cutover procedure. Implementation and tests do not alter the
live portfolio, choose production model pins, or restart running workers.
The old same-user worker services cannot enforce the managed filesystem boundary.

## Identities and files

Run the trusted controller and station supervisors under an identity permitted to
set the execution UID/GID (normally a root-owned system service). Install their
Python environment and executable code in a directory the execution account cannot
write or replace. Research, checkpoint, and discovery provider processes run as a
separate unprivileged execution account. Give that account its own writable home
and provider authentication. Do not grant it sudo or controller-group membership.
Provider executables must be installed where that account can traverse and execute
them. The child receives its account's HOME/USER/LOGNAME.

The controller database and bootstrap access file are under `state/`, mode 0700;
`access.json` is mode 0600. Approved TOPIC, AUTHORITY and SEMANTIC-STATE files are
controller-owned. Topic directories remain controller-owned, group-writable with
the sticky bit; working evidence descendants belong to the execution account.
This permits evidence edits but prevents replacing approved inventory by unlinking
or renaming its read-only file. Semantic assessment commands retain the existing
scientific validator and travel through the authenticated controller socket.

Unix peer credentials identify operator and execution callers. Each execution also
needs a capability bound to its current topic, lease generation and execution
kind. Supplying an `actor` field never grants operator authority. Finished or
superseded leases cannot authorize another state write.

## Reviewable cutover inputs

1. Drain existing workers at safe boundaries and record any remaining live PID and
   restart state. Back up queue/station state and approved topic content. Migration
   refuses running legacy records; it does not invent adoption or kill children.
2. Prepare the exact migration JSON described in [managed-stations.md](managed-stations.md).
   Set `active_count` to 0 for the protected bootstrap. Specify the five station
   pairs, monotonic intervals, full registered profiles, completed research count
   baselines, and known checkpoint/deepening history. Do not use attempt totals as
   successful research counts. Review the no-write `control-migrate` result first.
3. Apply that same migration input while drained. Keep the original JSON as an
   archived input. Managed reads/writes use `control.sqlite3`; legacy queue/station
   JSON is no longer an execution authority.
4. Create a reviewed access bootstrap JSON outside the research-owned tree:

   ```json
   {
     "schema_version": 1,
     "operator_uids": [1000],
     "agent_uid": 2001,
     "agent_gid": 2001,
     "socket_path": "/run/research-loops/control.sock"
   }
   ```

   The IDs above are examples; use the actual provisioned accounts. Operators and
   execution UID must differ, and the execution UID cannot be root. The socket's
   parent directory must belong to the controller and be traversable by clients,
   without group/world write access.
5. As the trusted supervisor, run:

   ```sh
   research-loops-deployment --root /var/lib/research-loops --access-file /etc/research-loops/access.json --apply
   research-loops-deployment --root /var/lib/research-loops
   ```

   The second invocation is read-only verification. Permission provisioning refuses
   active capacity/current executions and symlinked topic content. It changes
   ownership/modes, never approved text or research counts. New managed drafts and
   approved topics receive the same protection from the intake publisher.
6. Start the controller, then trusted supervisors with `run --worker station-1`
   through `station-5` as required. A separate supervisor with `--lanes intake`
   runs the capped discovery lane. Use system services, not the existing same-user
   service template. Set `RESEARCH_LOOP_CONTROLLER_SOCKET` for operator CLI/MCP
   clients. Keep `state/` inaccessible to execution processes.
7. Apply the reviewed active count through the controller. Inspect configured
   capacity, current/desired assignments, draining status, counts and review holds.
   A manually started higher station cannot acquire capacity. A configured provider
   failure is reported; the launcher never retries under the controller UID.

## Publication recovery

A pending intake or checkpoint decision stores the complete validated publication
before writing approved files. The topic stays ineligible while publication is
pending. Retry the identical request ID and payload after interruption; its original
revision is accepted because that durable intent owns the operation. A different
payload under the same ID is an error. File publication is recoverable, not falsely
described as a transaction spanning SQLite and multiple filesystem renames.

Checkpoint publication journals are removed only after the decision transaction
commits. A cleanup failure does not repeat an approved change: replay returns the
committed result and cleans the journal. Partial decisions retain the review hold
and list unresolved proposal IDs. Final resolution restores eligibility of the
existing queue item, preserving its current canonical priority and next research
ordinal. An unrelated manual pause remains in force.

Before reverting a cutover, drain managed executions and preserve the database and
published files together. Reverting only the database can restore an obsolete
inventory lock; reverting only code must not silently reopen legacy JSON writes.
