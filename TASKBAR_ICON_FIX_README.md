# SimpleNotePad 2.5.1 – oprava ikony na hlavním panelu Windows

Tato varianta navazuje na opravu tisku pro Windows 11 a před vydáním 2.5.1
sjednocuje ikonu spuštěné aplikace s ikonou EXE.

## Princip
Desktopová ikona AutoSaveNotepad.exe už byla správná, proto se nemění
PyInstaller ikona ani `icon.ico`.

Při startu aplikace se nyní:
1. nastaví stabilní Windows AppUserModelID `BignerCZE.SimpleNotePad`,
2. z běžícího `AutoSaveNotepad.exe` se přes Windows API vyextrahuje jeho
   vlastní vložená ikona,
3. tatáž ikona se explicitně nastaví jako velká i malá ikona hlavního Tk okna,
4. nastavení se zopakuje po prvním vykreslení okna, aby ho Tk nepřepsal.

Výsledkem má být přesně stejný symbol, jaký Explorer zobrazuje u EXE/souboru
na ploše.

## Jak testovat
Změnu nelze korektně posoudit pouze přes `python app.py`, protože v takovém
případě je `sys.executable` Python.exe.

Sestav EXE:

```powershell
pyinstaller --clean --noconfirm AutoSaveNotepad.spec
```

A spusť:

```powershell
.\dist\AutoSaveNotepad.exe
```

Ověř:
- ikonu souboru EXE,
- ikonu spuštěné aplikace na hlavním panelu,
- ikonu v Alt+Tab.

Pokud byla stará aplikace dříve připnutá na hlavní panel, Windows může mít
uloženou starou ikonu zástupce. V takovém případě starou položku odepni a
nově spuštěný SimpleNotePad připni znovu.
