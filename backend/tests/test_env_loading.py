"""Regression test: backend/.env must actually be read.

python-dotenv was a declared dependency but nothing called it, so a correctly
written .env was ignored and SECRET_KEY stayed empty. That presented to the user
as accounts simply not working, with no useful error.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_env_file_is_loaded_into_settings(tmp_path):
    env = BACKEND / ".env"
    existing = env.read_text() if env.exists() else None
    env.write_text("SECRET_KEY=from-the-env-file\nADMIN_USERNAME=env_admin\n")
    try:
        # A fresh interpreter with the test harness's own SECRET_KEY removed,
        # otherwise the real environment correctly wins over the file.
        import os
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("SECRET_KEY", "ADMIN_USERNAME")}
        out = subprocess.run(
            [sys.executable, "-c", textwrap.dedent("""
                import sys; sys.path.insert(0, '.')
                from app.config import get_settings
                s = get_settings()
                print(s.secret_key, s.admin_username, sep='|')
            """)],
            cwd=BACKEND, capture_output=True, text=True, timeout=60, env=clean,
        )
        assert out.returncode == 0, out.stderr
        secret, admin = out.stdout.strip().split("|")
        assert secret == "from-the-env-file"
        assert admin == "env_admin"
    finally:
        if existing is None:
            env.unlink(missing_ok=True)
        else:
            env.write_text(existing)


def test_real_environment_still_wins_over_the_file(tmp_path):
    env = BACKEND / ".env"
    existing = env.read_text() if env.exists() else None
    env.write_text("SECRET_KEY=from-the-file\n")
    try:
        import os
        e = dict(os.environ, SECRET_KEY="from-the-real-environment")
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0,'.');"
             "from app.config import get_settings; print(get_settings().secret_key)"],
            cwd=BACKEND, capture_output=True, text=True, env=e, timeout=60,
        )
        assert out.stdout.strip() == "from-the-real-environment"
    finally:
        if existing is None:
            env.unlink(missing_ok=True)
        else:
            env.write_text(existing)
