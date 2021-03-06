# (c) 2005 Ian Bicking and contributors; written for Paste
# (http://pythonpaste.org) Licensed under the MIT license:
# http://www.opensource.org/licenses/mit-license.php
#
# For discussion of daemonizing:
# http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/278731
#
# Code taken also from QP: http://www.mems-exchange.org/software/qp/ From
# lib/site.py

import optparse
import os
import re
import sys
import textwrap
import threading
import time
import webbrowser

import hupper
from paste.deploy import (
    loadapp,
    loadserver,
)
from paste.deploy.loadwsgi import (
    SERVER,
    loadcontext,
)

from pyramid.compat import PY2

from pyramid.scripts.common import parse_vars
from pyramid.scripts.common import setup_logging

def main(argv=sys.argv, quiet=False):
    command = PServeCommand(argv, quiet=quiet)
    return command.run()

class PServeCommand(object):

    usage = '%prog config_uri [var=value]'
    description = """\
    This command serves a web application that uses a PasteDeploy
    configuration file for the server and application.

    You can also include variable assignments like 'http_port=8080'
    and then use %(http_port)s in your config files.
    """
    default_verbosity = 1

    parser = optparse.OptionParser(
        usage,
        description=textwrap.dedent(description)
        )
    parser.add_option(
        '-n', '--app-name',
        dest='app_name',
        metavar='NAME',
        help="Load the named application (default main)")
    parser.add_option(
        '-s', '--server',
        dest='server',
        metavar='SERVER_TYPE',
        help="Use the named server.")
    parser.add_option(
        '--server-name',
        dest='server_name',
        metavar='SECTION_NAME',
        help=("Use the named server as defined in the configuration file "
              "(default: main)"))
    parser.add_option(
        '--reload',
        dest='reload',
        action='store_true',
        help="Use auto-restart file monitor")
    parser.add_option(
        '--reload-interval',
        dest='reload_interval',
        default=1,
        help=("Seconds between checking files (low number can cause "
              "significant CPU usage)"))
    parser.add_option(
        '-b', '--browser',
        dest='browser',
        action='store_true',
        help="Open a web browser to server url")
    parser.add_option(
        '-v', '--verbose',
        default=default_verbosity,
        dest='verbose',
        action='count',
        help="Set verbose level (default " + str(default_verbosity) + ")")
    parser.add_option(
        '-q', '--quiet',
        action='store_const',
        const=0,
        dest='verbose',
        help="Suppress verbose output")

    _scheme_re = re.compile(r'^[a-z][a-z]+:', re.I)

    def __init__(self, argv, quiet=False):
        self.options, self.args = self.parser.parse_args(argv[1:])
        if quiet:
            self.options.verbose = 0

    def out(self, msg): # pragma: no cover
        if self.options.verbose > 0:
            print(msg)

    def get_options(self):
        restvars = self.args[1:]
        return parse_vars(restvars)

    def run(self):  # pragma: no cover
        if not self.args:
            self.out('You must give a config file')
            return 2
        app_spec = self.args[0]

        vars = self.get_options()
        app_name = self.options.app_name

        if not self._scheme_re.search(app_spec):
            app_spec = 'config:' + app_spec
        server_name = self.options.server_name
        if self.options.server:
            server_spec = 'egg:pyramid'
            assert server_name is None
            server_name = self.options.server
        else:
            server_spec = app_spec
        base = os.getcwd()

        # do not open the browser on each reload so check hupper first
        if self.options.browser and not hupper.is_active():
            def open_browser():
                context = loadcontext(
                    SERVER, app_spec, name=server_name, relative_to=base,
                    global_conf=vars)
                url = 'http://127.0.0.1:{port}/'.format(**context.config())
                time.sleep(1)
                webbrowser.open(url)
            t = threading.Thread(target=open_browser)
            t.setDaemon(True)
            t.start()

        if self.options.reload and not hupper.is_active():
            if self.options.verbose > 1:
                self.out('Running reloading file monitor')
            hupper.start_reloader(
                'pyramid.scripts.pserve.main',
                reload_interval=int(self.options.reload_interval),
                verbose=self.options.verbose,
            )
            return 0

        if hupper.is_active():
            reloader = hupper.get_reloader()
            if app_spec.startswith('config:'):
                reloader.watch_files([app_spec[len('config:'):]])

        log_fn = app_spec
        if log_fn.startswith('config:'):
            log_fn = app_spec[len('config:'):]
        elif log_fn.startswith('egg:'):
            log_fn = None
        if log_fn:
            log_fn = os.path.join(base, log_fn)
            setup_logging(log_fn, global_conf=vars)

        server = self.loadserver(server_spec, name=server_name,
                                 relative_to=base, global_conf=vars)

        app = self.loadapp(
            app_spec, name=app_name, relative_to=base, global_conf=vars)

        if self.options.verbose > 0:
            if hasattr(os, 'getpid'):
                msg = 'Starting server in PID %i.' % os.getpid()
            else:
                msg = 'Starting server.'
            self.out(msg)

        def serve():
            try:
                server(app)
            except (SystemExit, KeyboardInterrupt) as e:
                if self.options.verbose > 1:
                    raise
                if str(e):
                    msg = ' ' + str(e)
                else:
                    msg = ''
                self.out('Exiting%s (-v to see traceback)' % msg)

        serve()

    def loadapp(self, app_spec, name, relative_to, **kw): # pragma: no cover
        return loadapp(app_spec, name=name, relative_to=relative_to, **kw)

    def loadserver(self, server_spec, name, relative_to, **kw):# pragma:no cover
        return loadserver(
            server_spec, name=name, relative_to=relative_to, **kw)

