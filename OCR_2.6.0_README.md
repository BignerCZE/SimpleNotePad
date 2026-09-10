# SimpleNotePad 2.6.0 – OCR obrázků ze schránky

## Chování Ctrl+V
Pokud je ve schránce běžný text:
- vložení funguje stejně jako dosud,
- žádný nový dialog se nezobrazuje.

Pokud je ve schránce obrázek nebo screenshot:
- zobrazí se dialog „Jak chcete obsah vložit?“
- Vložit jako obrázek
- Převést na text
- Zrušit

## Vložit jako obrázek
Zůstává celé dosavadní chování:
- automatické přizpůsobení při vložení,
- změna velikosti tažením za rohy,
- uložení obrázku v DOCX.

## Převést na text
- OCR probíhá lokálně přes Windows.Media.Ocr,
- obrázek se nikam neodesílá,
- OCR běží ve worker threadu, takže GUI během rozpoznávání nezamrzne,
- stavový řádek ukazuje „Rozpoznávám text…“,
- výsledek se vloží na pozici kurzoru jako běžný editovatelný text,
- zachovávají se rozpoznané řádky.

## Menu Obrázek
Nově obsahuje také:
- Převést obrázek ze schránky na text

Tato položka spustí OCR rovnou, bez dialogu „obrázek / text“.

## Jazyk
Aplikace preferuje `cs-CZ`, pokud je český Windows OCR jazyk dostupný.
Jinak zkusí OCR jazyk podle uživatelského jazykového profilu Windows.

Pokud není dostupný žádný OCR jazyk, uživatel dostane chybu s pokynem
nainstalovat jazykovou podporu OCR ve Windows.

## Instalace
Po nahrazení souborů:

```powershell
pip install -r requirements.txt
python .\app.py
```

## Test
1. Zkopíruj normální text a Ctrl+V – musí se vložit bez dialogu.
2. Win+Shift+S a označ text na obrazovce.
3. Ctrl+V.
4. Zvol „Vložit jako obrázek“ – musí se chovat stejně jako dříve.
5. Udělej nový screenshot textu.
6. Ctrl+V -> „Převést na text“.
7. Ověř českou diakritiku a zalomení řádků.
8. Vyzkoušej Obrázek -> Převést obrázek ze schránky na text.
9. Ulož DOCX a ověř, že OCR výsledek je běžný text.
