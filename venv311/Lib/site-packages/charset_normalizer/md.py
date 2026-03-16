from __future__ import annotations

import sys
from functools import lru_cache
from logging import getLogger

if sys.version_info >= (3, 8):
    from typing import final
else:
    try:
        from typing_extensions import final
    except ImportError:

        def final(cls):  # type: ignore[misc,no-untyped-def]
            return cls


from .constant import (
    COMMON_SAFE_ASCII_CHARACTERS,
    TRACE,
    UNICODE_SECONDARY_RANGE_KEYWORD,
    _ACCENTUATED,
    _CJK,
    _HANGUL,
    _HIRAGANA,
    _KATAKANA,
    _LATIN,
    _THAI,
)
from .utils import (
    _character_flags,
    is_accentuated,
    is_arabic,
    is_arabic_isolated_form,
    is_case_variable,
    is_cjk,
    is_emoticon,
    is_latin,
    is_punctuation,
    is_separator,
    is_symbol,
    is_unprintable,
    remove_accent,
    unicode_range,
    is_cjk_uncommon,
)

# Combined bitmask for CJK/Hangul/Katakana/Hiragana/Thai glyph detection.
_GLYPH_MASK: int = _CJK | _HANGUL | _KATAKANA | _HIRAGANA | _THAI


class MessDetectorPlugin:
    """
    Base abstract class used for mess detection plugins.
    All detectors MUST extend and implement given methods.
    """

    __slots__ = ()

    def eligible(self, character: str) -> bool:
        """
        Determine if given character should be fed in.
        """
        raise NotImplementedError  # pragma: nocover

    def feed(self, character: str) -> None:
        """
        The main routine to be executed upon character.
        Insert the logic in witch the text would be considered chaotic.
        """
        raise NotImplementedError  # pragma: nocover

    def reset(self) -> None:  # pragma: no cover
        """
        Permit to reset the plugin to the initial state.
        """
        raise NotImplementedError

    @property
    def ratio(self) -> float:
        """
        Compute the chaos ratio based on what your feed() has seen.
        Must NOT be lower than 0.; No restriction gt 0.
        """
        raise NotImplementedError  # pragma: nocover


@final
class TooManySymbolOrPunctuationPlugin(MessDetectorPlugin):
    __slots__ = (
        "_punctuation_count",
        "_symbol_count",
        "_character_count",
        "_last_printable_char",
        "_frenzy_symbol_in_word",
    )

    def __init__(self) -> None:
        self._punctuation_count: int = 0
        self._symbol_count: int = 0
        self._character_count: int = 0

        self._last_printable_char: str | None = None
        self._frenzy_symbol_in_word: bool = False

    def eligible(self, character: str) -> bool:
        return character.isprintable()

    def feed(self, character: str) -> None:
        self._character_count += 1

        if (
            character != self._last_printable_char
            and character not in COMMON_SAFE_ASCII_CHARACTERS
        ):
            if is_punctuation(character):
                self._punctuation_count += 1
            elif (
                not character.isdigit()
                and is_symbol(character)
                and not is_emoticon(character)
            ):
                self._symbol_count += 2

        self._last_printable_char = character

    def reset(self) -> None:  # Abstract
        self._punctuation_count = 0
        self._character_count = 0
        self._symbol_count = 0

    @property
    def ratio(self) -> float:
        if self._character_count == 0:
            return 0.0

        ratio_of_punctuation: float = (
            self._punctuation_count + self._symbol_count
        ) / self._character_count

        return ratio_of_punctuation if ratio_of_punctuation >= 0.3 else 0.0


@final
class TooManyAccentuatedPlugin(MessDetectorPlugin):
    __slots__ = ("_character_count", "_accentuated_count")

    def __init__(self) -> None:
        self._character_count: int = 0
        self._accentuated_count: int = 0

    def eligible(self, character: str) -> bool:
        return character.isalpha()

    def feed(self, character: str) -> None:
        self._character_count += 1

        if is_accentuated(character):
            self._accentuated_count += 1

    def reset(self) -> None:  # Abstract
        self._character_count = 0
        self._accentuated_count = 0

    @property
    def ratio(self) -> float:
        if self._character_count < 8:
            return 0.0

        ratio_of_accentuation: float = self._accentuated_count / self._character_count
        return ratio_of_accentuation if ratio_of_accentuation >= 0.35 else 0.0


