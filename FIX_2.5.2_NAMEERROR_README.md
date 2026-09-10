# SimpleNotePad 2.5.2 – corrected build

Oprava proti předchozímu balíčku 2.5.2.

Při úpravě taskbar ikony byl omylem odstraněn blok globálních konstant aplikace.
To vedlo při startu například k chybě:

    NameError: name 'UI_BG' is not defined

Tento balíček obnovuje všechny původní konstanty aplikace a současně zachovává
opravu taskbar ikony 2.5.2.

Ověřeno:
- Python syntax compile,
- AST kontrola všech module-level konstant,
- existence UI_BG před použitím,
- zachování AppUserModelID / GetAncestor / WM_SETICON logiky.
