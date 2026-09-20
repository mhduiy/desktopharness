import unittest

from mcp_autogui.regression import window_relative_point


class WindowRelativePointTests(unittest.TestCase):
    def test_tracks_window_translation(self):
        target = window_relative_point(
            {"x": 341.0, "y": 197.0, "width": 344.0, "height": 545.0},
            54 / 344,
            321 / 545,
        )
        self.assertEqual(target, {"x": 395.0, "y": 518.0})

    def test_rejects_invalid_relative_coordinate(self):
        with self.assertRaises(ValueError):
            window_relative_point({"x": 0, "y": 0, "width": 1, "height": 1}, 1.1, 0.5)


if __name__ == "__main__":
    unittest.main()
