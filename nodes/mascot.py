import os
import torch
import numpy as np
from PIL import Image

class ShimaNoodmanSticker:
    """
    Animated Mascot Node for Shima.
    Uses grid-based sprite sheets with seekable frames and named states.
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "animation": (["Idle", "Think", "Success", "Error", "Custom"], {"default": "Idle"}),
                "frame_index": ("INT", {"default": 0, "min": 0, "max": 99, "step": 1}),
                "coordinate": ("STRING", {"default": "A1"}),
                "columns": ("INT", {"default": 10, "min": 1, "max": 64}),
                "rows": ("INT", {"default": 10, "min": 1, "max": 64}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "process"
    CATEGORY = "Shima/Mascot"

    def process(self, image, animation, frame_index, coordinate, columns, rows):
        # This backend node primarily acts as a vessel for the image data.
        # The REAL magic happens in the JS frontend (noodman.js) which handles
        # the grid-slicing and animation playback on the canvas.
        return (image,)

NODE_CLASS_MAPPINGS = {
    "Shima.NoodmanSticker": ShimaNoodmanSticker,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Shima.NoodmanSticker": "Shima Noodman Mascot",
}