@final
class UnprintablePlugin(MessDetectorPlugin):
    __slots__ = ("_unprintable_count", "_character_count")

    def __init__(self) -> None:
        self._unprintable_count: int = 0
        self._character_count: int = 0

    def eligible(self, character: str) -> bool:
        return True

    def feed(self, character: str) -> None:
        if is_unprintable(character):
            self._unprintable_count += 1
        self._character_count += 1

    def reset(self) -> None:  # Abstract
        self._unprintable_count = 0

    @property
    def ratio(self) -> float:
        if self._character_count == 0:
            return 0.0

        return (self._unprintable_count * 8) / self._character_count


@final
class SuspiciousDuplicateAccentPlugin(MessDetectorPlugin):
    __slots__ = (
        "_successive_count",
        "_character_count",
        "_last_latin_character",
        "_last_was_accentuated",
    )

    def __init__(self) -> None:
        self._successive_count: int = 0
        self._character_count: int = 0

        self._last_latin_character: str | None = None
        self._last_was_accentuated: bool = False

    def eligible(self, character: str) -> bool:
        return character.isalpha() and is_latin(character)

    def feed(self, character: str) -> None:
        self._character_count += 1
        current_accentuated: bool = is_accentuated(character)
        if (
            self._last_latin_character is not None
            and current_accentuated
            and self._last_was_accentuated
        ):
            if character.isupper() and self._last_latin_character.isupper():
                self._successive_count += 1
            # Worse if its the same char duplicated with different accent.
            if remove_accent(character) == remove_accent(self._last_latin_character):
                self._successive_count += 1
        self._last_latin_character = character
        self._last_was_accentuated = current_accentuated

    def reset(self) -> None:  # Abstract
        self._successive_count = 0
        self._character_count = 0
        self._last_latin_character = None
        self._last_was_accentuated = False

    @property
    def ratio(self) -> float:
        if self._character_count == 0:
            return 0.0

        return (self._successive_count * 2) / self._character_count


@final
class SuspiciousRange(MessDetectorPlugin):
    __slots__ = (
        "_suspicious_successive_range_count",
        "_character_count",
        "_last_printable_seen",
        "_last_printable_range",
    )

    def __init__(self) -> None:
        self._suspicious_successive_range_count: int = 0
        self._character_count: int = 0
        self._last_printable_seen: str | None = None
        self._last_printable_range: str | None = None

    def eligible(self, character: str) -> bool:
        return character.isprintable()

    def feed(self, character: str) -> None:
        self._character_count += 1

        if (
            character.isspace()
            or is_punctuation(character)
            or character in COMMON_SAFE_ASCII_CHARACTERS
        ):
            self._last_printable_seen = None
            self._last_printable_range = None
            return

        if self._last_printable_seen is None:
            self._last_printable_seen = character
            self._last_printable_range = unicode_range(character)
            return

        unicode_range_a: str | None = self._last_printable_range
        unicode_range_b: str | None = unicode_range(character)

        if is_suspiciously_successive_range(unicode_range_a, unicode_range_b):
            self._suspicious_successive_range_count += 1

        self._last_printable_seen = character
        self._last_printable_range = unicode_range_b

    def reset(self) -> None:  # Abstract
        self._character_count = 0
        self._suspicious_successive_range_count = 0
        self._last_printable_seen = None
        self._last_printable_range = None

    @property
    def ratio(self) -> float:
        if self._character_count <= 13:
            return 0.0

        ratio_of_suspicious_range_usage: float = (
            self._suspicious_successive_range_count * 2
        ) / self._character_count

        return ratio_of_suspicious_range_usage


