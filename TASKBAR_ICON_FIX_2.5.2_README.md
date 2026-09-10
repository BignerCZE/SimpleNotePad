# SimpleNotePad 2.5.2 – oprava ikony hlavního panelu Windows

## Problém
Explorer zobrazoval správnou ikonu AutoSaveNotepad.exe, ale běžící aplikace
na hlavním panelu Windows zobrazovala výchozí Tcl/Tk ikonu.

Předchozí verze posílala WM_SETICON na `root.winfo_id()`. U Tkinteru na
Windows může tento handle patřit vnitřnímu Tk oknu, nikoli skutečnému
top-level wrapper oknu zobrazovanému na hlavním panelu.

## Oprava 2.5.2
- z běžícího EXE se vyextrahuje jeho vlastní ikona,
- přes `GetAncestor(..., GA_ROOT)` se najde skutečný top-level HWND,
- ikona se nastaví přes `WM_SETICON` na top-level i Tk HWND,
- současně se nastaví `GCLP_HICON` a `GCLP_HICONSM` na window class,
- změna se po startu několikrát zopakuje, protože Tk může wrapper během
  počátečního mapování dokončovat,
- stabilní AppUserModelID zůstává zachován.

## Test
Tuto změnu testuj na sestaveném EXE, nikoli přes `python app.py`.

Po release 2.5.2 lze aktualizaci získat běžným interním updaterem.
