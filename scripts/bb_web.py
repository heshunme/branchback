#!/usr/bin/env python3
"""Read-only, loopback-only viewer for Branchback state."""
import argparse
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from bb_storage import Error, Store, identifier, load_json

ASSETS = Path(__file__).with_name('web')


class Viewer:
    def __init__(self, home=None):
        self.home = Path(home or os.environ.get('BRANCHBACK_HOME', '~/.branchback')).expanduser().resolve()

    def registry(self):
        # Listing must work even when repositories have moved or no longer exist.
        return Store(home=self.home, project_root=ASSETS).registry()

    def project(self, project_id):
        identifier(project_id)
        relative = 'projects/' + project_id
        if relative not in self.registry().values():
            raise Error('Unknown project')
        path = (self.home / relative).resolve()
        if not path.is_relative_to(self.home) or not path.is_dir():
            raise Error('Project directory is missing or outside the state root')
        return path

    def tree(self, project_id, tree_id):
        project = self.project(project_id)
        path = (project / 'trees' / (identifier(tree_id) + '.json')).resolve()
        if not path.is_relative_to(project):
            raise Error('Tree is outside the project directory')
        tree = load_json(path)
        if (not isinstance(tree, dict) or tree.get('schema') not in (1, 2)
                or tree.get('id') != tree_id or not isinstance(tree.get('nodes'), dict)
                or not isinstance(tree.get('sessions'), dict)
                or tree.get('root') not in tree['nodes']):
            raise Error('Unsupported or invalid exploration state')
        return tree

    def projects(self):
        return [{'id': Path(relative).name, 'repository': key}
                for key, relative in self.registry().items()]

    def trees(self, project_id):
        output = []
        for path in sorted((self.project(project_id) / 'trees').glob('*.json')):
            try:
                tree = self.tree(project_id, path.stem)
                output.append({'id': tree['id'], 'question': tree['nodes'][tree['root']]['question'],
                               'status': tree.get('status'), 'updated_at': tree.get('updated_at')})
            except (Error, KeyError, TypeError) as exc:
                output.append({'id': path.stem, 'error': str(exc)})
        return output


def handler_for(viewer):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            try:
                if url.path == '/api/projects':
                    value = viewer.projects()
                elif url.path == '/api/trees':
                    value = viewer.trees(query.get('project', [''])[0])
                elif url.path == '/api/tree':
                    value = viewer.tree(query.get('project', [''])[0], query.get('tree', [''])[0])
                elif url.path in ('/', '/app.js', '/style.css'):
                    filename, content_type = {'/': ('index.html', 'text/html'),
                        '/app.js': ('app.js', 'text/javascript'),
                        '/style.css': ('style.css', 'text/css')}[url.path]
                    self.reply(200, (ASSETS / filename).read_bytes(), content_type)
                    return
                else:
                    self.reply(404, b'Not found', 'text/plain')
                    return
                self.reply(200, json.dumps(value, ensure_ascii=False).encode(), 'application/json')
            except (Error, OSError, ValueError, KeyError, TypeError) as exc:
                self.reply(400, json.dumps({'error': str(exc)}, ensure_ascii=False).encode(), 'application/json')

        def reply(self, status, body, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'; object-src 'none'")
            self.end_headers()
            self.wfile.write(body)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', help='State root (default BRANCHBACK_HOME or ~/.branchback)')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(Viewer(args.home)))
    print(f'Branchback viewer: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
