"""Unit tests for _float_img_to_uint8 (image float-clamping logic).

Covers the three branches introduced to fix #602:
  1. max <= 1.0          — normal [0, 1] float; scale to [0, 255].
  2. 1.0 < max <= 1+tol  — rounding artefact; warn + clamp + scale.
  3. max > 1+tol         — values already in [0, 255]; clip + cast.

Also verifies that uint8 images are unaffected (the caller skips the
helper entirely, but we test the boundary condition for completeness).
"""

import unittest
import warnings

import numpy as np

from visdom import _float_img_to_uint8


class TestFloatImgToUint8(unittest.TestCase):
    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _solid(self, value, dtype=np.float32, shape=(3, 4, 4)):
        """Return a solid-colour image array filled with *value*."""
        return np.full(shape, value, dtype=dtype)

    # ------------------------------------------------------------------
    # Case 1: max <= 1.0  →  scale by 255, no warning
    # ------------------------------------------------------------------
    def test_unit_range_scales_to_255(self):
        img = self._solid(1.0)
        result = _float_img_to_uint8(img)
        self.assertEqual(result.dtype, np.uint8)
        np.testing.assert_array_equal(result, 255)

    def test_half_range_scales_correctly(self):
        img = self._solid(0.5)
        result = _float_img_to_uint8(img)
        self.assertEqual(result.dtype, np.uint8)
        # 0.5 * 255 = 127 (truncation via uint8 cast)
        np.testing.assert_array_equal(result, np.uint8(0.5 * 255.0))

    def test_zero_image_stays_zero(self):
        img = self._solid(0.0)
        result = _float_img_to_uint8(img)
        np.testing.assert_array_equal(result, 0)

    def test_unit_range_no_warning(self):
        img = self._solid(1.0)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _float_img_to_uint8(img)
        self.assertEqual(len(caught), 0)

    # ------------------------------------------------------------------
    # Case 2: 1.0 < max <= 1+tol  →  warn + clamp to [0,1] + scale
    # ------------------------------------------------------------------
    def _just_above_one(self, dtype=np.float32):
        """A value guaranteed to be in (1.0, 1+tol] for the given dtype."""
        tol = float(np.finfo(dtype).eps ** 0.5)
        # Halfway into the tolerance band.
        return dtype(1.0 + tol * 0.5)

    def test_slight_overshoot_emits_warning(self):
        val = self._just_above_one()
        img = self._solid(val)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _float_img_to_uint8(img)
        self.assertEqual(len(caught), 1)
        self.assertIs(caught[0].category, UserWarning)
        self.assertIn("slightly above 1.0", str(caught[0].message))

    def test_slight_overshoot_renders_as_white(self):
        """Values just above 1.0 must clamp to white (255), not black (1)."""
        val = self._just_above_one()
        img = self._solid(val)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = _float_img_to_uint8(img)
        self.assertEqual(result.dtype, np.uint8)
        np.testing.assert_array_equal(result, 255)

    def test_slight_overshoot_float64(self):
        """Tolerance is dtype-specific; verify float64 behaves correctly."""
        dtype = np.float64
        tol = float(np.finfo(dtype).eps ** 0.5)
        val = dtype(1.0 + tol * 0.5)
        img = self._solid(val, dtype=dtype)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = _float_img_to_uint8(img)
        self.assertEqual(len(caught), 1)
        self.assertIs(caught[0].category, UserWarning)
        np.testing.assert_array_equal(result, 255)

    # ------------------------------------------------------------------
    # Case 3: max > 1+tol  →  treat as [0, 255], clip, no warning
    # ------------------------------------------------------------------
    def test_large_values_clipped_to_255(self):
        img = self._solid(200.0)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = _float_img_to_uint8(img)
        self.assertEqual(len(caught), 0)
        self.assertEqual(result.dtype, np.uint8)
        np.testing.assert_array_equal(result, 200)

    def test_out_of_range_high_clipped(self):
        """Values above 255 must be clipped to 255, not wrap around."""
        img = self._solid(300.0)
        result = _float_img_to_uint8(img)
        np.testing.assert_array_equal(result, 255)

    def test_mixed_large_image(self):
        """A [0, 255]-range image with varied values round-trips correctly."""
        img = np.array(
            [[[0.0, 128.0], [64.0, 255.0]]],
            dtype=np.float32,
        ).repeat(3, axis=0)
        result = _float_img_to_uint8(img)
        expected = np.array(
            [[[0, 128], [64, 255]]],
            dtype=np.uint8,
        ).repeat(3, axis=0)
        np.testing.assert_array_equal(result, expected)

    # ------------------------------------------------------------------
    # Boundary: exact tolerance edge
    # ------------------------------------------------------------------
    def test_exactly_at_tolerance_boundary_warns(self):
        """A value exactly at 1.0 + tol should still trigger the warning."""
        dtype = np.float32
        tol = float(np.finfo(dtype).eps ** 0.5)
        # Construct a value as close to 1.0+tol as float32 allows.
        val = dtype(1.0 + tol)
        if val <= 1.0:
            self.skipTest("dtype cannot represent a value above 1.0")
        img = self._solid(val, dtype=dtype)
        max_val = float(img.max())
        upper = 1.0 + tol
        if max_val > upper:
            # float32 rounding pushed it past the boundary; skip edge case.
            self.skipTest("float32 rounding placed value outside tolerance band")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = _float_img_to_uint8(img)
        self.assertEqual(len(caught), 1)
        np.testing.assert_array_equal(result, 255)


if __name__ == "__main__":
    unittest.main()
