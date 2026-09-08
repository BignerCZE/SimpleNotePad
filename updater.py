import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import keyring

API_ROOT = "https://api.github.com"
TOKEN_SERVICE = "AutoSaveNotepad GitHub"
ASSET_NAME = "AutoSaveNotepad.exe"
HASH_ASSET_NAME = "AutoSaveNotepad.exe.sha256"


class UpdateError(RuntimeError):
    pass


def version_tuple(value):
    value = str(value or "").strip().lower().lstrip("v")
    main = value.split("-", 1)[0]
    parts = []
    for piece in main.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits or 0))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:4])


class GitHubUpdater:
    def __init__(self, owner, repo, current_version, app_name):
        self.owner = owner
        self.repo = repo
        self.current_version = current_version
        self.app_name = app_name
        self.token_account = f"{owner}/{repo}"

    def save_token(self, token):
        try:
            keyring.set_password(TOKEN_SERVICE, self.token_account, token)
        except Exception as e:
            raise UpdateError(f"Token se nepodařilo bezpečně uložit:\n{e}") from e

    def get_token(self):
        try:
            return keyring.get_password(TOKEN_SERVICE, self.token_account)
        except Exception as e:
            raise UpdateError(f"Token se nepodařilo načíst:\n{e}") from e

    def _request(self, url, accept="application/vnd.github+json"):
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"{self.app_name}/{self.current_version}",
        }
        token = self.get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            return urllib.request.urlopen(req, timeout=20)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise UpdateError("GitHub přístup byl odmítnut. Zkontroluj token.") from e
            if e.code == 404:
                raise UpdateError("Repozitář/Release není dostupný. U private repo nastav token.") from e
            raise UpdateError(f"GitHub vrátil HTTP {e.code}.") from e
        except urllib.error.URLError as e:
            raise UpdateError(f"Nepodařilo se připojit ke GitHubu: {e.reason}") from e

    def _json(self, url):
        with self._request(url) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_access(self):
        data = self._json(f"{API_ROOT}/repos/{self.owner}/{self.repo}")
        return data.get("full_name", "").lower() == f"{self.owner}/{self.repo}".lower()

    def check_latest(self):
        release = self._json(f"{API_ROOT}/repos/{self.owner}/{self.repo}/releases/latest")
        tag = release.get("tag_name") or ""
        if version_tuple(tag) <= version_tuple(self.current_version):
            return None

        assets = {a.get("name"): a for a in release.get("assets", [])}
        exe = assets.get(ASSET_NAME)
        sha = assets.get(HASH_ASSET_NAME)
        if not exe or not sha:
            raise UpdateError("Release neobsahuje EXE a SHA-256 soubor.")

        return {
            "version": tag.lstrip("vV"),
            "tag": tag,
            "notes": release.get("body") or "",
            "exe_api_url": exe["url"],
            "hash_api_url": sha["url"],
        }

    def _download(self, api_url, path):
        with self._request(api_url, "application/octet-stream") as r, open(path, "wb") as f:
            while True:
                block = r.read(262144)
                if not block:
                    break
                f.write(block)

    def download_and_verify(self, release):
        folder = Path(tempfile.gettempdir()) / "autosave_notepad_update"
        folder.mkdir(parents=True, exist_ok=True)
        exe = folder / f"AutoSaveNotepad-{release['version']}.exe"
        sha = folder / f"AutoSaveNotepad-{release['version']}.sha256"
        self._download(release["exe_api_url"], exe)
        self._download(release["hash_api_url"], sha)

        expected = sha.read_text(encoding="utf-8").strip().split()[0].lower()
        digest = hashlib.sha256()
        with open(exe, "rb") as f:
            for block in iter(lambda: f.read(1048576), b""):
                digest.update(block)
        if digest.hexdigest().lower() != expected:
            try:
                exe.unlink()
            except OSError:
                pass
            raise UpdateError("Aktualizace neprošla kontrolou SHA-256.")
        return exe

    def install_after_exit(self, new_exe):
        if not getattr(sys, "frozen", False):
            raise UpdateError("Instalace je dostupná pouze v EXE verzi.")

        old = Path(sys.executable).resolve()
        new = Path(new_exe).resolve()
        script = new.parent / "install_update.cmd"

        cmd = (
            "@echo off\n"
            "setlocal\n"
            f'set "OLD={old}"\n'
            f'set "NEW={new}"\n'
            f'set "PID={os.getpid()}"\n'
            ":waitloop\n"
            'tasklist /FI "PID eq %PID%" 2>NUL | find /I "%PID%" >NUL\n'
            "if not errorlevel 1 (\n"
            "  timeout /t 1 /nobreak >NUL\n"
            "  goto waitloop\n"
            ")\n"
            'copy /Y "%NEW%" "%OLD%" >NUL\n'
            "if errorlevel 1 exit /b 1\n"
            'set "PYINSTALLER_RESET_ENVIRONMENT=1"\n'
            'set "_PYI_ARCHIVE_FILE="\n'
            'set "_PYI_APPLICATION_HOME_DIR="\n'
            'set "_PYI_PARENT_PROCESS_LEVEL="\n'
            'set "_PYI_SPLASH_IPC="\n'
            'start "" "%OLD%"\n'
            'del "%NEW%" >NUL 2>&1\n'
            'del "%~f0" >NUL 2>&1\n'
        )
        try:
            script.write_text(cmd, encoding="utf-8")
            env = os.environ.copy()
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"

            subprocess.Popen(
                ["cmd.exe", "/c", str(script)],
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
            )
        except OSError as e:
            raise UpdateError(f"Nepodařilo se spustit instalátor:\n{e}") from e
