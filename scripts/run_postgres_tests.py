"""Run tests against a temporary PostgreSQL cluster; never touches the app database.
Usage: PG_BINDIR=/path/to/postgres/bin python scripts/run_postgres_tests.py
The server listens only on a private Unix socket and is stopped on exit.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlencode


def main():
    bindir = os.environ.get('PG_BINDIR', '')
    binaries = {}
    for name in ('initdb', 'pg_ctl'):
        binary = str(Path(bindir) / name) if bindir else shutil.which(name)
        if not binary or not Path(binary).is_file():
            raise SystemExit('Install PostgreSQL and set PG_BINDIR to its bin directory.')
        binaries[name] = binary
    with tempfile.TemporaryDirectory(prefix='fortune-pg-', dir='/tmp') as folder:
        root = Path(folder)
        data = root / 'data'
        socket = root / 'socket'
        socket.mkdir(mode=0o700)
        subprocess.run([binaries['initdb'], '-D', str(data), '-A', 'trust',
                        '-U', 'fortune_test', '--no-locale', '-E', 'UTF8'], check=True, stdout=subprocess.DEVNULL)
        started = False
        try:
            subprocess.run([binaries['pg_ctl'], '-D', str(data), '-l', str(root / 'server.log'),
                            '-o', f"-F -h '' -k {socket}", '-w', 'start'], check=True)
            started = True
            env = {**os.environ, 'FORTUNE_TEST_DATABASE_URL':
                   'postgresql://fortune_test@/postgres?' + urlencode({'host': str(socket)})}
            return subprocess.run([sys.executable, '-m', 'pytest', '-q'], env=env,
                                  cwd=Path(__file__).resolve().parent.parent).returncode
        finally:
            if started:
                subprocess.run([binaries['pg_ctl'], '-D', str(data), '-m', 'immediate', '-w', 'stop'], check=True)


if __name__ == '__main__':
    sys.exit(main())