@final
class SuperWeirdWordPlugin(MessDetectorPlugin):
    __slots__ = (
        "_word_count",
        "_bad_word_count",
        "_foreign_long_count",
        "_is_current_word_bad",
        "_foreign_long_watch",
        "_character_count",
        "_bad_character_count",
        "_buffer_length",
        "_buffer_last_char",
        "_buffer_last_char_accentuated",
        "_buffer_accent_count",
        "_buffer_glyph_count",
        "_buffer_upper_count",
    )

    def __init__(self) -> None:
        self._word_count: int = 0
        self._bad_word_count: int = 0
        self._foreign_long_count: int = 0

        self._is_current_word_bad: bool = False
        self._foreign_long_watch: bool = False

        self._character_count: int = 0
        self._bad_character_count: int = 0

        self._buffer_length: int = 0
        self._buffer_last_char: str | None = None
        self._buffer_last_char_accentuated: bool = False
        self._buffer_accent_count: int = 0
        self._buffer_glyph_count: int = 0
        self._buffer_upper_count: int = 0

    def eligible(self, character: str) -> bool:
        return True

    def feed(self, character: str) -> None:
        if character.isalpha():
            self._buffer_length += 1
            self._buffer_last_char = character

            if character.isupper():
                self._buffer_upper_count += 1

            flags: int = _character_flags(character)
            char_accentuated: bool = bool(flags & _ACCENTUATED)
            self._buffer_last_char_accentuated = char_accentuated

            if char_accentuated:
                self._buffer_accent_count += 1
            if (
                not self._foreign_long_watch
                and (not (flags & _LATIN) or char_accentuated)
                and not (flags & _GLYPH_MASK)
            ):
                self._foreign_long_watch = True
            if flags & _GLYPH_MASK:
                self._buffer_glyph_count += 1
            return
        if not self._buffer_length:
            return
        if (
            character.isspace() or is_punctuation(character) or is_separator(character)
        ) and self._buffer_length:
            self._word_count += 1
            buffer_length: int = self._buffer_length

            self._character_count += buffer_length

            if buffer_length >= 4:
                if self._buffer_accent_count / buffer_length >= 0.5:
                    self._is_current_word_bad = True
                # Word/Buffer ending with an upper case accentuated letter are so rare,
                # that we will consider them all as suspicious. Same weight as foreign_long suspicious.
                elif (
                    self._buffer_last_char_accentuated
                    and self._buffer_last_char.isupper()  # type: ignore[union-attr]
                    and self._buffer_upper_count != buffer_length
                ):
                    self._foreign_long_count += 1
                    self._is_current_word_bad = True
                elif self._buffer_glyph_count == 1:
                    self._is_current_word_bad = True
                    self._foreign_long_count += 1
            if buffer_length >= 24 and self._foreign_long_watch:
                probable_camel_cased: bool = (
                    self._buffer_upper_count > 0
                    and self._buffer_upper_count / buffer_length <= 0.3
                )

                if not probable_camel_cased:
                    self._foreign_long_count += 1
                    self._is_current_word_bad = True

            if self._is_current_word_bad:
                self._bad_word_count += 1
                self._bad_character_count += buffer_length
                self._is_current_word_bad = False

            self._foreign_long_watch = False
            self._buffer_length = 0
            self._buffer_last_char = None
            self._buffer_last_char_accentuated = False
            self._buffer_accent_count = 0
            self._buffer_glyph_count = 0
            self._buffer_upper_count = 0
        elif (
            character not in {"<", ">", "-", "=", "~", "|", "_"}
            and not character.isdigit()
            and is_symbol(character)
        ):
            self._is_current_word_bad = True
            self._buffer_length += 1
            self._buffer_last_char = character
            self._buffer_last_char_accentuated = False

    def reset(self) -> None:  # Abstract
        self._buffer_length = 0
        self._buffer_last_char = None
        self._buffer_last_char_accentuated = False
        self._is_current_word_bad = False
        self._foreign_long_watch = False
        self._bad_word_count = 0
        self._word_count = 0
        self._character_count = 0
        self._bad_character_count = 0
        self._foreign_long_count = 0
        self._buffer_accent_count = 0
        self._buffer_glyph_count = 0
        self._buffer_upper_count = 0

    @property
    def ratio(self) -> float:
        if self._word_count <= 10 and self._foreign_long_count == 0:
            return 0.0

        return self._bad_character_count / self._character_count


