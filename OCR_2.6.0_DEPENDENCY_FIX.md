# SimpleNotePad 2.6.0 – oprava Windows OCR dependencies

Původní 2.6.0 obsahovalo Windows.Media.Ocr a Windows.Graphics.Imaging,
ale chyběly samostatně distribuované PyWinRT namespaces používané při
SoftwareBitmap.CreateCopyFromBuffer:

- winrt-Windows.Storage
- winrt-Windows.Storage.Streams
- winrt-Windows.Foundation.Collections

Proto se OCR zastavilo chybou:

    No module named 'winrt.windows.storage'

Po nahrazení souborů spusť:

    pip install -r requirements.txt

a teprve potom:

    python .\app.py

Pro kontrolu instalace lze spustit:

    python -c "import winrt.windows.storage, winrt.windows.storage.streams; print('WinRT Storage OK')"

Teprve po úspěšném OCR přes python app.py sestavuj PyInstaller EXE.
