# SimpleNotePad 2.6.3 – oprava layoutu OCR náhledu

Ve verzi 2.6.2 byla tlačítka vytvořená, ale velké editační pole je mohlo
v některých Windows/DPI konfiguracích vytlačit pod spodní okraj dialogu.

2.6.3 předělává OCR náhled z `pack` na pevně strukturovaný `grid`:

- řádek 0: nadpis,
- řádek 1: informace o OCR,
- řádek 2: editovatelný text – jediný řádek, který se roztahuje,
- řádek 3: pevný spodní panel.

Spodní panel obsahuje vždy viditelně:
- Zrušit
- Vložit text

Zkratky zůstávají:
- Esc = Zrušit
- Ctrl+Enter = Vložit text
