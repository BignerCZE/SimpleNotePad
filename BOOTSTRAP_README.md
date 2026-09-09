# AutoSave Notepad 2.1.0 – jednorázový bootstrap

Verze 2.0.2 má chybný instalační mechanismus, takže novější updater se do ní
nemůže sám "dostat". 2.1.0 je proto potřeba jednou nainstalovat ručně.

## 1. Nahraď zdrojové soubory
- app.py
- updater.py
- requirements.txt

## 2. Build
pip install -r requirements.txt
pyinstaller --clean --noconfirm AutoSaveNotepad.spec

Výsledek:
dist\AutoSaveNotepad.exe

## 3. Jednorázově nahraď staré EXE
Ukonči 2.0.2 a ručně nahraď jeho AutoSaveNotepad.exe novým EXE 2.1.0.

## 4. GitHub Release 2.1.0
git add app.py updater.py requirements.txt
git commit -m "Add robust updater bootstrap 2.1.0"
git push
git tag v2.1.0
git push origin v2.1.0

## 5. Skutečný test automatického updateru
Až 2.1.0 běží ručně, vytvoř další verzi (např. 2.1.1), změň APP_VERSION,
commitni a vytvoř tag v2.1.1.

Teprve přechod 2.1.0 -> 2.1.1 ověřuje nový updater.

## Log
Helper zapisuje diagnostiku do:
%TEMP%\autosave_notepad_update\update.log
