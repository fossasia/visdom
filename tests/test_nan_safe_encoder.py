import json
import math
import unittest

from visdom import NanSafeEncoder, _sanitize_nans


class TestSanitizeNans(unittest.TestCase):
    """Tests for _sanitize_nans() helper."""

    def test_nan_replaced(self):
        self.assertIsNone(_sanitize_nans(float("nan")))

    def test_inf_replaced(self):
        self.assertIsNone(_sanitize_nans(float("inf")))

    def test_neg_inf_replaced(self):
        self.assertIsNone(_sanitize_nans(float("-inf")))

    def test_normal_float_unchanged(self):
        self.assertEqual(_sanitize_nans(3.14), 3.14)

    def test_zero_unchanged(self):
        self.assertEqual(_sanitize_nans(0.0), 0.0)

    def test_int_unchanged(self):
        self.assertEqual(_sanitize_nans(42), 42)

    def test_string_unchanged(self):
        self.assertEqual(_sanitize_nans("hello"), "hello")

    def test_none_unchanged(self):
        self.assertIsNone(_sanitize_nans(None))

    def test_flat_list(self):
        result = _sanitize_nans([1.0, float("nan"), 3.0])
        self.assertEqual(result, [1.0, None, 3.0])

    def test_flat_dict(self):
        result = _sanitize_nans({"a": float("nan"), "b": 2.0})
        self.assertEqual(result, {"a": None, "b": 2.0})

    def test_nested_dict_in_list(self):
        data = [{"x": float("inf")}, {"y": 1.0}]
        result = _sanitize_nans(data)
        self.assertEqual(result, [{"x": None}, {"y": 1.0}])

    def test_nested_list_in_dict(self):
        data = {"vals": [float("-inf"), 5.0]}
        result = _sanitize_nans(data)
        self.assertEqual(result, {"vals": [None, 5.0]})

    def test_deeply_nested(self):
        data = {"a": {"b": {"c": [float("nan")]}}}
        result = _sanitize_nans(data)
        self.assertEqual(result, {"a": {"b": {"c": [None]}}})

    def test_tuple_converted_to_list(self):
        result = _sanitize_nans((1.0, float("nan")))
        self.assertEqual(result, [1.0, None])

    def test_empty_structures(self):
        self.assertEqual(_sanitize_nans([]), [])
        self.assertEqual(_sanitize_nans({}), {})


class TestNanSafeEncoder(unittest.TestCase):
    """Tests for NanSafeEncoder JSON encoder."""

    def _encode(self, obj):
        return json.loads(json.dumps(obj, cls=NanSafeEncoder))

    def test_nan_becomes_null(self):
        result = self._encode({"x": float("nan")})
        self.assertIsNone(result["x"])

    def test_inf_becomes_null(self):
        result = self._encode({"x": float("inf")})
        self.assertIsNone(result["x"])

    def test_neg_inf_becomes_null(self):
        result = self._encode({"x": float("-inf")})
        self.assertIsNone(result["x"])

    def test_normal_values_preserved(self):
        data = {"a": 1, "b": 2.5, "c": "text", "d": True, "e": None}
        self.assertEqual(self._encode(data), data)

    def test_list_with_nans(self):
        result = self._encode([1.0, float("nan"), 3.0, float("inf")])
        self.assertEqual(result, [1.0, None, 3.0, None])

    def test_nested_structure(self):
        data = {
            "traces": [
                {"x": [1.0, float("nan")], "y": [float("inf"), 2.0]},
            ],
            "name": "test",
        }
        result = self._encode(data)
        self.assertEqual(result["traces"][0]["x"], [1.0, None])
        self.assertEqual(result["traces"][0]["y"], [None, 2.0])
        self.assertEqual(result["name"], "test")

    def test_output_is_valid_json(self):
        data = {"x": [float("nan"), float("inf"), float("-inf"), 1.0]}
        encoded = json.dumps(data, cls=NanSafeEncoder)
        # Should not contain NaN/Infinity literals
        self.assertNotIn("NaN", encoded)
        self.assertNotIn("Infinity", encoded)
        # Should be parseable
        json.loads(encoded)

    def test_scatter_like_payload(self):
        """Simulates a scatter plot data payload with NaN values."""
        data = {
            "x": [0.1, 0.2, float("nan"), 0.4],
            "y": [1.0, float("inf"), 3.0, 4.0],
            "name": "trace1",
            "type": "scatter",
        }
        result = self._encode(data)
        self.assertEqual(result["x"], [0.1, 0.2, None, 0.4])
        self.assertEqual(result["y"], [1.0, None, 3.0, 4.0])

    def test_heatmap_like_payload(self):
        """Simulates a heatmap z-matrix with NaN values."""
        data = {
            "z": [[1.0, float("nan")], [float("inf"), 4.0]],
            "type": "heatmap",
        }
        result = self._encode(data)
        self.assertEqual(result["z"], [[1.0, None], [None, 4.0]])


if __name__ == "__main__":
    unittest.main()
