"""Serve site/ over HTTP for local checking.

Not part of the build. It exists because the pages share state through
localStorage, which browsers scope to an ORIGIN -- so a file:// or data: preview
cannot exercise the theme carrying from one page to the next at all.

`python3 -m http.server --directory site` cannot be used from the harness: its
argparse default calls os.getcwd(), which is not permitted for the spawned
process, so the module fails before it parses anything.
"""

import functools
import http.server
import os
import socketserver
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'site')
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777

os.chdir(ROOT)
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(('127.0.0.1', PORT), handler) as httpd:
    print(f'serving {ROOT} on http://127.0.0.1:{PORT}')
    sys.stdout.flush()
    httpd.serve_forever()
