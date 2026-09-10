import asyncio
import os
import re

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


class OcrError(RuntimeError):
    pass


def _preprocess_for_ocr(image, max_dimension=0):
    """
    Improve small UI/screenshot text before Windows OCR.

    The transformations are deliberately mild:
    - grayscale,
    - autocontrast,
    - 2x upscale when Windows' max OCR dimension allows it,
    - small contrast boost,
    - light unsharp mask.

    This is aimed at anti-aliased desktop/browser text where lowercase "l"
    can otherwise resemble the digit "1".
    """
    gray = ImageOps.grayscale(image)

    # Remove unused tonal margins while preserving text anti-aliasing.
    gray = ImageOps.autocontrast(gray)

    # Upscale only while staying inside Windows OCR limits.
    target_scale = 2.0
    if max_dimension:
        largest = max(gray.size)
        if largest > 0:
            target_scale = min(target_scale, max_dimension / largest)

    if target_scale > 1.05:
        new_size = (
            max(1, int(round(gray.width * target_scale))),
            max(1, int(round(gray.height * target_scale))),
        )
        gray = gray.resize(new_size, Image.Resampling.LANCZOS)

    # Mild enhancement: aggressive thresholding tends to damage accents and
    # anti-aliased Czech characters, so keep the source continuous-tone.
    gray = ImageEnhance.Contrast(gray).enhance(1.15)
    gray = gray.filter(
        ImageFilter.UnsharpMask(radius=1.0, percent=120, threshold=2)
    )

    # SoftwareBitmap path below expects RGBA8.
    return gray.convert("RGBA")


_AGE_L_AS_ONE_RE = re.compile(
    r"\b(\d{1,3})1("
    r"et(?:ý|á|é|ého|ému|ém|ým|ých|ou|ými)"
    r")\b",
    flags=re.IGNORECASE,
)


def _postprocess_czech_ocr(text):
    """
    Apply only high-confidence Czech OCR corrections.

    Example:
      401eté  -> 40leté
      511etým -> 51letým

    We intentionally do NOT perform a global 1 -> l replacement because that
    would corrupt real numbers, dates, identifiers and measurements.
    """
    if not text:
        return text

    return _AGE_L_AS_ONE_RE.sub(
        lambda match: f"{match.group(1)}l{match.group(2)}",
        text,
    )


def _load_winrt():
    if os.name != "nt":
        raise OcrError("Windows OCR je dostupné pouze ve Windows.")

    try:
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import (
            BitmapAlphaMode,
            BitmapPixelFormat,
            SoftwareBitmap,
        )
        from winrt.windows.media.ocr import OcrEngine

        # SoftwareBitmap.CreateCopyFromBuffer uses the Windows.Storage.Streams
        # IBuffer ABI. PyWinRT distributes these namespaces as separate wheels,
        # so import them explicitly to ensure the projection is registered.
        import winrt.windows.storage
        import winrt.windows.storage.streams
    except ImportError as exc:
        raise OcrError(
            "Chybí některá komponenta Windows OCR / Windows.Storage. "
            "Spusťte znovu: pip install -r requirements.txt"
        ) from exc

    return Language, BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap, OcrEngine


def available_ocr_languages():
    """Return installed Windows OCR language tags, e.g. ['cs-CZ', 'en-US'].""" 
    Language, _, _, _, OcrEngine = _load_winrt()

    result = []
    try:
        for language in OcrEngine.available_recognizer_languages:
            tag = getattr(language, "language_tag", None)
            if tag:
                result.append(str(tag))
    except Exception as exc:
        raise OcrError(
            f"Nepodařilo se zjistit dostupné jazyky Windows OCR: {exc}"
        ) from exc

    return result


