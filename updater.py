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
UPDATE_DIR = Path(tempfile.gettempdir()) / "autosave_notepad_update"
UPDATE_LOG = UPDATE_DIR / "update.log"


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


def _ps_quote(value):
    """Quote a string for a single-quoted PowerShell literal."""
    return str(value).replace("'", "''")


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
            return urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise UpdateError("GitHub přístup byl odmítnut. Zkontroluj token.") from e
            if e.code == 404:
                raise UpdateError(
                    "Repozitář/Release není dostupný. U private repo nastav token."
                ) from e
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
        release = self._json(
            f"{API_ROOT}/repos/{self.owner}/{self.repo}/releases/latest"
        )
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

    def _download(self, api_url, path, progress_callback=None, start=0, end=100):
        with self._request(api_url, "application/octet-stream") as r, open(path, "wb") as f:
            raw_length = r.headers.get("Content-Length")
            try:
                total = int(raw_length) if raw_length else 0
            except ValueError:
                total = 0

            downloaded = 0
            while True:
                block = r.read(262144)
                if not block:
                    break
                f.write(block)
                downloaded += len(block)
                if progress_callback and total > 0:
                    fraction = min(1.0, downloaded / total)
                    pct = start + (end - start) * fraction
                    progress_callback(pct)

        if progress_callback:
            progress_callback(end)

    def download_and_verify(self, release, progress_callback=None, phase_callback=None):
        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        exe = UPDATE_DIR / f"AutoSaveNotepad-{release['version']}.exe"
        sha = UPDATE_DIR / f"AutoSaveNotepad-{release['version']}.sha256"

        if phase_callback:
            phase_callback("Stahuji novou verzi programu…")
        if progress_callback:
            progress_callback(8)
        self._download(
            release["exe_api_url"],
            exe,
            progress_callback=progress_callback,
            start=8,
            end=72,
        )

        if phase_callback:
            phase_callback("Stahuji kontrolní součet SHA-256…")
        self._download(
            release["hash_api_url"],
            sha,
            progress_callback=progress_callback,
            start=72,
            end=82,
        )

        if phase_callback:
            phase_callback("Ověřuji integritu staženého souboru…")
        if progress_callback:
            progress_callback(84)

        try:
            expected = sha.read_text(encoding="utf-8").strip().split()[0].lower()
        except (OSError, IndexError) as e:
            raise UpdateError("Kontrolní SHA-256 soubor je neplatný.") from e

        digest = hashlib.sha256()
        size = max(1, exe.stat().st_size)
        read_bytes = 0
        with open(exe, "rb") as f:
            for block in iter(lambda: f.read(1048576), b""):
                digest.update(block)
                read_bytes += len(block)
                if progress_callback:
                    progress_callback(84 + 10 * min(1.0, read_bytes / size))

        actual = digest.hexdigest().lower()
        if actual != expected:
            try:
                exe.unlink()
            except OSError:
                pass
            raise UpdateError(
                "Aktualizace neprošla kontrolou SHA-256. Instalace byla zrušena."
            )

        if progress_callback:
            progress_callback(95)
        if phase_callback:
            phase_callback("Aktualizace je ověřena. Připravuji instalaci…")
        return exe

    def _check_install_location(self, current_exe):
        """Fail early if the running EXE directory cannot be written."""
        folder = current_exe.parent
        probe = folder / f".autosave_notepad_write_test_{os.getpid()}.tmp"
        try:
            probe.write_text("test", encoding="utf-8")
            probe.unlink()
        except OSError as e:
            raise UpdateError(
                "Program nemá oprávnění přepsat vlastní EXE soubor.\n\n"
                f"Umístění: {folder}\n\n"
                "Přesuň AutoSaveNotepad.exe například do své uživatelské složky "
                "(Dokumenty / Aplikace) nebo spusť aktualizaci s potřebným oprávněním."
            ) from e

    def install_after_exit(self, new_exe):
        if not getattr(sys, "frozen", False):
            raise UpdateError("Instalace je dostupná pouze v EXE verzi.")

        current_exe = Path(sys.executable).resolve()
        new_exe = Path(new_exe).resolve()
        self._check_install_location(current_exe)

        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        script = UPDATE_DIR / "install_update.ps1"
        log = UPDATE_LOG

        old_q = _ps_quote(current_exe)
        new_q = _ps_quote(new_exe)
        log_q = _ps_quote(log)
        pid = os.getpid()

        # PowerShell helper:
        # 1) waits for the old application to terminate,
        # 2) retries replacement several times,
        # 3) clears PyInstaller environment,
        # 4) starts the new EXE,
        # 5) writes a diagnostic log.
        ps = f"""$ErrorActionPreference = 'Stop'
$old = '{old_q}'
$new = '{new_q}'
$log = '{log_q}'
$pidToWait = {pid}

function Write-Log([string]$msg) {{
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff'
    Add-Content -LiteralPath $log -Value "$stamp  $msg" -Encoding UTF8
}}

try {{
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null
    Write-Log "Updater helper started."
    Write-Log "Old EXE: $old"
    Write-Log "New EXE: $new"
    Write-Log "Waiting for PID $pidToWait."

    for ($i = 0; $i -lt 60; $i++) {{
        $p = Get-Process -Id $pidToWait -ErrorAction SilentlyContinue
        if (-not $p) {{ break }}
        Start-Sleep -Milliseconds 500
    }}

    if (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) {{
        throw "Old application did not terminate within 30 seconds."
    }}

    Write-Log "Old application terminated."

    $copied = $false
    for ($i = 1; $i -le 20; $i++) {{
        try {{
            [System.IO.File]::Copy($new, $old, $true)
            $copied = $true
            Write-Log "EXE replaced successfully on attempt $i."
            break
        }}
        catch {{
            Write-Log "Copy attempt $i failed: $($_.Exception.Message)"
            Start-Sleep -Milliseconds 500
        }}
    }}

    if (-not $copied) {{
        throw "Unable to replace executable after 20 attempts."
    }}

    if (-not (Test-Path -LiteralPath $old)) {{
        throw "Replacement EXE does not exist after copy."
    }}

    $env:PYINSTALLER_RESET_ENVIRONMENT = '1'
    Remove-Item Env:_PYI_ARCHIVE_FILE -ErrorAction SilentlyContinue
    Remove-Item Env:_PYI_APPLICATION_HOME_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:_PYI_PARENT_PROCESS_LEVEL -ErrorAction SilentlyContinue
    Remove-Item Env:_PYI_SPLASH_IPC -ErrorAction SilentlyContinue

    Write-Log "Starting updated application."
    Start-Process -FilePath $old -WorkingDirectory (Split-Path -Parent $old)
    Write-Log "Updated application launch requested."

    Start-Sleep -Milliseconds 500
    Remove-Item -LiteralPath $new -Force -ErrorAction SilentlyContinue
    Write-Log "Downloaded temporary EXE removed."
}}
catch {{
    Write-Log "ERROR: $($_.Exception.Message)"
    Write-Log $_.ScriptStackTrace
    try {{
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show(
            "Aktualizaci se nepodařilo dokončit.`n`n$($_.Exception.Message)`n`nLog: $log",
            "AutoSave Notepad – chyba aktualizace",
            "OK",
            "Error"
        ) | Out-Null
    }} catch {{}}
    exit 1
}}
"""

        try:
            script.write_text(ps, encoding="utf-8-sig")
            try:
                log.unlink()
            except FileNotFoundError:
                pass

            env = os.environ.copy()
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            for key in list(env):
                if key.startswith("_PYI_"):
                    env.pop(key, None)

            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)

            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                    str(script),
                ],
                env=env,
                creationflags=flags,
                close_fds=True,
            )
        except OSError as e:
            raise UpdateError(f"Nepodařilo se spustit instalátor:\n{e}") from e

    def get_update_log_path(self):
        return UPDATE_LOG
