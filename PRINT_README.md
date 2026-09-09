# SimpleNotePad 2.5.0 – tisk

## Ovládání
- tlačítko **Tisk** v toolbaru nahradilo původní tlačítko **Vložit obrázek**,
- **Ctrl+P** otevře tisk,
- **Soubor → Tisk...** otevře stejnou funkci,
- vložení obrázku zůstává přes Ctrl+V a menu **Obrázek → Vložit ze schránky**.

## Jak tisk funguje
Aktuální karta se nejprve uloží do dočasného DOCX snapshotu. Tím se do tisku dostanou i změny, které ještě nebyly ručně uložené, včetně formátování a obrázků.

Ve Windows se zobrazí systémový tiskový dialog. Po potvrzení je dočasný DOCX předán vybrané tiskárně přes systémovou akci `printto`. Pro DOCX musí být ve Windows nainstalovaná aplikace, která tuto systémovou tiskovou akci podporuje (typicky Microsoft Word).

Dočasné tiskové DOCX soubory se ukládají do `%TEMP%\AutoSaveNotepad_print` a starší než jeden den se průběžně mažou.
