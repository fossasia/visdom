import unittest
from io import BytesIO
import base64 as b64
import numpy as np
from PIL import Image
import visdom


class TestImageRendering(unittest.TestCase):
    def setUp(self):
        self.viz = visdom.Visdom(send=False, use_incoming_socket=False)

    def _decode_image_payload(self, result):
        msg, endpoint = result
        self.assertEqual(endpoint, "events")
        data_entry = msg["data"][0]
        self.assertEqual(data_entry["type"], "image")
        
        src_url = data_entry["content"]["src"]
        prefix = "data:image/png;base64,"
        self.assertTrue(src_url.startswith(prefix))
        
        b64data = src_url[len(prefix):]
        img_bytes = b64.b64decode(b64data)
        return Image.open(BytesIO(img_bytes))

    def test_grayscale_image_2d(self):
        # 2D Grayscale image of shape (H, W)
        img = np.random.randint(0, 256, (120, 80), dtype=np.uint8)
        result = self.viz.image(img)
        
        pil_img = self._decode_image_payload(result)
        self.assertEqual(pil_img.mode, "L")
        self.assertEqual(pil_img.size, (80, 120))  # (W, H)

    def test_grayscale_image_3d_single_channel(self):
        # 3D Grayscale image of shape (1, H, W)
        img = np.random.randint(0, 256, (1, 120, 80), dtype=np.uint8)
        result = self.viz.image(img)
        
        pil_img = self._decode_image_payload(result)
        self.assertEqual(pil_img.mode, "L")
        self.assertEqual(pil_img.size, (80, 120))  # (W, H)

    def test_rgb_image(self):
        # RGB image of shape (3, H, W)
        img = np.random.randint(0, 256, (3, 120, 80), dtype=np.uint8)
        result = self.viz.image(img)
        
        pil_img = self._decode_image_payload(result)
        self.assertEqual(pil_img.mode, "RGB")
        self.assertEqual(pil_img.size, (80, 120))  # (W, H)

    def test_rgba_image(self):
        # RGBA image of shape (4, H, W)
        img = np.random.randint(0, 256, (4, 120, 80), dtype=np.uint8)
        result = self.viz.image(img)
        
        pil_img = self._decode_image_payload(result)
        self.assertEqual(pil_img.mode, "RGBA")
        self.assertEqual(pil_img.size, (80, 120))  # (W, H)

    def test_size1_dimension_collapse_gray(self):
        # Crash case: 3D array of shape (1, 1, 100) (e.g. single pixel line)
        img = np.random.randint(0, 256, (1, 1, 100), dtype=np.uint8)
        result = self.viz.image(img)
        
        pil_img = self._decode_image_payload(result)
        self.assertEqual(pil_img.mode, "L")
        self.assertEqual(pil_img.size, (100, 1))  # (W, H)

    def test_invalid_dimensions(self):
        # 1D array should raise ValueError
        img_1d = np.arange(100, dtype=np.uint8)
        with self.assertRaises(ValueError):
            self.viz.image(img_1d)

        # 4D array should raise ValueError
        img_4d = np.zeros((1, 3, 50, 50), dtype=np.uint8)
        with self.assertRaises(ValueError):
            self.viz.image(img_4d)

    def test_invalid_channels(self):
        # 2 channels is unsupported
        img_2ch = np.zeros((2, 50, 50), dtype=np.uint8)
        with self.assertRaises(ValueError):
            self.viz.image(img_2ch)

        # 5 channels is unsupported
        img_5ch = np.zeros((5, 50, 50), dtype=np.uint8)
        with self.assertRaises(ValueError):
            self.viz.image(img_5ch)

    def test_floating_point_scaling(self):
        # Float in [0.0, 1.0] should be scaled to [0, 255]
        img_float_01 = np.array([[0.0, 0.5], [1.0, 0.25]], dtype=np.float32)
        result = self.viz.image(img_float_01)
        
        pil_img = self._decode_image_payload(result)
        self.assertEqual(pil_img.mode, "L")
        # Check actual values (rounded to nearest uint8)
        arr = np.array(pil_img)
        np.testing.assert_array_equal(arr, [[0, 127], [255, 63]])

        # Float with max > 1.0 should NOT be scaled, just converted to uint8
        img_float_large = np.array([[0.0, 128.0], [255.0, 10.0]], dtype=np.float32)
        result_large = self.viz.image(img_float_large)
        pil_img_large = self._decode_image_payload(result_large)
        arr_large = np.array(pil_img_large)
        np.testing.assert_array_equal(arr_large, [[0, 128], [255, 10]])


if __name__ == "__main__":
    unittest.main()