# For paste.deploy server instantiation (egg:pyramid#wsgiref)
def wsgiref_server_runner(wsgi_app, global_conf, **kw): # pragma: no cover
    from wsgiref.simple_server import make_server
    host = kw.get('host', '0.0.0.0')
    port = int(kw.get('port', 8080))
    server = make_server(host, port, wsgi_app)
    print('Starting HTTP server on http://%s:%s' % (host, port))
    server.serve_forever()

# For paste.deploy server instantiation (egg:pyramid#cherrypy)
def cherrypy_server_runner(
        app, global_conf=None, host='127.0.0.1', port=None,
        ssl_pem=None, protocol_version=None, numthreads=None,
        server_name=None, max=None, request_queue_size=None,
        timeout=None
        ): # pragma: no cover
    """
    Entry point for CherryPy's WSGI server

    Serves the specified WSGI app via CherryPyWSGIServer.

    ``app``

        The WSGI 'application callable'; multiple WSGI applications
        may be passed as (script_name, callable) pairs.

    ``host``

        This is the ipaddress to bind to (or a hostname if your
        nameserver is properly configured).  This defaults to
        127.0.0.1, which is not a public interface.

    ``port``

        The port to run on, defaults to 8080 for HTTP, or 4443 for
        HTTPS. This can be a string or an integer value.

    ``ssl_pem``

        This an optional SSL certificate file (via OpenSSL) You can
        generate a self-signed test PEM certificate file as follows:

            $ openssl genrsa 1024 > host.key
            $ chmod 400 host.key
            $ openssl req -new -x509 -nodes -sha1 -days 365  \\
                          -key host.key > host.cert
            $ cat host.cert host.key > host.pem
            $ chmod 400 host.pem

    ``protocol_version``

        The protocol used by the server, by default ``HTTP/1.1``.

    ``numthreads``

        The number of worker threads to create.

    ``server_name``

        The string to set for WSGI's SERVER_NAME environ entry.

    ``max``

        The maximum number of queued requests. (defaults to -1 = no
        limit).

    ``request_queue_size``

        The 'backlog' argument to socket.listen(); specifies the
        maximum number of queued connections.

    ``timeout``

        The timeout in seconds for accepted connections.
    """
    is_ssl = False
    if ssl_pem:
        port = port or 4443
        is_ssl = True

    if not port:
        if ':' in host:
            host, port = host.split(':', 1)
        else:
            port = 8080
    bind_addr = (host, int(port))

    kwargs = {}
    for var_name in ('numthreads', 'max', 'request_queue_size', 'timeout'):
        var = locals()[var_name]
        if var is not None:
            kwargs[var_name] = int(var)

    from cherrypy import wsgiserver

    server = wsgiserver.CherryPyWSGIServer(bind_addr, app,
                                           server_name=server_name, **kwargs)
    if ssl_pem is not None:
        if PY2:
            server.ssl_certificate = server.ssl_private_key = ssl_pem
        else:
            # creates wsgiserver.ssl_builtin as side-effect
            wsgiserver.get_ssl_adapter_class()
            server.ssl_adapter = wsgiserver.ssl_builtin.BuiltinSSLAdapter(
                ssl_pem, ssl_pem)

    if protocol_version:
        server.protocol = protocol_version

    try:
        protocol = is_ssl and 'https' or 'http'
        if host == '0.0.0.0':
            print('serving on 0.0.0.0:%s view at %s://127.0.0.1:%s' %
                  (port, protocol, port))
        else:
            print('serving on %s://%s:%s' % (protocol, host, port))
        server.start()
    except (KeyboardInterrupt, SystemExit):
        server.stop()

    return server

if __name__ == '__main__': # pragma: no cover
    sys.exit(main() or 0)