def _select_engine(preferred_language):
    Language, _, _, _, OcrEngine = _load_winrt()

    # Prefer Czech when it is genuinely installed/supported.
    if preferred_language:
        try:
            language = Language(preferred_language)
            if OcrEngine.is_language_supported(language):
                engine = OcrEngine.try_create_from_language(language)
                if engine is not None:
                    return engine
        except Exception:
            pass

    # Fall back to the user's Windows language profile. This also permits
    # English OCR on PCs where Czech OCR has not been installed.
    try:
        engine = OcrEngine.try_create_from_user_profile_languages()
    except Exception as exc:
        raise OcrError(
            f"Windows OCR engine se nepodařilo vytvořit: {exc}"
        ) from exc

    if engine is None:
        languages = []
        try:
            languages = available_ocr_languages()
        except Exception:
            pass

        if languages:
            available = ", ".join(languages)
            raise OcrError(
                "Windows nenašel vhodný OCR jazyk pro uživatelský profil. "
                f"Dostupné OCR jazyky: {available}."
            )

        raise OcrError(
            "Ve Windows není dostupný žádný OCR jazyk. "
            "Nainstalujte jazykovou podporu OCR v Nastavení Windows "
            "(Čas a jazyk → Jazyk a oblast → Jazykové možnosti)."
        )

    return engine


async def _recognize_async(image, preferred_language):
    (
        _Language,
        BitmapAlphaMode,
        BitmapPixelFormat,
        SoftwareBitmap,
        _OcrEngine,
    ) = _load_winrt()

    # Windows OCR has a maximum supported image dimension.
    engine = _select_engine(preferred_language)

    max_dimension = 0
    try:
        from winrt.windows.media.ocr import OcrEngine
        max_dimension = int(OcrEngine.max_image_dimension)
    except Exception:
        max_dimension = 0

    # For screenshots/UI text, preprocess before creating SoftwareBitmap.
    rgba = _preprocess_for_ocr(
        image,
        max_dimension=max_dimension,
    )

    # Final safety clamp in case a source image is already larger than the
    # Windows OCR limit.
    if max_dimension and max(rgba.size) > max_dimension:
        ratio = max_dimension / max(rgba.size)
        new_size = (
            max(1, int(round(rgba.width * ratio))),
            max(1, int(round(rgba.height * ratio))),
        )
        rgba = rgba.resize(new_size, Image.Resampling.LANCZOS)

    try:
        pixels = bytearray(rgba.tobytes())
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            pixels,
            BitmapPixelFormat.RGBA8,
            rgba.width,
            rgba.height,
            BitmapAlphaMode.STRAIGHT,
        )
    except TypeError:
        # Some Windows SDK projections expose the older overload without
        # BitmapAlphaMode.
        try:
            pixels = bytearray(rgba.tobytes())
            bitmap = SoftwareBitmap.create_copy_from_buffer(
                pixels,
                BitmapPixelFormat.RGBA8,
                rgba.width,
                rgba.height,
            )
        except Exception as exc:
            raise OcrError(
                f"Obrázek se nepodařilo připravit pro Windows OCR: {exc}"
            ) from exc
    except Exception as exc:
        raise OcrError(
            f"Obrázek se nepodařilo připravit pro Windows OCR: {exc}"
        ) from exc

    try:
        result = await engine.recognize_async(bitmap)
    except Exception as exc:
        raise OcrError(
            f"Windows OCR selhalo při rozpoznávání: {exc}"
        ) from exc
    finally:
        try:
            bitmap.close()
        except Exception:
            pass

    # Keep the OCR line structure instead of flattening everything into one
    # paragraph.
    lines = []
    try:
        for line in result.lines:
            value = (line.text or "").rstrip()
            if value:
                lines.append(value)
    except Exception:
        text = getattr(result, "text", "") or ""
        lines = text.splitlines()

    language_tag = ""
    try:
        language_tag = str(engine.recognizer_language.language_tag)
    except Exception:
        pass

    recognized_text = "\n".join(lines)
    recognized_text = _postprocess_czech_ocr(recognized_text)

    return recognized_text, language_tag


def recognize_image(image, preferred_language="cs-CZ"):
    """
    Synchronous wrapper intended to be called from a worker thread.
    No image data leaves the computer.
    """
    if not isinstance(image, Image.Image):
        raise OcrError("OCR očekává obrázek ve formátu Pillow Image.")

    try:
        return asyncio.run(
            _recognize_async(image, preferred_language)
        )
    except OcrError:
        raise
    except Exception as exc:
        raise OcrError(f"Windows OCR se nepodařilo spustit: {exc}") from exc
