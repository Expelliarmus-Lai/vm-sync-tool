import unittest

from syncer import LogEvent
from ui import LogPanel


class FakeTextbox:
    def __init__(self):
        self.inserts = []
        self.tags = {}

    def configure(self, **_kwargs):
        pass

    def insert(self, index, text, tag):
        self.inserts.append((index, text, tag))

    def tag_config(self, tag, **kwargs):
        self.tags[tag] = kwargs

    def delete(self, *_args):
        pass

    def see(self, *_args):
        pass


class LogPanelColorTests(unittest.TestCase):
    def test_log_header_uses_vector_icon(self):
        import inspect

        source = inspect.getsource(LogPanel)

        self.assertIn('"list"', source)
        self.assertIn("pack_section_title", source)
        self.assertNotIn("▤  同步日志", source)
        self.assertNotIn("📋  同步日志", source)

    def test_each_log_level_uses_independent_message_tag(self):
        panel = object.__new__(LogPanel)
        panel.textbox = FakeTextbox()
        panel._line_count = 0

        panel.append(LogEvent("✓", "ok", "success"))
        panel.append(LogEvent("✗", "bad", "error"))
        panel.append(LogEvent("⚠", "warn", "warning"))

        message_tags = [
            tag
            for _index, text, tag in panel.textbox.inserts
            if "ok" in text or "bad" in text or "warn" in text
        ]

        self.assertEqual(["msg_success", "msg_error", "msg_warning"], message_tags)
        self.assertNotIn("msg_tag", panel.textbox.tags)


if __name__ == "__main__":
    unittest.main()
