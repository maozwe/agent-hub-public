from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier
import tempfile
import unittest
from hub import Hub


class AutoAssignmentTests(unittest.TestCase):
    def test_competing_agents_claim_one_task_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            database=str(Path(tmp)/'hub.sqlite3')
            with closing(Hub(database)) as hub:
                for agent in ('claude','codex','cursor'): hub.register_agent(agent,True)
                task=hub.create_task('owner/repo','Read')
            barrier=Barrier(3)
            def claim(agent):
                with closing(Hub(database)) as hub:
                    barrier.wait(timeout=5)
                    return hub.claim(agent,auto_assign=True)
            with ThreadPoolExecutor(max_workers=3) as pool:
                results=list(pool.map(claim,('claude','codex','cursor')))
            winners=[r for r in results if r]
            self.assertEqual(len(winners),1)
            self.assertEqual(winners[0]['id'],task['id'])

    def test_busy_explicit_and_direct_assignment_boundaries(self):
        with closing(Hub()) as hub:
            for agent in ('claude','codex','codex-direct'): hub.register_agent(agent,True)
            unassigned=hub.create_task('owner/repo','Unassigned',1)
            explicit=hub.create_task('owner/repo','Explicit',3);hub.assign(explicit['id'],'claude')
            self.assertIsNone(hub.claim('codex-direct'))
            self.assertEqual(hub.claim('claude',auto_assign=True)['id'],explicit['id'])
            hub.transition(explicit['id'],'claude','working');hub.block(explicit['id'],'claude','Manual session active')
            self.assertIsNone(hub.claim('claude',auto_assign=True))
            self.assertEqual(hub.claim('codex',auto_assign=True)['id'],unassigned['id'])
