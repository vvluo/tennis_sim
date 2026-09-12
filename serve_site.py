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
class Handler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler serves .html as bare 'text/html' with no charset,
    so a browser guesses -- and guesses Latin-1, which renders every UTF-8 em
    dash as 'a EUR "'. GitHub Pages sends the charset; this now does too, so what
    is checked locally is what ships."""

    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      '.html': 'text/html; charset=utf-8',
                      '.js': 'text/javascript; charset=utf-8',
                      '.json': 'application/json; charset=utf-8'}


handler = functools.partial(Handler, directory=ROOT)
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(('127.0.0.1', PORT), handler) as httpd:
    print(f'serving {ROOT} on http://127.0.0.1:{PORT}')
    sys.stdout.flush()
    httpd.serve_forever()
