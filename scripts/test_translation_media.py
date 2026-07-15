import unittest

from translation_media import image_key, merge_images, missing_source_images


class TranslationMediaTests(unittest.TestCase):
    def test_merge_images_keeps_caption_and_adds_missing_source_media(self) -> None:
        existing = [{"url": "https://assets.example/cover.jpg?width=1280", "caption": "封面"}]
        source = [
            "https://assets.example/cover.jpg?width=640",
            "https://assets.example/chart.jpg",
        ]

        self.assertEqual(merge_images(existing, source), [
            {"url": "https://assets.example/cover.jpg?width=1280", "caption": "封面"},
            {"url": "https://assets.example/chart.jpg", "caption": ""},
        ])

    def test_missing_source_images_ignores_transformed_duplicates(self) -> None:
        translation = [{"url": "https://assets.example/cover.jpg?width=1280"}]
        source = [
            "https://assets.example/cover.jpg?width=640",
            "https://assets.example/chart.jpg",
        ]

        self.assertEqual(missing_source_images(translation, source), ["https://assets.example/chart.jpg"])
        self.assertEqual(image_key(source[0]), image_key(translation[0]))


if __name__ == "__main__":
    unittest.main()
