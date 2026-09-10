# SimpleNotePad 2.5.1 – oprava tisku pro Windows 11

## Co bylo špatně ve 2.5.0
Verze 2.5.0 používala Windows ShellExecute s akcí `printto` nad dočasným DOCX.
Na některých instalacích Windows 11 tato shellová asociace DOCX není
zaregistrovaná a Windows vrací chybu 31.

Proto selhal i Microsoft Print to PDF – k samotnému tisku se vůbec nedošlo.

## Nové řešení
2.5.1 nepředává DOCX Wordu ani jiné aplikaci.

Po stisku:
- tlačítka Tisk,
- Soubor -> Tisk...,
- Ctrl+P

se otevře standardní Windows tiskový dialog. Po výběru tiskárny SimpleNotePad
vykreslí aktuální obsah karty přímo do tiskového kontextu Windows (GDI).

Tím pádem:
- není potřeba Microsoft Word,
- není potřeba funkční `print`/`printto` asociace DOCX,
- fungují běžné fyzické tiskárny,
- Microsoft Print to PDF je podporován stejně jako ostatní Windows tiskárny.

## Co se tiskne
- aktuální text,
- tučné písmo,
- kurzíva,
- podtržení,
- velikosti písma,
- vložené obrázky,
- aktuálně nastavená velikost obrázků.

Tisk vychází přímo z otevřené karty, takže zahrnuje i změny, které ještě
nebyly ručně uloženy do DOCX.

## Doporučený test
1. Spusť `python .\app.py`.
2. Vlož text v několika velikostech a stylech.
3. Vlož screenshot a změň jeho velikost tažením za roh.
4. Ctrl+P.
5. Vyber Microsoft Print to PDF.
6. Ulož PDF a zkontroluj rozložení.
7. Totéž ověř na fyzické tiskárně, pokud je k dispozici.
