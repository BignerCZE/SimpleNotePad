# SimpleNotePad – DOCX storage

Tato varianta mění primární formát poznámek z TXT na DOCX.

## Co je uvnitř DOCX
- text
- tučné písmo
- kurzíva
- podtržení
- velikost písma
- obrázky a screenshoty vložené přes Ctrl+V

Obrázky už nejsou závislé na externí PNG složce. Po uložení jsou vložené
přímo do DOCX balíčku.

## Automatické ukládání
- periodický autosave vytváří `.docx`
- recovery soubor v TEMP je `.docx`
- při ukončení programu se zapíše úplný recovery DOCX
- JSON stav aplikace ukládá jen seznam karet, cesty a nastavení, nikoli obsah poznámek

## Staré TXT
TXT lze otevřít jako import. Je označen jako neuložený a při prvním uložení
se nabídne `.docx`.

## Build
```powershell
pip install -r requirements.txt
python .\app.py
```

Po otestování:
```powershell
pyinstaller --clean --noconfirm AutoSaveNotepad.spec
```

## Doporučené testy
1. Napiš několik řádků.
2. Část nastav tučně, kurzívou, podtrženě a různými velikostmi.
3. Win+Shift+S -> screenshot -> Ctrl+V.
4. Ulož jako DOCX.
5. Zavři aplikaci a DOCX znovu otevři v SimpleNotePad.
6. Otevři tentýž DOCX v Microsoft Wordu.
7. Ověř text, formátování a obrázek.
8. Ověř automatické uložení ve zvolené autosave složce.
