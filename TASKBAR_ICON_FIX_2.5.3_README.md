# SimpleNotePad 2.5.3 – taskbar ikona přes Tk iconphoto

## Proč předchozí opravy nefungovaly
Na hlavním panelu zůstávala modrá Tcl/Tk feather ikona. To znamená, že samotný
Tk interpreter stále používal svou výchozí aplikační ikonu.

Přepisování HWND přes WM_SETICON proto nebylo vhodné řešení.

## Oprava 2.5.3
- `icon.ico` zůstává ikonou samotného AutoSaveNotepad.exe v Exploreru,
- `icon.png` se nově přibalí do PyInstaller one-file balíčku,
- ihned při vytvoření hlavního Tk okna se zavolá:

    root.iconphoto(True, tk.PhotoImage(...))

- PhotoImage zůstává uložený v objektu aplikace po celou dobu běhu,
- stabilní Windows AppUserModelID zůstává zachován.

Tím Tkinter dostává vlastní ikonu přímo svým podporovaným mechanismem místo
následného přepisování nativních Windows handle.

## Důležité
V kořeni projektu musí zůstat oba původní soubory:
- `icon.ico`
- `icon.png`

`AutoSaveNotepad.spec`:
- používá `icon.ico` pro EXE,
- přibaluje `icon.png` jako runtime resource.

## Test
```powershell
pyinstaller --clean --noconfirm AutoSaveNotepad.spec
.\dist\AutoSaveNotepad.exe
```

Pokud byl program připnutý na hlavním panelu, pro čistý test ho nejdříve
odepni. Spusť nový EXE normálně ze složky a sleduj ikonu běžící aplikace.
