#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import unittest
import numpy as np
from unittest.mock import patch
import visdom
from visdom import (
    _pc3d_validate_xyz,
    _pc3d_validate_rgb,
    _pc3d_validate_opts,
    _pc3d_downsample,
    _pc3d_compute_bounds,
    _PC3D_HARD_MAX_POINTS,
)


class TestXyzValidation(unittest.TestCase):
    def test_valid_xyz_float32_returned_contiguous(self):
        xyz = np.random.randn(50, 3).astype(np.float32)
        result = _pc3d_validate_xyz(xyz)
        self.assertEqual(result.dtype, np.dtype('<f4'))
        self.assertTrue(result.flags['C_CONTIGUOUS'])
        self.assertEqual(result.shape, (50, 3))

    def test_valid_xyz_float64_cast_to_float32(self):
        xyz = np.random.randn(10, 3)  # float64
        result = _pc3d_validate_xyz(xyz)
        self.assertEqual(result.dtype, np.dtype('<f4'))

    def test_valid_xyz_list_input(self):
        xyz = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        result = _pc3d_validate_xyz(xyz)
        self.assertEqual(result.shape, (2, 3))

    def test_wrong_ncols_raises(self):
        xyz = np.random.randn(10, 2)
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_xyz(xyz)
        self.assertIn('(N, 3)', str(ctx.exception))

    def test_1d_array_raises(self):
        xyz = np.array([1.0, 2.0, 3.0])
        with self.assertRaises(ValueError):
            _pc3d_validate_xyz(xyz)

    def test_empty_raises(self):
        xyz = np.zeros((0, 3))
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_xyz(xyz)
        self.assertIn('at least one point', str(ctx.exception))

    def test_nan_raises(self):
        xyz = np.random.randn(5, 3)
        xyz[2, 1] = float('nan')
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_xyz(xyz)
        self.assertIn('finite', str(ctx.exception))

    def test_inf_raises(self):
        xyz = np.random.randn(5, 3)
        xyz[0, 0] = float('inf')
        with self.assertRaises(ValueError):
            _pc3d_validate_xyz(xyz)

    def test_float64_overflow_to_float32_raises(self):
        # values finite in float64 but overflow float32
        limit = float(np.finfo(np.float32).max)
        xyz = np.array([[limit * 2, 0.0, 0.0]], dtype=np.float64)
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_xyz(xyz)
        self.assertIn('float32', str(ctx.exception))

    def test_non_numeric_raises(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_xyz("not an array")
        self.assertIn('array-like', str(ctx.exception))

    def test_single_point_valid(self):
        xyz = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
        result = _pc3d_validate_xyz(xyz)
        self.assertEqual(result.shape, (1, 3))

    def test_xyz_float32_max_boundary_passes(self):
        # strict > means exact float32 max must be accepted
        f32_max = float(np.finfo(np.float32).max)
        xyz = np.array([[f32_max, 0.0, 0.0]], dtype=np.float64)
        result = _pc3d_validate_xyz(xyz)
        self.assertEqual(result.shape, (1, 3))
        self.assertEqual(result.dtype, np.dtype('<f4'))

    def test_3d_array_raises_with_message(self):
        xyz = np.ones((5, 3, 2))
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_xyz(xyz)
        msg = str(ctx.exception)
        self.assertIn('(N, 3)', msg)
        self.assertIn('(5, 3, 2)', msg)

    def test_one_column_raises(self):
        xyz = np.ones((5, 1))
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_xyz(xyz)
        self.assertIn('(N, 3)', str(ctx.exception))

    def test_overflow_message_contains_scale_guidance(self):
        limit = float(np.finfo(np.float32).max)
        xyz = np.array([[limit * 2, 0.0, 0.0]], dtype=np.float64)
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_xyz(xyz)
        msg = str(ctx.exception)
        self.assertIn('Scale coordinates', msg)
        self.assertIn('float32 range', msg)
        self.assertIn('max |value|', msg)

    def test_none_raises_value_error_not_type_error(self):
        with self.assertRaises(ValueError):
            _pc3d_validate_xyz(None)
        try:
            _pc3d_validate_xyz(None)
        except TypeError:
            self.fail('None should raise ValueError, not TypeError')
        except ValueError:
            pass

    def test_fortran_order_xyz_produces_c_contiguous_result(self):
        xyz_f = np.asfortranarray(
            np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)
        )
        validated = _pc3d_validate_xyz(xyz_f)
        self.assertTrue(validated.flags['C_CONTIGUOUS'],
            'Fortran-order input must produce C-contiguous output')
        np.testing.assert_array_almost_equal(validated, [[1, 2, 3], [4, 5, 6]])

    def test_xyz_tuple_of_tuples_coerces(self):
        xyz = ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))
        result = _pc3d_validate_xyz(xyz)
        self.assertEqual(result.dtype, np.dtype('float32'))
        self.assertEqual(result.shape, (2, 3))

    def test_xyz_numpy_matrix_coerces_to_ndarray(self):
        m = np.matrix([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        result = _pc3d_validate_xyz(m)
        self.assertIsInstance(result, np.ndarray)
        self.assertNotIsInstance(result, np.matrix)
        self.assertEqual(result.dtype, np.dtype('float32'))
        self.assertEqual(result.shape, (2, 3))

    def test_xyz_int32_dtype_coerces_to_float32(self):
        xyz = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.int32)
        result = _pc3d_validate_xyz(xyz)
        self.assertEqual(result.dtype, np.dtype('float32'))
        np.testing.assert_array_almost_equal(result, [[1, 2, 3], [4, 5, 6]])

    def test_xyz_int64_dtype_coerces_to_float32(self):
        xyz = np.array([[10, 20, 30]], dtype=np.int64)
        result = _pc3d_validate_xyz(xyz)
        self.assertEqual(result.dtype, np.dtype('float32'))
        np.testing.assert_array_almost_equal(result, [[10, 20, 30]])

    def test_negative_infinity_raises(self):
        xyz = np.array([[float('-inf'), 0.0, 0.0]], dtype=np.float64)
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_xyz(xyz)
        self.assertIn('finite', str(ctx.exception))

    def test_xyz_output_dtype_always_float32(self):
        for dtype in (np.float16, np.float32, np.float64, np.int32):
            vals = np.array([[1, 2, 3]], dtype=dtype)
            if dtype == np.float16:
                vals = np.array([[1.0, 2.0, 3.0]], dtype=dtype)
            result = _pc3d_validate_xyz(vals)
            self.assertEqual(result.dtype, np.dtype('float32'),
                f'dtype {dtype} input did not produce float32 output')

    def test_xyz_output_c_contiguous_always(self):
        for dtype in (np.float32, np.float64, np.int32):
            xyz = np.array([[1, 2, 3], [4, 5, 6]], dtype=dtype)
            result = _pc3d_validate_xyz(xyz)
            self.assertTrue(result.flags['C_CONTIGUOUS'])


class TestRgbValidation(unittest.TestCase):
    def setUp(self):
        self.N = 20

    def test_none_returns_none(self):
        self.assertIsNone(_pc3d_validate_rgb(None, self.N))

    def test_integer_uint8_valid(self):
        rgb = np.random.randint(0, 256, size=(self.N, 3), dtype=np.uint8)
        result = _pc3d_validate_rgb(rgb, self.N)
        self.assertEqual(result.dtype, np.uint8)
        self.assertEqual(result.shape, (self.N, 3))
        self.assertTrue(result.flags['C_CONTIGUOUS'])

    def test_integer_int32_valid(self):
        rgb = np.random.randint(0, 256, size=(self.N, 3), dtype=np.int32)
        result = _pc3d_validate_rgb(rgb, self.N)
        self.assertEqual(result.dtype, np.uint8)

    def test_integer_out_of_range_raises(self):
        rgb = np.full((self.N, 3), 300, dtype=np.int32)
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_rgb(rgb, self.N)
        self.assertIn('[0, 255]', str(ctx.exception))

    def test_float_0_1_range_scaled(self):
        rgb = np.array([[0.5, 0.25, 1.0]], dtype=np.float32)
        result = _pc3d_validate_rgb(rgb, 1)
        self.assertEqual(result.dtype, np.uint8)
        np.testing.assert_array_equal(result, np.array([[128, 64, 255]], dtype=np.uint8))

    def test_float_0_255_range_kept(self):
        rgb = np.array([[10.7, 128.3, 200.9]], dtype=np.float64)
        result = _pc3d_validate_rgb(rgb, 1)
        self.assertEqual(result.dtype, np.uint8)
        expected = np.round(rgb).clip(0, 255).astype(np.uint8)
        np.testing.assert_array_equal(result, expected)

    def test_float_negative_raises(self):
        rgb = np.full((self.N, 3), -0.1, dtype=np.float32)
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_rgb(rgb, self.N)
        self.assertIn('[0, 1] or [0, 255]', str(ctx.exception))

    def test_float_above_255_raises(self):
        rgb = np.full((self.N, 3), 300.0, dtype=np.float64)
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_rgb(rgb, self.N)
        self.assertIn('[0, 1] or [0, 255]', str(ctx.exception))

    def test_nan_raises(self):
        rgb = np.random.rand(self.N, 3)
        rgb[0, 0] = float('nan')
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_rgb(rgb, self.N)
        self.assertIn('finite', str(ctx.exception))

    def test_wrong_shape_raises(self):
        rgb = np.random.randint(0, 256, size=(self.N + 1, 3), dtype=np.uint8)
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_rgb(rgb, self.N)
        self.assertIn(str(self.N), str(ctx.exception))

    def test_non_numeric_raises(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_rgb("not an array", self.N)
        self.assertIn('array-like', str(ctx.exception))

    def test_bool_array_raises(self):
        rgb = np.ones((self.N, 3), dtype=bool)
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_rgb(rgb, self.N)
        self.assertIn('bool', str(ctx.exception))

    def test_float_max_exactly_one_scales_to_255(self):
        # max == 1.0 must land in the scale-by-255 branch
        rgb = np.array([[1.0, 0.0, 0.5]], dtype=np.float32)
        result = _pc3d_validate_rgb(rgb, 1)
        self.assertEqual(result.dtype, np.uint8)
        np.testing.assert_array_equal(result, np.array([[255, 0, 128]], dtype=np.uint8))

    def test_float_max_255_boundary(self):
        # max == 255.0 must take passthrough branch (no scale)
        rgb = np.array([[255.0, 128.0, 0.0]], dtype=np.float64)
        result = _pc3d_validate_rgb(rgb, 1)
        self.assertEqual(result.dtype, np.uint8)
        np.testing.assert_array_equal(result, np.array([[255, 128, 0]], dtype=np.uint8))

    def test_integer_rgb_negative_raises(self):
        rgb = np.array([[-1, 100, 200]], dtype=np.int32)
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_rgb(rgb, 1)
        msg = str(ctx.exception)
        self.assertIn('[0, 255]', msg)
        self.assertIn('integer', msg)

    def test_integer_rgb_exact_zero_and_255_boundaries_pass(self):
        rgb = np.array([[0, 128, 255], [100, 200, 50]], dtype=np.int32)
        result = _pc3d_validate_rgb(rgb, 2)
        self.assertEqual(result.dtype, np.uint8)
        np.testing.assert_array_equal(
            result, np.array([[0, 128, 255], [100, 200, 50]], dtype=np.uint8)
        )

    def test_float_rgb_just_above_one_is_passthrough_not_scaled(self):
        # max exactly 1.0 → scale branch: 1.0*255 = 255
        rgb_at = np.array([[0.0, 0.5, 1.0]], dtype=np.float64)
        out_at = _pc3d_validate_rgb(rgb_at, 1)
        self.assertEqual(out_at[0, 2], 255, 'max==1.0 must scale to 255')

        # max 1.001 → passthrough: round(1.001)=1, NOT 255
        rgb_over = np.array([[0.0, 0.5, 1.001]], dtype=np.float64)
        out_over = _pc3d_validate_rgb(rgb_over, 1)
        self.assertEqual(out_over[0, 2], 1,
            'max just over 1.0 must take passthrough branch (no multiply by 255)')
        self.assertNotEqual(out_over[0, 2], 255)

        # max 1.5 → passthrough: round(1.5)=2
        rgb_mid = np.array([[0.0, 0.0, 1.5]], dtype=np.float64)
        out_mid = _pc3d_validate_rgb(rgb_mid, 1)
        self.assertEqual(out_mid[0, 2], 2, 'max=1.5 must take passthrough branch')

    def test_rgb_1d_input_raises(self):
        rgb = np.array([100, 150, 200], dtype=np.uint8)
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_rgb(rgb, 1)
        msg = str(ctx.exception)
        self.assertIn('(3,)', msg)

    def test_rgb_wrong_column_count_raises(self):
        N = self.N
        rgb = np.random.randint(0, 256, size=(N, 4), dtype=np.uint8)
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_rgb(rgb, N)
        msg = str(ctx.exception)
        self.assertIn('({}, 3)'.format(N), msg)
        self.assertIn('({}, 4)'.format(N), msg)

    def test_rgb_object_array_raises_type_error(self):
        rgb = np.array([['red', 'green', 'blue'], ['r', 'g', 'b']])
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_rgb(rgb, 2)
        msg = str(ctx.exception)
        self.assertIn('array-like', msg)
        self.assertIn('numeric', msg)

    def test_rgb_complex_array_raises_type_error(self):
        rgb = np.array([[100+50j, 0+0j, 0+0j]], dtype=complex)
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_rgb(rgb, 1)
        self.assertIn('complex', str(ctx.exception).lower())

    def test_float_rgb_all_zeros_takes_scale_path_and_returns_zeros(self):
        rgb = np.zeros((5, 3), dtype=np.float64)
        result = _pc3d_validate_rgb(rgb, 5)
        self.assertEqual(result.dtype, np.uint8)
        np.testing.assert_array_equal(result, np.zeros((5, 3), dtype=np.uint8))

    def test_float_rgb_half_gray_rounds_to_128(self):
        rgb = np.full((2, 3), 0.5, dtype=np.float64)
        result = _pc3d_validate_rgb(rgb, 2)
        self.assertEqual(result.dtype, np.uint8)
        np.testing.assert_array_equal(result, np.full((2, 3), 128, dtype=np.uint8))

    def test_float_rgb_mixed_row_exact_uint8_output(self):
        rgb = np.array([[0.0, 0.5, 1.0]], dtype=np.float64)
        result = _pc3d_validate_rgb(rgb, 1)
        self.assertEqual(result[0, 0], 0)
        self.assertEqual(result[0, 1], 128)
        self.assertEqual(result[0, 2], 255)

    def test_float_rgb_some_values_above_255_raises_value_error(self):
        rgb = np.array([[300.0, 0.0, 0.0]], dtype=np.float64)
        with self.assertRaises(ValueError):
            _pc3d_validate_rgb(rgb, 1)

    def test_rgb_list_of_lists_integer_values_coerces(self):
        rgb = [[255, 0, 0], [0, 255, 0], [0, 0, 255]]
        result = _pc3d_validate_rgb(rgb, 3)
        self.assertEqual(result.dtype, np.uint8)
        self.assertEqual(result.shape, (3, 3))
        self.assertEqual(result[0, 0], 255)

    def test_rgb_float64_in_0_255_passthrough_path(self):
        rgb = np.array([[200.0, 100.0, 50.0]], dtype=np.float64)
        result = _pc3d_validate_rgb(rgb, 1)
        self.assertEqual(result.dtype, np.uint8)
        self.assertEqual(result[0, 0], 200)
        self.assertEqual(result[0, 1], 100)
        self.assertEqual(result[0, 2], 50)


class TestOptsValidation(unittest.TestCase):
    def test_none_opts_returns_empty_dict(self):
        result = _pc3d_validate_opts(None)
        self.assertEqual(result, {})

    def test_markersize_zero_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_opts({'markersize': 0})
        self.assertIn('markersize', str(ctx.exception))

    def test_markersize_negative_raises(self):
        with self.assertRaises(ValueError):
            _pc3d_validate_opts({'markersize': -1.0})

    def test_opacity_below_zero_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_opts({'opacity': -0.1})
        self.assertIn('opacity', str(ctx.exception))

    def test_opacity_above_one_raises(self):
        with self.assertRaises(ValueError):
            _pc3d_validate_opts({'opacity': 1.1})

    def test_max_points_zero_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_opts({'max_points': 0})
        self.assertIn('max_points', str(ctx.exception))

    def test_downsample_none_alone_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_opts({'downsample': 'none'})
        self.assertIn("not a valid value", str(ctx.exception))

    def test_max_points_with_downsample_none_string_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_opts({'max_points': 100, 'downsample': 'none'})
        self.assertIn("not a valid value", str(ctx.exception))

    def test_invalid_downsample_string_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_opts({'downsample': 'uniform'})
        self.assertIn("'stride' or 'random'", str(ctx.exception))

    def test_valid_opts_do_not_raise(self):
        _pc3d_validate_opts({
            'markersize': 3.0, 'opacity': 0.8,
            'max_points': 50000, 'downsample': 'stride',
        })

    def test_markersize_non_numeric_raises(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_opts({'markersize': 'large'})
        self.assertIn('markersize', str(ctx.exception))

    def test_opacity_non_numeric_raises(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_opts({'opacity': 'high'})
        self.assertIn('opacity', str(ctx.exception))

    def test_max_points_float_raises(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_opts({'max_points': 100.5})
        self.assertIn('max_points', str(ctx.exception))

    def test_max_points_bool_raises(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_opts({'max_points': True})
        self.assertIn('max_points', str(ctx.exception))

    def test_markersize_bool_raises(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_opts({'markersize': True})
        self.assertIn('markersize', str(ctx.exception))

    def test_opacity_bool_raises(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_opts({'opacity': False})
        self.assertIn('opacity', str(ctx.exception))

    def test_show_axes_int_raises(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_opts({'show_axes': 0})
        self.assertIn('show_axes', str(ctx.exception))
        self.assertIn('False', str(ctx.exception))

    def test_show_axes_int_one_raises(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_opts({'show_axes': 1})
        self.assertIn('show_axes', str(ctx.exception))

    def test_show_axes_false_valid(self):
        _pc3d_validate_opts({'show_axes': False})

    def test_show_axes_true_valid(self):
        _pc3d_validate_opts({'show_axes': True})

    def test_default_color_wrong_length_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_opts({'default_color': [255, 0]})
        self.assertIn('default_color', str(ctx.exception))

    def test_default_color_out_of_range_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_opts({'default_color': [256, 0, 0]})
        self.assertIn('default_color', str(ctx.exception))

    def test_default_color_valid(self):
        _pc3d_validate_opts({'default_color': [40, 40, 40]})

    def test_bgcolor_non_string_raises(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_opts({'bgcolor': 0xffffff})
        self.assertIn('bgcolor', str(ctx.exception))

    def test_bgcolor_string_valid(self):
        _pc3d_validate_opts({'bgcolor': '#ffffff'})

    def test_seed_bool_raises(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_opts({'seed': True})
        self.assertIn('seed', str(ctx.exception))

    def test_seed_float_raises(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_opts({'seed': 1.5})
        self.assertIn('seed', str(ctx.exception))

    def test_seed_int_valid(self):
        _pc3d_validate_opts({'seed': 42})

    def test_seed_none_valid(self):
        _pc3d_validate_opts({'seed': None})

    def test_opacity_boundary_zero(self):
        _pc3d_validate_opts({'opacity': 0.0})

    def test_opacity_boundary_one(self):
        _pc3d_validate_opts({'opacity': 1.0})

    def test_default_color_bool_element_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_opts({'default_color': [True, 0, 0]})
        self.assertIn('default_color', str(ctx.exception))
        try:
            _pc3d_validate_opts({'default_color': [True, 128, 0]})
            self.fail('expected ValueError')
        except TypeError:
            self.fail('bool element raised TypeError; expected ValueError')
        except ValueError:
            pass

    def test_default_color_negative_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_opts({'default_color': [-1, 0, 0]})
        msg = str(ctx.exception)
        self.assertIn('default_color', msg)
        self.assertIn('[0, 255]', msg)

    def test_default_color_boundary_zero_and_255_pass(self):
        _pc3d_validate_opts({'default_color': [0, 0, 0]})
        _pc3d_validate_opts({'default_color': [255, 255, 255]})

    def test_default_color_non_list_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_opts({'default_color': {'r': 0, 'g': 0, 'b': 0}})
        msg = str(ctx.exception)
        self.assertIn('default_color', msg)
        self.assertIn('list/tuple', msg)

    def test_seed_zero_valid_and_preserved(self):
        result = _pc3d_validate_opts({'seed': 0, 'max_points': 100, 'downsample': 'random'})
        self.assertEqual(result['seed'], 0,
            'seed=0 must be preserved; falsy check would discard it')

    def test_max_points_one_valid(self):
        _pc3d_validate_opts({'max_points': 1})

    def test_max_points_negative_raises(self):
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_opts({'max_points': -1})
        msg = str(ctx.exception)
        self.assertIn('max_points', msg)
        self.assertIn('positive integer', msg)

    def test_opts_none_typed_numeric_fields_raise_type_error(self):
        for field in ('markersize', 'opacity', 'show_axes'):
            with self.subTest(field=field):
                with self.assertRaises(TypeError) as ctx:
                    _pc3d_validate_opts({field: None})
                self.assertIn(field, str(ctx.exception))

    def test_downsample_none_message_contains_omit_guidance(self):
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_opts({'downsample': 'none'})
        msg = str(ctx.exception)
        self.assertIn('omit', msg)
        self.assertIn('entirely', msg)

    def test_markersize_zero_message_contains_gt_zero(self):
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_opts({'markersize': 0})
        self.assertIn('> 0', str(ctx.exception))

    def test_opacity_out_of_range_message_contains_bound_phrase(self):
        with self.assertRaises(ValueError) as ctx:
            _pc3d_validate_opts({'opacity': 1.1})
        self.assertIn('between 0 and 1', str(ctx.exception))

    def test_seed_string_message_contains_guidance(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_opts({'seed': 'abc'})
        msg = str(ctx.exception)
        self.assertIn('None or a non-negative integer', msg)
        self.assertIn('seed', msg)

    def test_bgcolor_message_contains_css_color_string(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_opts({'bgcolor': 0xffffff})
        self.assertIn('CSS color string', str(ctx.exception))

    def test_show_axes_int_message_contains_not_zero_guidance(self):
        with self.assertRaises(TypeError) as ctx:
            _pc3d_validate_opts({'show_axes': 0})
        msg = str(ctx.exception)
        self.assertIn('not 0', msg)
        self.assertIn('show_axes=False', msg)

    def test_unknown_opts_keys_are_preserved(self):
        result = _pc3d_validate_opts({
            'unknown_key': 'foo',
            'another_future_opt': 42,
            'markersize': 3.0,
        })
        self.assertIn('unknown_key', result)
        self.assertIn('another_future_opt', result)

    def test_empty_dict_opts_returns_empty_dict(self):
        result = _pc3d_validate_opts({})
        self.assertEqual(result, {})

    def test_max_points_none_explicit_is_treated_as_absent(self):
        result = _pc3d_validate_opts({'max_points': None})
        self.assertIsNone(result.get('max_points'))


class TestDownsampling(unittest.TestCase):
    def setUp(self):
        self.xyz = np.random.randn(1000, 3).astype(np.float32)
        self.rgb = np.random.randint(0, 256, (1000, 3), dtype=np.uint8)

    def test_no_max_points_returns_full(self):
        xyz_out, rgb_out = _pc3d_downsample(self.xyz, self.rgb, {})
        self.assertEqual(xyz_out.shape[0], 1000)
        self.assertEqual(rgb_out.shape[0], 1000)

    def test_stride_produces_correct_count(self):
        xyz_out, rgb_out = _pc3d_downsample(
            self.xyz, self.rgb, {'max_points': 100, 'downsample': 'stride'}
        )
        self.assertEqual(xyz_out.shape[0], 100)
        self.assertEqual(rgb_out.shape[0], 100)

    def test_random_produces_correct_count(self):
        xyz_out, rgb_out = _pc3d_downsample(
            self.xyz, self.rgb, {'max_points': 200, 'downsample': 'random', 'seed': 42}
        )
        self.assertEqual(xyz_out.shape[0], 200)
        self.assertEqual(rgb_out.shape[0], 200)

    def test_random_reproducible_with_seed(self):
        opts = {'max_points': 50, 'downsample': 'random', 'seed': 7}
        xyz_a, _ = _pc3d_downsample(self.xyz, None, opts)
        xyz_b, _ = _pc3d_downsample(self.xyz, None, opts)
        np.testing.assert_array_equal(xyz_a, xyz_b)

    def test_default_is_stride_when_downsample_not_set(self):
        xyz_out, _ = _pc3d_downsample(self.xyz, None, {'max_points': 100})
        self.assertEqual(xyz_out.shape[0], 100)
        # stride uses linspace(0, N-1, ...) so first point must be self.xyz[0]
        np.testing.assert_array_equal(xyz_out[0], self.xyz[0])

    def test_n_lte_max_points_no_downsample(self):
        xyz_out, _ = _pc3d_downsample(self.xyz, None, {'max_points': 5000})
        self.assertEqual(xyz_out.shape[0], 1000)  # no change

    def test_large_cloud_warning_emitted(self):
        big_xyz = np.random.randn(300_000, 3).astype(np.float32)
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _pc3d_downsample(big_xyz, None, {})
        self.assertTrue(any('200,000' in str(warning.message) for warning in w))
        self.assertTrue(any(issubclass(warning.category, UserWarning) for warning in w))

    def test_n_equals_max_points_exactly_no_downsample(self):
        N = 100
        xyz = np.arange(N * 3, dtype=np.float32).reshape(N, 3)
        for mode in ('stride', 'random', None):
            opts = {'max_points': N}
            if mode is not None:
                opts['downsample'] = mode
            xyz_out, rgb_out = _pc3d_downsample(xyz, None, opts)
            self.assertEqual(xyz_out.shape[0], N,
                msg='mode={}: N==max_points must return full cloud'.format(mode))
            np.testing.assert_array_equal(xyz_out, xyz,
                err_msg='mode={}: data must be unchanged'.format(mode))
            self.assertIsNone(rgb_out)

    def test_no_warning_at_exactly_200k(self):
        import warnings
        xyz = np.zeros((200_000, 3), dtype=np.float32)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            _pc3d_downsample(xyz, None, {})
        user_warns = [x for x in w if issubclass(x.category, UserWarning)]
        self.assertEqual(len(user_warns), 0,
            'N==200_000 must not emit a UserWarning')

    def test_warning_at_200001_with_key_phrases(self):
        import warnings
        xyz = np.zeros((200_001, 3), dtype=np.float32)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            _pc3d_downsample(xyz, None, {})
        user_warns = [x for x in w if issubclass(x.category, UserWarning)]
        self.assertEqual(len(user_warns), 1,
            'N==200_001 must emit exactly one UserWarning')
        msg = str(user_warns[0].message)
        self.assertIn('200,000', msg)
        self.assertIn('inline base64 transport', msg)
        self.assertIn('max_points', msg)

    def test_stride_rgb_and_xyz_use_same_indices(self):
        N = 100
        xyz = np.zeros((N, 3), dtype=np.float32)
        xyz[:, 0] = np.arange(N, dtype=np.float32)
        rgb = np.zeros((N, 3), dtype=np.uint8)
        rgb[:, 0] = np.arange(N, dtype=np.uint8)
        xyz_out, rgb_out = _pc3d_downsample(
            xyz, rgb, {'max_points': 10, 'downsample': 'stride'}
        )
        self.assertEqual(xyz_out.shape[0], 10)
        self.assertEqual(rgb_out.shape[0], 10)
        np.testing.assert_array_equal(
            xyz_out[:, 0].astype(np.uint8), rgb_out[:, 0],
            err_msg='stride: xyz and rgb rows must come from the same source index'
        )

    def test_random_rgb_and_xyz_use_same_indices(self):
        N = 100
        xyz = np.zeros((N, 3), dtype=np.float32)
        xyz[:, 0] = np.arange(N, dtype=np.float32)
        rgb = np.zeros((N, 3), dtype=np.uint8)
        rgb[:, 0] = np.arange(N, dtype=np.uint8)
        xyz_out, rgb_out = _pc3d_downsample(
            xyz, rgb, {'max_points': 10, 'downsample': 'random', 'seed': 7}
        )
        self.assertEqual(xyz_out.shape[0], 10)
        self.assertEqual(rgb_out.shape[0], 10)
        np.testing.assert_array_equal(
            xyz_out[:, 0].astype(np.uint8), rgb_out[:, 0],
            err_msg='random: xyz and rgb rows must come from the same source index'
        )

    def test_random_no_seed_two_calls_differ(self):
        opts = {'max_points': 100, 'downsample': 'random'}
        out_a, _ = _pc3d_downsample(self.xyz, None, opts)
        out_b, _ = _pc3d_downsample(self.xyz, None, opts)
        self.assertFalse(
            np.array_equal(out_a, out_b),
            'Two unseeded random calls returned identical subsets; RNG may be fixed'
        )

    def test_stride_includes_first_and_last_point(self):
        N = 1000
        xyz = np.random.randn(N, 3).astype(np.float32)
        xyz[0] = [999.0, 999.0, 999.0]
        xyz[-1] = [-999.0, -999.0, -999.0]
        xyz_out, _ = _pc3d_downsample(
            xyz, None, {'max_points': 10, 'downsample': 'stride'}
        )
        np.testing.assert_array_equal(xyz_out[0], xyz[0],
            err_msg='stride must always include the first point (index 0)')
        np.testing.assert_array_equal(xyz_out[-1], xyz[-1],
            err_msg='stride must always include the last point (index N-1)')

    def test_seed_zero_reproducible_in_downsample(self):
        opts = {'max_points': 50, 'downsample': 'random', 'seed': 0}
        xyz_a, _ = _pc3d_downsample(self.xyz, None, opts)
        xyz_b, _ = _pc3d_downsample(self.xyz, None, opts)
        np.testing.assert_array_equal(xyz_a, xyz_b,
            err_msg='seed=0 must produce reproducible output; falsy check would discard it')

    def test_max_points_one_returns_single_row(self):
        for mode in ('stride', 'random'):
            xyz_out, rgb_out = _pc3d_downsample(
                self.xyz, self.rgb,
                {'max_points': 1, 'downsample': mode, 'seed': 0}
            )
            self.assertEqual(xyz_out.shape, (1, 3),
                msg='mode={}: max_points=1 must produce exactly one row'.format(mode))
            self.assertEqual(rgb_out.shape, (1, 3),
                msg='mode={}: rgb must also have exactly one row'.format(mode))

    def test_max_points_n_minus_1_removes_exactly_one(self):
        N = self.xyz.shape[0]
        for mode in ('stride', 'random'):
            xyz_out, rgb_out = _pc3d_downsample(
                self.xyz, self.rgb,
                {'max_points': N - 1, 'downsample': mode, 'seed': 0}
            )
            self.assertEqual(xyz_out.shape[0], N - 1,
                msg='mode={}: max_points=N-1 must remove exactly one point'.format(mode))
            self.assertEqual(rgb_out.shape[0], N - 1)

    def test_no_downsample_key_defaults_to_stride_endpoints(self):
        N = 100
        xyz = np.array([[float(i), 0., 0.] for i in range(N)], dtype=np.float32)
        # linspace(0,99,5) → indices [0, 25, 50, 74, 99]
        xyz_out, _ = _pc3d_downsample(xyz, None, {'max_points': 5, 'seed': 42})
        self.assertEqual(xyz_out.shape[0], 5)
        self.assertAlmostEqual(float(xyz_out[0, 0]), 0.0, places=2,
            msg='first output row must be xyz[0] (stride endpoint)')
        self.assertAlmostEqual(float(xyz_out[-1, 0]), 99.0, places=2,
            msg='last output row must be xyz[99] (stride endpoint)')

    def test_max_points_one_rgb_none_does_not_crash(self):
        xyz_out, rgb_out = _pc3d_downsample(
            self.xyz, None, {'max_points': 1, 'downsample': 'stride'}
        )
        self.assertEqual(xyz_out.shape, (1, 3))
        self.assertIsNone(rgb_out)

    def test_stride_max_points_2_returns_exactly_first_and_last(self):
        N = 100
        xyz = np.arange(N * 3, dtype=np.float32).reshape(N, 3)
        out, _ = _pc3d_downsample(xyz, None, {'max_points': 2, 'downsample': 'stride'})
        self.assertEqual(out.shape[0], 2)
        np.testing.assert_array_equal(out[0], xyz[0])
        np.testing.assert_array_equal(out[-1], xyz[N - 1])

    def test_stride_max_points_3_includes_first_middle_last(self):
        N = 100
        xyz = np.zeros((N, 3), dtype=np.float32)
        xyz[:, 0] = np.arange(N, dtype=np.float32)
        out, _ = _pc3d_downsample(xyz, None, {'max_points': 3, 'downsample': 'stride'})
        self.assertEqual(out.shape[0], 3)
        self.assertAlmostEqual(float(out[0, 0]), 0.0)
        self.assertAlmostEqual(float(out[-1, 0]), float(N - 1))

    def test_random_output_has_no_duplicate_rows(self):
        N = 1000
        xyz = np.zeros((N, 3), dtype=np.float32)
        xyz[:, 0] = np.arange(N, dtype=np.float32)
        out, _ = _pc3d_downsample(xyz, None, {'max_points': 100, 'downsample': 'random', 'seed': 42})
        unique_vals = set(float(row[0]) for row in out)
        self.assertEqual(len(unique_vals), out.shape[0], 'random mode must not produce duplicate rows')

    def test_stride_preserves_float32_dtype(self):
        xyz = np.ones((200, 3), dtype=np.float32)
        out, _ = _pc3d_downsample(xyz, None, {'max_points': 50, 'downsample': 'stride'})
        self.assertEqual(out.dtype, np.dtype('float32'))

    def test_random_preserves_float32_dtype(self):
        xyz = np.ones((200, 3), dtype=np.float32)
        out, _ = _pc3d_downsample(xyz, None, {'max_points': 50, 'downsample': 'random', 'seed': 1})
        self.assertEqual(out.dtype, np.dtype('float32'))

    def test_stride_preserves_rgb_uint8_dtype(self):
        N = 200
        xyz = np.ones((N, 3), dtype=np.float32)
        rgb = np.full((N, 3), 128, dtype=np.uint8)
        _, rgb_out = _pc3d_downsample(xyz, rgb, {'max_points': 50, 'downsample': 'stride'})
        self.assertIsNotNone(rgb_out)
        self.assertEqual(rgb_out.dtype, np.dtype('uint8'))

    def test_random_preserves_rgb_uint8_dtype(self):
        N = 200
        xyz = np.ones((N, 3), dtype=np.float32)
        rgb = np.full((N, 3), 200, dtype=np.uint8)
        _, rgb_out = _pc3d_downsample(xyz, rgb, {'max_points': 50, 'downsample': 'random', 'seed': 7})
        self.assertIsNotNone(rgb_out)
        self.assertEqual(rgb_out.dtype, np.dtype('uint8'))

    def test_random_rgb_none_no_crash(self):
        xyz = np.ones((200, 3), dtype=np.float32)
        out, rgb_out = _pc3d_downsample(xyz, None, {'max_points': 50, 'downsample': 'random', 'seed': 3})
        self.assertEqual(out.shape[0], 50)
        self.assertIsNone(rgb_out)

    def test_random_selected_indices_are_valid(self):
        N = 500
        xyz = np.zeros((N, 3), dtype=np.float32)
        xyz[:, 0] = np.arange(N, dtype=np.float32)
        out, _ = _pc3d_downsample(xyz, None, {'max_points': 100, 'downsample': 'random', 'seed': 99})
        for val in out[:, 0]:
            self.assertGreaterEqual(float(val), 0.0)
            self.assertLess(float(val), float(N))

    def test_downsample_random_with_seed_but_no_max_points_is_noop(self):
        xyz = np.ones((10, 3), dtype=np.float32)
        out, _ = _pc3d_downsample(xyz, None, {'downsample': 'random', 'seed': 42})
        self.assertEqual(out.shape[0], 10)
        np.testing.assert_array_equal(out, xyz)

    def test_downsample_stride_explicit_but_no_max_points_is_noop(self):
        xyz = np.ones((10, 3), dtype=np.float32)
        out, _ = _pc3d_downsample(xyz, None, {'downsample': 'stride'})
        self.assertEqual(out.shape[0], 10)
        np.testing.assert_array_equal(out, xyz)

    def test_max_points_larger_than_n_is_noop_with_no_warning(self):
        import warnings
        xyz = np.ones((10, 3), dtype=np.float32)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            out, _ = _pc3d_downsample(xyz, None, {'max_points': 100})
        self.assertEqual(out.shape[0], 10)
        np.testing.assert_array_equal(out, xyz)
        user_warns = [x for x in w if issubclass(x.category, UserWarning)]
        self.assertEqual(len(user_warns), 0)

    def test_stride_output_indices_ascending(self):
        N = 100
        xyz = np.zeros((N, 3), dtype=np.float32)
        xyz[:, 0] = np.arange(N, dtype=np.float32)
        out, _ = _pc3d_downsample(xyz, None, {'max_points': 20, 'downsample': 'stride'})
        vals = out[:, 0].tolist()
        self.assertEqual(vals, sorted(vals), 'stride output must be in ascending index order')

    def test_random_max_points_n_minus_1_returns_n_minus_1_unique_rows(self):
        N = 50
        xyz = np.zeros((N, 3), dtype=np.float32)
        xyz[:, 0] = np.arange(N, dtype=np.float32)
        out, _ = _pc3d_downsample(xyz, None, {'max_points': N - 1, 'downsample': 'random', 'seed': 1})
        self.assertEqual(out.shape[0], N - 1)
        unique_vals = set(float(row[0]) for row in out)
        self.assertEqual(len(unique_vals), N - 1)


class TestPayload(unittest.TestCase):
    def setUp(self):
        self.viz = visdom.Visdom(send=False, use_incoming_socket=False)
        self.xyz = np.random.randn(50, 3).astype(np.float32)

    def _call_and_capture(self, xyz, rgb=None, **kw):
        captured = {}
        def fake_send(msg, endpoint='events', **kwargs):
            captured['msg'] = msg
            return 'win1'
        with patch.object(self.viz, '_send', side_effect=fake_send):
            self.viz.pointcloud3d(xyz, rgb=rgb, **kw)
        return captured['msg']['data'][0]['content']

    def test_version_and_transport(self):
        content = self._call_and_capture(self.xyz)
        self.assertEqual(content['version'], 1)
        self.assertEqual(content['transport'], 'inline_base64')

    def test_xyz_dtype_and_shape(self):
        content = self._call_and_capture(self.xyz)
        self.assertEqual(content['xyz']['dtype'], 'float32')
        self.assertEqual(content['xyz']['shape'], [50, 3])
        self.assertEqual(content['xyz']['encoding'], 'base64')
        self.assertEqual(content['xyz']['byte_order'], 'little')

    def test_no_rgb_omits_rgb_key(self):
        content = self._call_and_capture(self.xyz)
        self.assertNotIn('rgb', content)

    def test_rgb_present_when_provided(self):
        rgb = np.random.randint(0, 256, (50, 3), dtype=np.uint8)
        content = self._call_and_capture(self.xyz, rgb=rgb)
        self.assertIn('rgb', content)
        self.assertEqual(content['rgb']['dtype'], 'uint8')
        self.assertEqual(content['rgb']['shape'], [50, 3])

    def test_num_points_fields(self):
        content = self._call_and_capture(self.xyz)
        self.assertEqual(content['num_points_original'], 50)
        self.assertEqual(content['num_points_rendered'], 50)

    def test_num_points_after_downsample(self):
        xyz = np.random.randn(500, 3).astype(np.float32)
        content = self._call_and_capture(
            xyz, opts={'max_points': 100, 'downsample': 'stride'}
        )
        self.assertEqual(content['num_points_original'], 500)
        self.assertEqual(content['num_points_rendered'], 100)

    def test_bounds_fields_present(self):
        content = self._call_and_capture(self.xyz)
        b = content['bounds']
        self.assertIn('min', b)
        self.assertIn('max', b)
        self.assertIn('center', b)
        self.assertIn('radius', b)
        self.assertEqual(len(b['min']), 3)
        self.assertIsInstance(b['radius'], float)

    def test_bounds_unit_cube(self):
        corners = np.array([
            [-1, -1, -1], [1, -1, -1], [-1, 1, -1], [1, 1, -1],
            [-1, -1,  1], [1, -1,  1], [-1, 1,  1], [1, 1,  1],
        ], dtype=np.float32)
        content = self._call_and_capture(corners)
        b = content['bounds']
        self.assertAlmostEqual(b['center'][0], 0.0, places=5)
        self.assertAlmostEqual(b['radius'], np.sqrt(3), places=3)

    def test_xyz_base64_round_trips(self):
        import base64
        content = self._call_and_capture(self.xyz)
        raw = base64.b64decode(content['xyz']['data'])
        decoded = np.frombuffer(raw, dtype='<f4').reshape(50, 3)
        np.testing.assert_array_almost_equal(decoded, self.xyz)

    def test_xyz_bytes_are_little_endian(self):
        # Ensure bytes decode correctly as LE even on big-endian platforms.
        import base64
        xyz = np.array([[1.5, 2.5, 3.5]], dtype=np.float32)
        content = self._call_and_capture(xyz)
        raw = base64.b64decode(content['xyz']['data'])
        decoded = np.frombuffer(raw, dtype='<f4')
        np.testing.assert_array_almost_equal(decoded, [1.5, 2.5, 3.5])

    def test_hard_cap_raises(self):
        xyz = np.zeros((_PC3D_HARD_MAX_POINTS + 1, 3), dtype=np.float32)
        with self.assertRaises(ValueError) as ctx:
            self.viz.pointcloud3d(xyz)
        self.assertIn('max_points', str(ctx.exception))

    def test_hard_cap_exact_boundary_succeeds(self):
        xyz = np.zeros((_PC3D_HARD_MAX_POINTS, 3), dtype=np.float32)
        captured = {}
        def fake_send(msg, endpoint='events', **kwargs):
            captured['ok'] = True
            return 'win1'
        with patch.object(self.viz, '_send', side_effect=fake_send):
            self.viz.pointcloud3d(xyz)
        self.assertTrue(captured.get('ok'),
            'pointcloud3d must succeed for exactly HARD_MAX points')

    def test_hard_cap_error_message_contains_both_counts_and_guidance(self):
        xyz = np.zeros((_PC3D_HARD_MAX_POINTS + 1, 3), dtype=np.float32)
        with self.assertRaises(ValueError) as ctx:
            self.viz.pointcloud3d(xyz)
        msg = str(ctx.exception)
        self.assertIn('hard maximum', msg)
        self.assertIn('max_points', msg)
        self.assertIn('{:,}'.format(_PC3D_HARD_MAX_POINTS + 1), msg)
        self.assertIn('{:,}'.format(_PC3D_HARD_MAX_POINTS), msg)

    def test_xyz_and_rgb_shapes_equal_after_downsample(self):
        import base64
        N = 100
        xyz = np.array([[float(i)] * 3 for i in range(N)], dtype=np.float32)
        rgb = np.array([[i] * 3 for i in range(N)], dtype=np.uint8)
        content = self._call_and_capture(
            xyz, rgb=rgb, opts={'max_points': 10, 'downsample': 'random', 'seed': 42}
        )
        self.assertEqual(content['xyz']['shape'][0], 10)
        self.assertEqual(content['rgb']['shape'][0], 10)
        self.assertEqual(content['xyz']['shape'][0], content['rgb']['shape'][0])
        raw_xyz = base64.b64decode(content['xyz']['data'])
        raw_rgb = base64.b64decode(content['rgb']['data'])
        xyz_dec = np.frombuffer(raw_xyz, dtype='<f4').reshape(10, 3)
        rgb_dec = np.frombuffer(raw_rgb, dtype=np.uint8).reshape(10, 3)
        for j in range(10):
            self.assertAlmostEqual(
                xyz_dec[j, 0], float(rgb_dec[j, 0]), delta=0.6,
                msg='xyz[{}] and rgb[{}] must originate from the same source row'.format(j, j)
            )

    def test_num_points_original_is_pre_downsample(self):
        xyz = np.random.randn(300, 3).astype(np.float32)
        content = self._call_and_capture(
            xyz, opts={'max_points': 30, 'downsample': 'random', 'seed': 1}
        )
        self.assertEqual(content['num_points_original'], 300)
        self.assertEqual(content['num_points_rendered'], 30)
        self.assertGreater(content['num_points_original'], content['num_points_rendered'])

    def test_num_points_rendered_never_exceeds_original(self):
        xyz = np.random.randn(30, 3).astype(np.float32)
        content = self._call_and_capture(xyz, opts={'max_points': 1000})
        self.assertEqual(content['num_points_original'], 30)
        self.assertEqual(content['num_points_rendered'], 30)
        self.assertLessEqual(content['num_points_rendered'], content['num_points_original'])

    def test_xyz_data_byte_length_matches_shape_product(self):
        import base64
        xyz = np.random.randn(73, 3).astype(np.float32)
        content = self._call_and_capture(xyz)
        raw = base64.b64decode(content['xyz']['data'])
        n_values = len(raw) // 4
        shape_product = content['xyz']['shape'][0] * content['xyz']['shape'][1]
        self.assertEqual(n_values, shape_product)
        self.assertEqual(content['xyz']['shape'][0], content['num_points_rendered'])
        self.assertEqual(content['xyz']['shape'][1], 3)

    def test_rgb_data_byte_length_matches_shape_product(self):
        import base64
        rgb = np.random.randint(0, 256, (73, 3), dtype=np.uint8)
        xyz = np.random.randn(73, 3).astype(np.float32)
        content = self._call_and_capture(xyz, rgb=rgb)
        raw = base64.b64decode(content['rgb']['data'])
        shape_product = content['rgb']['shape'][0] * content['rgb']['shape'][1]
        self.assertEqual(len(raw), shape_product)
        self.assertEqual(content['rgb']['shape'][0], content['num_points_rendered'])
        self.assertEqual(content['rgb']['shape'][1], 3)

    def test_rgb_base64_round_trips(self):
        import base64
        rgb = np.array([[255, 0, 128], [10, 200, 50]], dtype=np.uint8)
        xyz = np.zeros((2, 3), dtype=np.float32)
        content = self._call_and_capture(xyz, rgb=rgb)
        raw = base64.b64decode(content['rgb']['data'])
        decoded = np.frombuffer(raw, dtype=np.uint8).reshape(2, 3)
        np.testing.assert_array_equal(decoded, rgb)

    def test_win_env_endpoint_forwarded_to_send(self):
        captured = {}
        def fake_send(msg, endpoint='events', **kwargs):
            captured['msg'] = msg
            captured['endpoint'] = endpoint
            return 'sent_win'
        xyz = np.random.randn(5, 3).astype(np.float32)
        with patch.object(self.viz, '_send', side_effect=fake_send):
            ret = self.viz.pointcloud3d(
                xyz, win='my_win', env='my_env', opts={'title': 'test_title'}
            )
        msg = captured['msg']
        self.assertEqual(msg['win'], 'my_win')
        self.assertEqual(msg['eid'], 'my_env')
        self.assertEqual(msg['opts'].get('title'), 'test_title')
        self.assertNotIn('layout', msg)
        self.assertEqual(captured['endpoint'], 'events')
        self.assertEqual(ret, 'sent_win')

    def test_opts_title_and_backend_opts_forwarded_to_send(self):
        captured = {}
        def fake_send(msg, endpoint='events', **kwargs):
            captured['msg'] = msg
            return 'w'
        with patch.object(self.viz, '_send', side_effect=fake_send):
            self.viz.pointcloud3d(
                self.xyz,
                opts={
                    'title': 'My Cloud',
                    'markersize': 3.0,
                    'max_points': 1000,
                    'downsample': 'stride',
                    'seed': 7,
                }
            )
        opts_sent = captured['msg']['opts']
        self.assertEqual(opts_sent.get('title'), 'My Cloud')
        self.assertAlmostEqual(opts_sent.get('markersize'), 3.0)
        self.assertIn('max_points', opts_sent)
        self.assertIn('downsample', opts_sent)

    def test_rgb_validation_bool_dtype_propagates_type_error(self):
        rgb = np.ones((50, 3), dtype=bool)
        with patch.object(self.viz, '_send', return_value='win1'):
            with self.assertRaises(TypeError) as ctx:
                self.viz.pointcloud3d(self.xyz, rgb=rgb)
        self.assertIn('bool', str(ctx.exception))

    def test_opts_validation_error_propagates(self):
        with patch.object(self.viz, '_send', return_value='win1'):
            with self.assertRaises(ValueError) as ctx:
                self.viz.pointcloud3d(self.xyz, opts={'markersize': -1})
        self.assertIn('markersize', str(ctx.exception))

    def test_xyz_type_error_propagates(self):
        with patch.object(self.viz, '_send', return_value='win1'):
            with self.assertRaises(TypeError) as ctx:
                self.viz.pointcloud3d('not_an_array')
        self.assertIn('array-like', str(ctx.exception))

    def test_bounds_computed_on_rendered_subset_not_original(self):
        xyz = np.zeros((100, 3), dtype=np.float32)
        xyz[0] = [100.0, 0.0, 0.0]
        content = self._call_and_capture(
            xyz, opts={'max_points': 10, 'downsample': 'stride'}
        )
        b = content['bounds']
        self.assertAlmostEqual(b['max'][0], 100.0, places=3,
            msg='bounds must include the extreme point that stride kept')
        self.assertEqual(content['xyz']['shape'][0], content['num_points_rendered'])

    def test_win_reuse_does_not_raise(self):
        calls = []
        def fake_send(msg, endpoint='events', **kwargs):
            calls.append(msg['win'])
            return msg['win']
        with patch.object(self.viz, '_send', side_effect=fake_send):
            r1 = self.viz.pointcloud3d(self.xyz, win='mywin')
            r2 = self.viz.pointcloud3d(self.xyz, win='mywin')
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], 'mywin')
        self.assertEqual(calls[1], 'mywin')

    def test_win_none_env_none_passthrough(self):
        captured = {}
        def fake_send(msg, endpoint='events', **kwargs):
            captured['msg'] = msg
            return 'auto_win'
        with patch.object(self.viz, '_send', side_effect=fake_send):
            self.viz.pointcloud3d(self.xyz, win=None, env=None)
        self.assertIsNone(captured['msg']['win'])
        self.assertIsNone(captured['msg']['eid'])

    def test_return_value_is_forwarded_from_send(self):
        def fake_send(msg, endpoint='events', **kwargs):
            return 'my_window_id'
        with patch.object(self.viz, '_send', side_effect=fake_send):
            ret = self.viz.pointcloud3d(self.xyz)
        self.assertEqual(ret, 'my_window_id')

    def test_return_value_none_when_send_returns_none(self):
        def fake_send(msg, endpoint='events', **kwargs):
            return None
        with patch.object(self.viz, '_send', side_effect=fake_send):
            ret = self.viz.pointcloud3d(self.xyz)
        self.assertIsNone(ret)

    def test_send_exception_propagates(self):
        def fake_send(msg, endpoint='events', **kwargs):
            raise RuntimeError('network failure')
        with patch.object(self.viz, '_send', side_effect=fake_send):
            with self.assertRaises(RuntimeError):
                self.viz.pointcloud3d(self.xyz)

    def test_message_data_item_type_is_pointcloud3d(self):
        captured = {}
        def fake_send(msg, endpoint='events', **kwargs):
            captured['msg'] = msg
            return 'win'
        with patch.object(self.viz, '_send', side_effect=fake_send):
            self.viz.pointcloud3d(self.xyz)
        self.assertEqual(captured['msg']['data'][0]['type'], 'pointcloud3d')

    def test_eid_key_matches_env_parameter(self):
        captured = {}
        def fake_send(msg, endpoint='events', **kwargs):
            captured['msg'] = msg
            return 'win'
        with patch.object(self.viz, '_send', side_effect=fake_send):
            self.viz.pointcloud3d(self.xyz, env='my_env')
        self.assertEqual(captured['msg']['eid'], 'my_env')

    def test_bgcolor_round_trips_through_opts_to_payload(self):
        captured = {}
        def fake_send(msg, endpoint='events', **kwargs):
            captured['msg'] = msg
            return 'win'
        with patch.object(self.viz, '_send', side_effect=fake_send):
            self.viz.pointcloud3d(self.xyz, opts={'bgcolor': '#ff0000'})
        self.assertEqual(captured['msg']['opts'].get('bgcolor'), '#ff0000')


class TestBoundsHelper(unittest.TestCase):
    def test_bounds_unit_cube(self):
        corners = np.array([
            [-1, -1, -1], [1, 1, 1],
        ], dtype=np.float32)
        b = _pc3d_compute_bounds(corners)
        self.assertAlmostEqual(b['center'][0], 0.0, places=5)
        self.assertAlmostEqual(b['min'][0], -1.0, places=5)
        self.assertAlmostEqual(b['max'][0], 1.0, places=5)
        self.assertAlmostEqual(b['radius'], np.sqrt(3), places=3)

    def test_bounds_single_point(self):
        xyz = np.array([[3.0, 4.0, 5.0]], dtype=np.float32)
        b = _pc3d_compute_bounds(xyz)
        self.assertAlmostEqual(b['center'][0], 3.0, places=5)
        self.assertAlmostEqual(b['center'][1], 4.0, places=5)
        self.assertAlmostEqual(b['center'][2], 5.0, places=5)
        # single-point cloud: raw radius 0 → clamped to 1e-4 to prevent camera clipping
        self.assertGreater(b['radius'], 0.0)
        self.assertAlmostEqual(b['radius'], 1e-4, places=6)
        np.testing.assert_array_almost_equal(b['min'], [3.0, 4.0, 5.0])
        np.testing.assert_array_almost_equal(b['max'], [3.0, 4.0, 5.0])

    def test_bounds_degenerate_coincident_points_radius_clamped(self):
        for n in (1, 2, 3):
            xyz = np.full((n, 3), [5.0, 5.0, 5.0], dtype=np.float32)
            b = _pc3d_compute_bounds(xyz)
            self.assertAlmostEqual(b['radius'], 1e-4, places=6,
                msg='N={}: radius must be clamped to 1e-4'.format(n))
            self.assertGreater(b['radius'], 0.0)
            np.testing.assert_array_almost_equal(
                b['center'], [5.0, 5.0, 5.0],
                err_msg='N={}: center must be at the coincident point'.format(n)
            )
            np.testing.assert_array_almost_equal(b['min'], [5.0, 5.0, 5.0])
            np.testing.assert_array_almost_equal(b['max'], [5.0, 5.0, 5.0])

    def test_bounds_center_and_radius_are_python_floats(self):
        xyz = np.random.randn(30, 3).astype(np.float32)
        b = _pc3d_compute_bounds(xyz)
        self.assertIsInstance(b['center'], list)
        self.assertEqual(len(b['center']), 3)
        for v in b['center']:
            self.assertIsInstance(v, float,
                'center elements must be Python float, not numpy scalar')
        self.assertIsInstance(b['radius'], float, 'radius must be Python float')
        self.assertIsInstance(b['min'], list)
        self.assertIsInstance(b['max'], list)
        for v in b['min'] + b['max']:
            self.assertIsInstance(v, float,
                'min/max elements must be Python float, not numpy scalar')

    def test_bounds_all_negative_coordinates(self):
        xyz = np.array([
            [-10.0, -5.0, -1.0],
            [-8.0,  -3.0, -4.0],
            [-12.0, -7.0, -2.0],
        ], dtype=np.float32)
        b = _pc3d_compute_bounds(xyz)
        np.testing.assert_allclose(b['min'], [-12.0, -7.0, -4.0], atol=1e-5)
        np.testing.assert_allclose(b['max'], [-8.0, -3.0, -1.0], atol=1e-5)
        np.testing.assert_allclose(b['center'], [-10.0, -5.0, -2.5], atol=1e-5)
        center = np.array([-10.0, -5.0, -2.5])
        expected_radius = max(float(np.linalg.norm(pt - center)) for pt in xyz)
        self.assertAlmostEqual(b['radius'], expected_radius, places=3)
        self.assertGreater(b['radius'], 0.0)

    def test_bounds_asymmetric_off_origin(self):
        xyz = np.array([[10.0, 0.0, 0.0], [20.0, 0.0, 0.0]], dtype=np.float32)
        b = _pc3d_compute_bounds(xyz)
        np.testing.assert_allclose(b['center'], [15.0, 0.0, 0.0], atol=1e-4)
        self.assertAlmostEqual(b['radius'], 5.0, places=3,
            msg='radius must be distance from center [15,0,0] to endpoints, not from origin')
        self.assertFalse(
            all(abs(c) < 1e-6 for c in b['center']),
            'center must not be at the coordinate origin for an off-origin cloud'
        )

    def test_bounds_flat_degenerate_axis(self):
        xyz = np.array([
            [1.0, 0.0, 0.0],
            [3.0, 0.0, 0.0],
            [2.0, 4.0, 0.0],
        ], dtype=np.float32)
        b = _pc3d_compute_bounds(xyz)
        self.assertAlmostEqual(b['min'][2], 0.0, places=6)
        self.assertAlmostEqual(b['max'][2], 0.0, places=6)
        self.assertAlmostEqual(b['center'][2], 0.0, places=6)
        self.assertGreater(b['radius'], 0.0,
            'radius must be positive even when one axis is degenerate')
        self.assertTrue(
            all(np.isfinite(v) for v in b['center']),
            'center must contain only finite values'
        )

    def test_bounds_far_from_origin_cluster(self):
        xyz = np.array([
            [1000.0, 1000.0, 1000.0],
            [1010.0, 1000.0, 1000.0],
            [1000.0, 1010.0, 1000.0],
        ], dtype=np.float32)
        b = _pc3d_compute_bounds(xyz)
        np.testing.assert_allclose(b['center'], [1005.0, 1005.0, 1000.0], atol=1e-3)
        self.assertGreater(b['radius'], 0.0)
        self.assertTrue(all(np.isfinite(v) for v in b['center']))

    def test_bounds_line_cloud_same_x_same_y_varying_z(self):
        xyz = np.array([
            [5.0, 5.0, 0.0],
            [5.0, 5.0, 10.0],
            [5.0, 5.0, 20.0],
        ], dtype=np.float32)
        b = _pc3d_compute_bounds(xyz)
        np.testing.assert_allclose(b['center'], [5.0, 5.0, 10.0], atol=1e-4)
        self.assertAlmostEqual(b['min'][0], 5.0, places=4)
        self.assertAlmostEqual(b['max'][0], 5.0, places=4)
        self.assertGreater(b['radius'], 0.0)

    def test_bounds_center_is_midpoint_of_min_max_not_mean_of_points(self):
        xyz = np.array([
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [10.0, 10.0, 10.0],
        ], dtype=np.float32)
        b = _pc3d_compute_bounds(xyz)
        # mean of points = [2.5, 2.5, 2.5]; midpoint of min/max = [5, 5, 5]
        np.testing.assert_allclose(b['center'], [5.0, 5.0, 5.0], atol=1e-4,
            err_msg='center must be midpoint of min/max, not mean of all points')

    def test_bounds_two_points_center_is_exact_midpoint(self):
        xyz = np.array([[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]], dtype=np.float32)
        b = _pc3d_compute_bounds(xyz)
        np.testing.assert_allclose(b['center'], [5.0, 5.0, 5.0], atol=1e-4)

    def test_bounds_exact_keys_no_extras_no_missing(self):
        xyz = np.random.randn(10, 3).astype(np.float32)
        b = _pc3d_compute_bounds(xyz)
        self.assertEqual(sorted(b.keys()), ['center', 'max', 'min', 'radius'])

    def test_bounds_min_max_are_lists_of_python_floats(self):
        xyz = np.random.randn(20, 3).astype(np.float32)
        b = _pc3d_compute_bounds(xyz)
        self.assertIsInstance(b['min'], list)
        self.assertIsInstance(b['max'], list)
        for v in b['min']:
            self.assertIsInstance(v, float)
        for v in b['max']:
            self.assertIsInstance(v, float)

    def test_bounds_min_max_correct_per_axis(self):
        xyz = np.array([
            [1.0, 10.0, 100.0],
            [2.0, 8.0, 50.0],
            [3.0, 12.0, 75.0],
        ], dtype=np.float32)
        b = _pc3d_compute_bounds(xyz)
        np.testing.assert_allclose(b['min'], [1.0, 8.0, 50.0], atol=1e-5)
        np.testing.assert_allclose(b['max'], [3.0, 12.0, 100.0], atol=1e-5)

    def test_bounds_large_cloud_radius_positive_center_finite(self):
        rng = np.random.default_rng(0)
        xyz = rng.standard_normal((10000, 3)).astype(np.float32)
        b = _pc3d_compute_bounds(xyz)
        self.assertGreater(b['radius'], 0.0)
        self.assertTrue(all(np.isfinite(v) for v in b['center']))
        self.assertEqual(len(b['center']), 3)

    def test_bounds_very_small_extent_radius_clamped(self):
        xyz = np.array([
            [1.0, 1.0, 1.0],
            [1.0 + 1e-7, 1.0, 1.0],
            [1.0, 1.0 + 1e-7, 1.0],
        ], dtype=np.float32)
        b = _pc3d_compute_bounds(xyz)
        self.assertGreater(b['radius'], 0.0)
        self.assertTrue(np.isfinite(b['radius']))


class TestIntegrationFullPipeline(unittest.TestCase):
    """End-to-end tests through the full pointcloud3d() call."""

    def setUp(self):
        self.viz = visdom.Visdom(
            server='http://localhost', port=9999, raise_exceptions=False
        )

    def _capture(self, xyz, **kwargs):
        captured = {}
        def fake_send(msg, endpoint='events', **kwargs2):
            captured['msg'] = msg
            return 'win_id'
        with patch.object(self.viz, '_send', side_effect=fake_send):
            ret = self.viz.pointcloud3d(xyz, **kwargs)
        captured['ret'] = ret
        return captured

    def test_full_pipeline_xyz_rgb_opts_all_together(self):
        xyz = np.random.randn(50, 3).astype(np.float32)
        rgb = np.random.randint(0, 256, size=(50, 3), dtype=np.uint8)
        captured = self._capture(xyz, rgb=rgb, win='w', env='e', opts={
            'title': 'test', 'markersize': 3.0, 'opacity': 0.8,
            'bgcolor': '#000000', 'show_axes': True,
        })
        msg = captured['msg']
        self.assertEqual(msg['data'][0]['type'], 'pointcloud3d')
        self.assertIn('xyz', msg['data'][0]['content'])
        self.assertIn('rgb', msg['data'][0]['content'])
        self.assertEqual(msg['opts'].get('title'), 'test')
        self.assertEqual(msg['opts'].get('bgcolor'), '#000000')

    def test_list_input_full_pipeline_payload_correct(self):
        xyz_list = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
        captured = self._capture(xyz_list)
        content = captured['msg']['data'][0]['content']
        self.assertIn('xyz', content)
        self.assertEqual(content['num_points_original'], 3)

    def test_n1_single_point_rgb_none_empty_opts_full_pipeline(self):
        xyz = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
        captured = self._capture(xyz)
        content = captured['msg']['data'][0]['content']
        self.assertEqual(content['num_points_original'], 1)
        self.assertEqual(content['num_points_rendered'], 1)
        self.assertNotIn('rgb', content)

    def test_n200001_warning_fires_but_send_still_completes(self):
        import warnings
        xyz = np.zeros((200_001, 3), dtype=np.float32)
        captured = {}
        def fake_send(msg, endpoint='events', **kwargs):
            captured['msg'] = msg
            return 'win'
        with patch.object(self.viz, '_send', side_effect=fake_send):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter('always')
                self.viz.pointcloud3d(xyz)
        user_warns = [x for x in w if issubclass(x.category, UserWarning)]
        self.assertGreater(len(user_warns), 0)
        self.assertIn('msg', captured)

    def test_downsample_error_propagates_before_encoding(self):
        xyz = np.zeros((10, 3), dtype=np.float32)
        called = []
        def fake_send(msg, endpoint='events', **kwargs):
            called.append(True)
            return 'win'
        with patch.object(self.viz, '_send', side_effect=fake_send):
            with self.assertRaises(ValueError):
                self.viz.pointcloud3d(xyz, opts={'downsample': 'none'})
        self.assertEqual(len(called), 0, '_send must not be called when opts raises')

    def test_xyz_nan_propagates_before_send(self):
        xyz = np.array([[float('nan'), 0.0, 0.0]], dtype=np.float64)
        called = []
        def fake_send(msg, endpoint='events', **kwargs):
            called.append(True)
            return 'win'
        with patch.object(self.viz, '_send', side_effect=fake_send):
            with self.assertRaises(ValueError):
                self.viz.pointcloud3d(xyz)
        self.assertEqual(len(called), 0)

    def test_rgb_shape_mismatch_propagates_before_send(self):
        xyz = np.zeros((5, 3), dtype=np.float32)
        rgb = np.zeros((3, 3), dtype=np.uint8)
        called = []
        def fake_send(msg, endpoint='events', **kwargs):
            called.append(True)
            return 'win'
        with patch.object(self.viz, '_send', side_effect=fake_send):
            with self.assertRaises((ValueError, TypeError)):
                self.viz.pointcloud3d(xyz, rgb=rgb)
        self.assertEqual(len(called), 0)

    def test_return_value_string_from_send(self):
        def fake_send(msg, endpoint='events', **kwargs):
            return 'specific_window_42'
        with patch.object(self.viz, '_send', side_effect=fake_send):
            ret = self.viz.pointcloud3d(self._simple_xyz())
        self.assertEqual(ret, 'specific_window_42')

    def _simple_xyz(self):
        return np.zeros((3, 3), dtype=np.float32)