@final
class CjkUncommonPlugin(MessDetectorPlugin):
    """
    Detect messy CJK text that probably means nothing.
    """

    __slots__ = ("_character_count", "_uncommon_count")

    def __init__(self) -> None:
        self._character_count: int = 0
        self._uncommon_count: int = 0

    def eligible(self, character: str) -> bool:
        return is_cjk(character)

    def feed(self, character: str) -> None:
        self._character_count += 1

        if is_cjk_uncommon(character):
            self._uncommon_count += 1
            return

    def reset(self) -> None:  # Abstract
        self._character_count = 0
        self._uncommon_count = 0

    @property
    def ratio(self) -> float:
        if self._character_count < 8:
            return 0.0

        uncommon_form_usage: float = self._uncommon_count / self._character_count

        # we can be pretty sure it's garbage when uncommon characters are widely
        # used. otherwise it could just be traditional chinese for example.
        return uncommon_form_usage / 10 if uncommon_form_usage > 0.5 else 0.0


@final
class ArchaicUpperLowerPlugin(MessDetectorPlugin):
    __slots__ = (
        "_buf",
        "_character_count_since_last_sep",
        "_successive_upper_lower_count",
        "_successive_upper_lower_count_final",
        "_character_count",
        "_last_alpha_seen",
        "_current_ascii_only",
    )

    def __init__(self) -> None:
        self._buf: bool = False

        self._character_count_since_last_sep: int = 0

        self._successive_upper_lower_count: int = 0
        self._successive_upper_lower_count_final: int = 0

        self._character_count: int = 0

        self._last_alpha_seen: str | None = None
        self._current_ascii_only: bool = True

    def eligible(self, character: str) -> bool:
        return True

    def feed(self, character: str) -> None:
        is_concerned: bool = character.isalpha() and is_case_variable(character)
        chunk_sep: bool = not is_concerned

        if chunk_sep and self._character_count_since_last_sep > 0:
            if (
                self._character_count_since_last_sep <= 64
                and not character.isdigit()
                and not self._current_ascii_only
            ):
                self._successive_upper_lower_count_final += (
                    self._successive_upper_lower_count
                )

            self._successive_upper_lower_count = 0
            self._character_count_since_last_sep = 0
            self._last_alpha_seen = None
            self._buf = False
            self._character_count += 1
            self._current_ascii_only = True

            return

        if self._current_ascii_only and not character.isascii():
            self._current_ascii_only = False

        if self._last_alpha_seen is not None:
            if (character.isupper() and self._last_alpha_seen.islower()) or (
                character.islower() and self._last_alpha_seen.isupper()
            ):
                if self._buf:
                    self._successive_upper_lower_count += 2
                    self._buf = False
                else:
                    self._buf = True
            else:
                self._buf = False

        self._character_count += 1
        self._character_count_since_last_sep += 1
        self._last_alpha_seen = character

    def reset(self) -> None:  # Abstract
        self._character_count = 0
        self._character_count_since_last_sep = 0
        self._successive_upper_lower_count = 0
        self._successive_upper_lower_count_final = 0
        self._last_alpha_seen = None
        self._buf = False
        self._current_ascii_only = True

    @property
    def ratio(self) -> float:
        if self._character_count == 0:
            return 0.0

        return self._successive_upper_lower_count_final / self._character_count


@final
class ArabicIsolatedFormPlugin(MessDetectorPlugin):
    __slots__ = ("_character_count", "_isolated_form_count")

    def __init__(self) -> None:
        self._character_count: int = 0
        self._isolated_form_count: int = 0

    def reset(self) -> None:  # Abstract
        self._character_count = 0
        self._isolated_form_count = 0

    def eligible(self, character: str) -> bool:
        return is_arabic(character)

    def feed(self, character: str) -> None:
        self._character_count += 1

        if is_arabic_isolated_form(character):
            self._isolated_form_count += 1

    @property
    def ratio(self) -> float:
        if self._character_count < 8:
            return 0.0

        isolated_form_usage: float = self._isolated_form_count / self._character_count

        return isolated_form_usage


