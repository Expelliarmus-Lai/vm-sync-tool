import unittest

from vmrun_output import decode_vmrun_stream


class VmrunOutputTests(unittest.TestCase):
    def test_decodes_utf8_guest_error(self):
        message = "该对象不是一个目录"
        self.assertEqual(message, decode_vmrun_stream(message.encode("utf-8")))

    def test_decodes_utf16_bom_output(self):
        message = "虚拟机路径无效"
        self.assertEqual(message, decode_vmrun_stream(message.encode("utf-16")))

    def test_preserves_existing_text_from_test_doubles(self):
        self.assertEqual("already decoded", decode_vmrun_stream("already decoded"))


if __name__ == "__main__":
    unittest.main()
