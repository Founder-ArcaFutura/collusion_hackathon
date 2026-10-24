"""Exercise the Windows native-output path without Modal or inference."""

import base64
import os
import shutil
import subprocess
import sys

import pytest


def test_host_cli_direct_entrypoint_has_no_duplicate_module_warning():
    result = subprocess.run(
        [sys.executable, '-X', 'utf8', '-c',
         'from poseidon_compute.hosted_model import main; main()', '--help'],
        capture_output=True, encoding='utf-8', timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert '--run-timeout' in result.stdout
    assert 'found in sys.modules' not in result.stderr


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell encoding regression')
def test_modal_style_unicode_survives_windows_powershell_tee(tmp_path):
    powershell = shutil.which('powershell.exe')
    if powershell is None:
        pytest.skip('Windows PowerShell is unavailable')
    log = tmp_path / 'host.log'
    # Use the same native Python -> merged stderr -> Tee-Object path as the
    # launcher, including the legacy Rich renderer from the reported traceback.
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    program = (
        'import sys; from rich.console import Console; '
        'assert sys.stdout.encoding.lower() == "utf-8"; '
        'Console(legacy_windows=True).print("\\u2713 Initialized. \\u2014 ready"); '
        'print("DIAGNOSTIC_LOG_COMPLETE")'
    )
    script = (
        '$ErrorActionPreference = "Continue"; '
        '[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); '
        # PS 5 strips nested double quotes from native -c arguments; the
        # launcher entrypoint has none. Encode this more complex fixture.
        f'& {quote(sys.executable)} -X utf8 -c '
        + quote("exec(bytes.fromhex('" + program.encode().hex() + "').decode())") + ' 2>&1 '
        f'| Tee-Object -FilePath {quote(log)}; exit $LASTEXITCODE'
    )
    env = os.environ.copy()
    env.pop('PYTHONIOENCODING', None)
    env['PYTHONUTF8'] = '0'  # The explicit launcher flag must win.
    result = subprocess.run(
        [powershell, '-NoProfile', '-NonInteractive', '-EncodedCommand',
         base64.b64encode(script.encode('utf-16-le')).decode('ascii')],
        capture_output=True, timeout=30, env=env,
    )
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    raw = log.read_bytes()
    text = raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig')
    assert 'DIAGNOSTIC_LOG_COMPLETE' in text
    assert '\u2713 Initialized. \u2014 ready' in text
    assert 'UnicodeEncodeError' not in text
