import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen, Request
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from bb_engine import Engine
from bb_storage import Store, Error
from bb_web import Viewer, handler_for


class ViewerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'state'
        self.viewer = Viewer(self.home)

    def populate(self):
        store = Store(self.home, project_root=self.root)
        context = Engine(store).start({'goal': 'Explore <script>alert(1)</script>', 'scope': 'viewer', 'sources': ['test']})
        return self.viewer.projects()[0]['id'], context['tree']

    def test_empty_read_creates_nothing(self):
        self.assertEqual(self.viewer.projects(), [])
        self.assertFalse(self.home.exists())

    def test_existing_state_and_missing_repository_are_read_only(self):
        project, tree_id = self.populate()
        before = {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        self.assertEqual(len(self.viewer.trees(project)), 1)
        self.assertEqual(self.viewer.tree(project, tree_id)['id'], tree_id)
        self.assertEqual(before, {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()})
        with self.assertRaises(Error):
            self.viewer.tree(project, '../../projects')
        with self.assertRaises(Error):
            self.viewer.trees('unknown')

    def test_http_routes_and_write_rejection(self):
        project, tree_id = self.populate()
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.viewer))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        with urlopen(base + '/') as response:
            self.assertIn(b'Branchback', response.read())
            self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        with urlopen(base + f'/api/tree?project={project}&tree={tree_id}') as response:
            self.assertEqual(json.load(response)['id'], tree_id)
        for path, method, status in [('/../../projects.json', 'GET', 404), ('/api/tree', 'POST', 501), ('/api/tree?project=..&tree=x', 'GET', 400)]:
            with self.assertRaises(HTTPError) as caught:
                urlopen(Request(base + path, method=method))
            self.assertEqual(caught.exception.code, status)

    def test_corrupt_tree_does_not_hide_other_trees(self):
        project, tree_id = self.populate()
        (self.home / 'projects' / project / 'trees' / 'broken.json').write_text('{')
        trees = self.viewer.trees(project)
        self.assertEqual(len(trees), 2)
        self.assertTrue(any(t.get('error') for t in trees))
        self.assertTrue(any(t['id'] == tree_id for t in trees))


if __name__ == '__main__':
    unittest.main()