@lru_cache(maxsize=1024)
def is_suspiciously_successive_range(
    unicode_range_a: str | None, unicode_range_b: str | None
) -> bool:
    """
    Determine if two Unicode range seen next to each other can be considered as suspicious.
    """
    if unicode_range_a is None or unicode_range_b is None:
        return True

    if unicode_range_a == unicode_range_b:
        return False

    if "Latin" in unicode_range_a and "Latin" in unicode_range_b:
        return False

    if "Emoticons" in unicode_range_a or "Emoticons" in unicode_range_b:
        return False

    # Latin characters can be accompanied with a combining diacritical mark
    # eg. Vietnamese.
    if ("Latin" in unicode_range_a or "Latin" in unicode_range_b) and (
        "Combining" in unicode_range_a or "Combining" in unicode_range_b
    ):
        return False

    keywords_range_a, keywords_range_b = (
        unicode_range_a.split(" "),
        unicode_range_b.split(" "),
    )

    for el in keywords_range_a:
        if el in UNICODE_SECONDARY_RANGE_KEYWORD:
            continue
        if el in keywords_range_b:
            return False

    # Japanese Exception
    range_a_jp_chars, range_b_jp_chars = (
        unicode_range_a
        in (
            "Hiragana",
            "Katakana",
        ),
        unicode_range_b in ("Hiragana", "Katakana"),
    )
    if (range_a_jp_chars or range_b_jp_chars) and (
        "CJK" in unicode_range_a or "CJK" in unicode_range_b
    ):
        return False
    if range_a_jp_chars and range_b_jp_chars:
        return False

    if "Hangul" in unicode_range_a or "Hangul" in unicode_range_b:
        if "CJK" in unicode_range_a or "CJK" in unicode_range_b:
            return False
        if unicode_range_a == "Basic Latin" or unicode_range_b == "Basic Latin":
            return False

    # Chinese/Japanese use dedicated range for punctuation and/or separators.
    if ("CJK" in unicode_range_a or "CJK" in unicode_range_b) or (
        unicode_range_a in ["Katakana", "Hiragana"]
        and unicode_range_b in ["Katakana", "Hiragana"]
    ):
        if "Punctuation" in unicode_range_a or "Punctuation" in unicode_range_b:
            return False
        if "Forms" in unicode_range_a or "Forms" in unicode_range_b:
            return False
        if unicode_range_a == "Basic Latin" or unicode_range_b == "Basic Latin":
            return False

    return True


# import time messdetector plugins detection(...)
_DETECTOR_CLASSES: tuple[type[MessDetectorPlugin], ...] = tuple(
    md_class for md_class in MessDetectorPlugin.__subclasses__()
)


@lru_cache(maxsize=2048)
def mess_ratio(
    decoded_sequence: str, maximum_threshold: float = 0.2, debug: bool = False
) -> float:
    """
    Compute a mess ratio given a decoded bytes sequence. The maximum threshold does stop the computation earlier.
    """

    detectors: list[MessDetectorPlugin] = [md_class() for md_class in _DETECTOR_CLASSES]

    mean_mess_ratio: float
    seq_len: int = len(decoded_sequence)

    if seq_len < 511:
        step: int = 32
    elif seq_len < 1024:
        step = 64
    else:
        step = 128

    for block_start in range(0, seq_len, step):
        for character in decoded_sequence[block_start : block_start + step]:
            for detector in detectors:
                if detector.eligible(character):
                    detector.feed(character)

        mean_mess_ratio = sum(dt.ratio for dt in detectors)

        if mean_mess_ratio >= maximum_threshold:
            break
    else:
        # Flush last word buffer in SuperWeirdWordPlugin via trailing newline.
        for detector in detectors:
            if detector.eligible("\n"):
                detector.feed("\n")
        mean_mess_ratio = sum(dt.ratio for dt in detectors)

    if debug:
        logger = getLogger("charset_normalizer")

        logger.log(
            TRACE,
            "Mess-detector extended-analysis start. "
            f"intermediary_mean_mess_ratio_calc={step} mean_mess_ratio={mean_mess_ratio} "
            f"maximum_threshold={maximum_threshold}",
        )

        if seq_len > 16:
            logger.log(TRACE, f"Starting with: {decoded_sequence[:16]}")
            logger.log(TRACE, f"Ending with: {decoded_sequence[-16::]}")

        for dt in detectors:
            logger.log(TRACE, f"{dt.__class__}: {dt.ratio}")

    return round(mean_mess_ratio, 3)
