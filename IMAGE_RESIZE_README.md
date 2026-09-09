# SimpleNotePad 2.3.0 – změna velikosti obrázků

Výchozí vložení:
1. Pokud je screenshot/obrázek užší nebo stejně široký jako dostupná šířka editoru,
   vloží se v původní pixelové šířce.
2. Pokud je širší než editor, při vložení se zmenší přesně na maximální šířku editoru.
3. Poměr stran se vždy zachovává.

Úprava po vložení:
- klikni na obrázek,
- v horní liště se aktivuje skupina „Obrázek“,
- `−` = zmenšit o 10 %,
- `+` = zvětšit o 10 %,
- pole `px` = přesná šířka v pixelech,
- `Původní` = původní pixelová šířka screenshotu,
- `Do okna` = aktuální maximální šířka editoru.

DOCX:
- do DOCX se ukládá aktuálně nastavená zobrazovaná šířka,
- při opětovném otevření se velikost načte z OOXML rozměru obrázku,
- obrázek zůstává fyzicky uvnitř DOCX.
