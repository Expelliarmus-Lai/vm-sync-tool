import inspect
import unittest

import main


class SingleInstanceTests(unittest.TestCase):
    def test_existing_instance_is_notified_to_show_window(self):
        source = inspect.getsource(main.main)

        self.assertIn("notify_existing_instance()", source)
        self.assertIn("attach_single_instance_socket", source)


if __name__ == "__main__":
    unittest.main()
