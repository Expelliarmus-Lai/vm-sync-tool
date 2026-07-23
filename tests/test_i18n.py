import unittest
from unittest.mock import patch

from i18n import (
    SUPPORTED_LANGUAGES,
    TRANSLATIONS,
    Translator,
    detect_system_language,
    normalize_language,
)


class I18nTests(unittest.TestCase):
    def test_translation_keys_are_complete_for_supported_languages(self):
        key_sets = [
            set(TRANSLATIONS[language])
            for language in SUPPORTED_LANGUAGES
        ]

        self.assertTrue(key_sets)
        self.assertEqual(key_sets[0], key_sets[1])

    def test_translator_formats_dynamic_values(self):
        zh = Translator("zh")
        en = Translator("en")

        self.assertEqual("将同步 3 个文件", zh.tr("preflight.action.full", count=3))
        self.assertEqual("Will sync 3 files", en.tr("preflight.action.full", count=3))

    def test_preflight_warning_log_is_single_line(self):
        self.assertNotIn("\n", Translator("zh").tr("ui.preflight.warning", message="warn"))
        self.assertNotIn("\n", Translator("en").tr("ui.preflight.warning", message="warn"))

    def test_invalid_language_normalizes_to_empty_for_auto_detection(self):
        self.assertEqual("", normalize_language("fr"))
        self.assertEqual("en", normalize_language("EN"))

    def test_detect_system_language_treats_windows_chinese_locale_name_as_zh(self):
        with patch("i18n._detect_windows_ui_language", return_value=""), \
                patch("i18n.locale.getlocale") as getlocale:
            getlocale.return_value = ("Chinese (Simplified)_China", "936")

            self.assertEqual("zh", detect_system_language())

    def test_windows_chinese_lcid_detects_zh(self):
        from i18n import _language_from_windows_lcid

        self.assertEqual("zh", _language_from_windows_lcid(0x0804))


if __name__ == "__main__":
    unittest.main()
