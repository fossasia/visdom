import unittest
from unittest.mock import patch
import visdom


class TestAudioCaption(unittest.TestCase):
    def setUp(self):
        self.viz = visdom.Visdom(send=False, use_incoming_socket=False)

    def _call_audio(self, opts=None):
        sent = {}

        def capture(text, **kwargs):
            sent["html"] = text
            return ""

        with patch("visdom.loadfile", return_value=b"\x00" * 4):
            with patch.object(self.viz, "text", side_effect=capture):
                self.viz.audio(
                    audiofile="sample.wav", opts=opts
                )
        return sent.get("html", "")

    def test_caption_appears_in_html(self):
        html = self._call_audio(opts={"caption": "Dog barking"})
        self.assertIn("Dog barking", html)

    def test_no_caption_leaves_html_unchanged(self):
        html = self._call_audio()
        self.assertNotIn("<p>", html)

    def test_empty_caption_leaves_html_unchanged(self):
        html = self._call_audio(opts={"caption": ""})
        self.assertNotIn("<p>", html)

    def test_caption_is_html_escaped(self):
        html = self._call_audio(opts={"caption": "<script>alert(1)</script>"})
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class TestVideoCaption(unittest.TestCase):
    def setUp(self):
        self.viz = visdom.Visdom(send=False, use_incoming_socket=False)

    def _call_video(self, opts=None):
        sent = {}

        def capture(text, **kwargs):
            sent["html"] = text
            return ""

        with patch("visdom.loadfile", return_value=b"\x00" * 4):
            with patch.object(self.viz, "text", side_effect=capture):
                self.viz.video(
                    videofile="sample.mp4", opts=opts
                )
        return sent.get("html", "")

    def test_caption_appears_in_html(self):
        html = self._call_video(opts={"caption": "Training rollout"})
        self.assertIn("Training rollout", html)

    def test_no_caption_leaves_html_unchanged(self):
        html = self._call_video()
        self.assertNotIn("<p>", html)

    def test_empty_caption_leaves_html_unchanged(self):
        html = self._call_video(opts={"caption": ""})
        self.assertNotIn("<p>", html)

    def test_caption_is_html_escaped(self):
        html = self._call_video(opts={"caption": "<b>bold</b>"})
        self.assertNotIn("<b>", html)
        self.assertIn("&lt;b&gt;", html)


if __name__ == "__main__":
    unittest.main()
