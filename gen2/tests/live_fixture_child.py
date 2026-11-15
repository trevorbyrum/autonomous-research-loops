"""The live-order executor child for the L1+L2 integration test: the production child with the fixture agent, which then leaves what
`DockerCLI.run` leaves at a confirmed end (`docker-complete.json` for the plan's origin) unless the marker file `no-end` sits in the station root. Not collected
as tests; no container and no provider."""
import sys
from pathlib import Path

from gen2.app import child, live
from gen2.supervisor import jobs
from gen2.tests.offline_agent import OfflineAgent

if __name__ == "__main__":
    directory = Path(sys.argv[1])
    job = jobs.Job(directory.parent.parent, directory.parent.name)
    invalid = (directory.parent.parent.parent / "invalid-judgment").exists()
    agent = OfflineAgent({("research_pass", "scope"): lambda work: {}}) if invalid else OfflineAgent()
    code = child.main(sys.argv[1:], agent=agent)
    if job.read("docker-plan.json") is not None and not (directory.parent.parent.parent / "no-end").exists():   # only a live job has a plan
        batch = live.ScratchBatch(directory)   # a refused judgment still leaves the backend's own evidence set aside, as DockerCLI.run does
        refs = [batch.stage(b"2e1 complete", "text/plain"), batch.stage(b'{"usage": "recorded"}', "application/json")] if invalid else []
        job.write("docker-complete.json", {"origin": job.read("docker-plan.json")["origin"], "refs": refs, "disposition": {"disposition": "unknown", "reason": "fixture"}})
    sys.exit(code)
