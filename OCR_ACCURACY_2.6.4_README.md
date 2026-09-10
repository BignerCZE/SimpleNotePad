# SimpleNotePad 2.6.4 – vyšší přesnost OCR

Verze 2.6.4 zlepšuje rozpoznávání malého textu ze screenshotů.

## 1. Předzpracování obrazu
Před předáním do Windows OCR se screenshot:
- převede do odstínů šedi,
- automaticky srovná kontrast,
- zvětší až 2×, pokud to dovoluje limit Windows OCR,
- lehce zvýší kontrast,
- jemně doostří.

Nepoužívá se tvrdé černobílé prahování, protože to může poškodit diakritiku
a anti-aliased malé písmo.

## 2. Konzervativní české korekce
Po OCR se automaticky opravují pouze vysoce jisté záměny malého `l`
za číslici `1` u věkových výrazů.

Příklady:
- 401eté  -> 40leté
- 511etým -> 51letým
- 351etá  -> 35letá
- 601etého -> 60letého

Globální nahrazování `1` za `l` se nedělá, aby nedošlo k poškození skutečných
čísel, datumů, identifikátorů nebo měření.

## 3. Náhled zůstává
Výsledek se i nadále otevře v editovatelném náhledu.
Uživatel může text před vložením ručně opravit.

Zkratky:
- Esc = Zrušit
- Ctrl+Enter = Vložit text
