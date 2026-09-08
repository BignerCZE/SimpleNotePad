# SimpleNotePad upgrade 2.0

## Nové funkce
- tučné písmo (Ctrl+B)
- kurzíva (Ctrl+I)
- podtržení (Ctrl+U)
- velikost písma
- formátovací toolbar a menu
- automatická kontrola GitHub Releases při startu
- ruční kontrola aktualizací
- podpora private GitHub repozitáře
- token uložen přes Windows Credential Manager (`keyring`)
- SHA-256 ověření staženého EXE
- automatický GitHub Actions build po tagu `vX.Y.Z`

## Formátování a TXT
`.txt` neumí rich-text formátování. Text proto zůstává čistý TXT a informace
o tučném písmu, kurzívě, podtržení a velikosti se ukládají v interním stavovém
JSON souboru aplikace. Tím se zachová současný autosave/export workflow.

## Private repo
1. Nejdřív nasaď a otestuj verzi 2.0.0 ještě s veřejným repozitářem.
2. Vytvoř GitHub Release `v2.0.0`.
3. Potom přepni repo na Private.
4. V GitHubu vytvoř fine-grained Personal Access Token pouze pro
   `BignerCZE/SimpleNotePad` s `Contents: Read-only`.
5. V programu: `Nápověda -> Nastavit GitHub přístup`.
6. Token se uloží do Windows Credential Manager. Nikdy ho necommituj.

## Build
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pyinstaller --clean --noconfirm AutoSaveNotepad.spec
```

## Vydání nové verze
Např. 2.0.1:
```powershell
# změň APP_VERSION v app.py na 2.0.1
git add .
git commit -m "Release 2.0.1"
git push
git tag v2.0.1
git push origin v2.0.1
```

GitHub Actions vytvoří Release s:
- `AutoSaveNotepad.exe`
- `AutoSaveNotepad.exe.sha256`
