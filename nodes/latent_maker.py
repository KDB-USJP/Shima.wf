"""
Shima.LatentMaker - Unified seed, latent dimensions, and upscaling node

Combines the functionality of:
- Seed generator (uses ComfyUI's built-in control_after_generate)
- EmptyLatentImage (with aspect ratio presets)
- Latent upscaling options
- Model-type awareness (SD1.5/SDXL/SD3/Flux)

All inputs are connectable for maximum flexibility.
"""

import torch
import random
from .system_utils import ShimaSecurity, BUFFER_STABLE, EXECUTE_PLANK, INDEX_SHIFT


class ShimaLatentMaker:
    """
    Create empty latents with integrated seed control and dimension presets.
    
    Supports multiple model types with appropriate latent channel counts:
    - SD 1.5 / SDXL: 4-channel latents
    - SD3 / Flux: 16-channel latents
    """
    
    # Aspect ratio presets with common resolutions
    ASPECT_RATIOS = {
        "1:1 Square": (1, 1),
        "4:3 Standard": (4, 3),
        "3:4 Portrait": (3, 4),
        "16:9 Widescreen": (16, 9),
        "9:16 Vertical": (9, 16),
        "21:9 Ultrawide": (21, 9),
        "3:2 Photo": (3, 2),
        "2:3 Portrait Photo": (2, 3),
        "Custom": (0, 0),  # Use width/height inputs
    }
    
    # Base resolutions per model type
    MODEL_BASES = {
        "sd1.5": {"base": 512, "channels": 4},
        "sd2.x": {"base": 768, "channels": 4},
        "sdxl": {"base": 1024, "channels": 4},
        "sd3": {"base": 1024, "channels": 16},
        "flux": {"base": 1024, "channels": 16},
    }
    
    # Map user-facing model names to their latent format key
    MODEL_TYPE_MAP = {
        "sd1.5": "sd1.5", "sd2.x": "sd2.x",
        "sdxl": "sdxl", "pony": "sdxl", "illustrious": "sdxl",
        "sd3": "sd3", "hidream": "sd3",
        "flux": "flux", "chroma": "flux", "lumina2": "flux",
        "z-image-base": "flux", "z-image-turbo": "flux",
        "auraflow": "sdxl", "hunyuan": "sdxl",
    }
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # Seed control
                "s33d": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "s33d_mode": (["fixed", "increment", "decrement", "randomize"], {"default": "fixed", "tooltip": "Control seed behavior (applied to base seed)"}),
                
                # Model type (affects latent channels)
                "model_type": (["sdxl", "sd1.5", "sd2.x", "sd3", "flux", "pony", "illustrious",
                                "auraflow", "hunyuan", "lumina2", "chroma", "hidream",
                                "z-image-base", "z-image-turbo"], {
                    "default": "sdxl",
                    "tooltip": "Select Model Type — determines latent channels and base resolution"
                }),
                
                # Aspect Ratio / Dimensions
                "aspect_ratio": (list(cls.ASPECT_RATIOS.keys()), {"default": "4:3 Standard"}),
                "orientation": (["landscape", "portrait", "auto"], {"default": "landscape"}),
                
                "width": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 8, "tooltip": "Manual width (used if Aspect Ratio is Custom)"}),
                "height": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 8, "tooltip": "Manual height (used if Aspect Ratio is Custom)"}),
                
                "scale": ("FLOAT", {"default": 1.0, "min": 0.1, "max": 4.0, "step": 0.05, "tooltip": "Upscale factor applied to dimensions"}),

                # Batch size
                "batch_size": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 64,
                    "tooltip": "Number of latents to generate in batch"
                }),
            },
            "optional": {
                # Shima Integration (Input)
                "shima.commonparams": ("DICT", {
                    "forceInput": True,
                    "tooltip": "Configuration bundle from Shima.Commons (overrides seed/dimensions if enabled)"
                }),

                # Shima Integration (Widgets)
                "use_commonparams": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "If True, use settings from Shima.Commons bundle (Seed, Width, Height)"
                }),
                "allow_external_linking": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "If ON, this node broadcasts/receives OUTSIDE the Island (ignores group regex)"
                }),
                "show_used_values": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Show actual values being used (debug)"
                }),
            }
        }
    
    RETURN_TYPES = ("LATENT", "INT", "INT", "INT", "BNDL")
    RETURN_NAMES = ("latent", "s33d", "width", "height", "latentmaker.bndl")
    OUTPUT_TOOLTIPS = (
        "Empty latent image at calculated dimensions",
        "The seed used.",
        "The width used.",
        "The height used.",
        "The bundled dictionary containing the latent."
    )
    
    FUNCTION = "generate"
    CATEGORY = "Shima/Latent"
    
    DESCRIPTION = "Create empty latents with integrated seed control, aspect ratio presets, and model-type awareness."

    def generate(
        self,
        s33d: int,
        s33d_mode: str,
        model_type: str,
        aspect_ratio: str,
        orientation: str,
        width: int,
        height: int,
        scale: float,
        batch_size: int,
        use_commonparams: bool = False,
        **kwargs,
    ):
        # INTEGRITY CHECK: Silent Buffer Validation
        prompt = kwargs.get("prompt")
        state = BUFFER_STABLE
        if prompt:
            state, _ = ShimaSecurity.verify_workflow(prompt)
            if state in [EXECUTE_PLANK, INDEX_SHIFT]:
                # Standardized camouflaged log
                print(f"[Shima] Workflow integrity check complete.")
        
        # Handle dot notation input
        shima_commonparams = kwargs.get("shima.commonparams", None)
        
        # 1. Determine Base Seed
        # Priority: Bundle (if enabled) > Direct Input/Widget
        # Note: If s33d is wired, it comes in as 's33d' arg. 
        # If 'use_commonparams' is True, we OVERRIDE it with bundle.
        # Use commonparams switch responsibly!
        
        current_seed = s33d
        
        if use_commonparams and shima_commonparams:
            bundle_seed = shima_commonparams.get("seed")
            # Only override if bundle has a valid seed
            if bundle_seed is not None:
                current_seed = bundle_seed
                # When using bundle seed, we must ignore local randomization
                # effectively treating it as 'fixed' relative to the bundle
                s33d_mode = "fixed"
        
        # 2. Apply Mode (Fixed, Increment, Decrement, Randomize)
        # Note: 'fixed' means use current_seed as is.
        # 'increment/decrement' implies offset from input.
        # 'randomize' ignores input.
        
        final_s33d = current_seed
        
        if s33d_mode == "increment":
            final_s33d = (current_seed + 1) % 0xffffffffffffffff
        elif s33d_mode == "decrement":
            final_s33d = (current_seed - 1) % 0xffffffffffffffff
        elif s33d_mode == "randomize":
            final_s33d = random.randint(0, 0xffffffffffffffff)
        
        # 3. Determine Dimensions
        
        # Check Bundle settings first (if enabled)
        bundle_model_type = None
        bundle_orientation = None
        
        if use_commonparams and shima_commonparams:
            bundle_model_type = shima_commonparams.get("model_type_raw", shima_commonparams.get("model_type"))
            bundle_orientation = shima_commonparams.get("orientation")  
            
        # Determine effective model type
        # Bundle overrides local if present
        effective_model_type = bundle_model_type if bundle_model_type else model_type
        
        # Get model config basics using effective model type
        # Use lowercase for safety as Commons standardizes to lowercase
        # Resolve user-facing model type to latent format key
        mt_raw = effective_model_type.lower() if effective_model_type else "sdxl"
        mt = self.MODEL_TYPE_MAP.get(mt_raw, "sdxl")
            
        model_config = self.MODEL_BASES[mt]
        base_size = model_config["base"]
        channels = model_config["channels"]
        
        final_width = None
        final_height = None
        
        # Check Bundle dimensions logic
        if use_commonparams and shima_commonparams:
            b_width = shima_commonparams.get("width")
            b_height = shima_commonparams.get("height")
            if b_width and b_height:
                final_width = int(b_width)
                final_height = int(b_height)
        
        # If not set by bundle, use Node Settings
        if final_width is None:
            if aspect_ratio == "Custom":
                # Use manual width/height inputs
                final_width = width
                final_height = height
            else:
                # Calculate from aspect ratio
                ratio_w, ratio_h = self.ASPECT_RATIOS[aspect_ratio]
                
                # Determine effective orientation
                # Bundle overrides local if present
                effective_orientation = bundle_orientation if (bundle_orientation and bundle_orientation != "auto") else orientation
                
                # Apply orientation
                if effective_orientation == "portrait" and ratio_w > ratio_h:
                    ratio_w, ratio_h = ratio_h, ratio_w
                elif effective_orientation == "landscape" and ratio_h > ratio_w:
                    ratio_w, ratio_h = ratio_h, ratio_w
                # "auto" keeps the preset as-is
                
                # Calculate dimensions that fit within base_size
                if ratio_w >= ratio_h:
                    final_width = base_size
                    final_height = int(base_size * ratio_h / ratio_w)
                else:
                    final_height = base_size
                    final_width = int(base_size * ratio_w / ratio_h)
        
        
        # Apply scale
        final_width = int(final_width * scale)
        final_height = int(final_height * scale)
        
        # Ensure dimensions are divisible by 8 (required for latent space)
        final_width = (final_width // 8) * 8
        final_height = (final_height // 8) * 8
        
        # Clamp to reasonable bounds
        final_width = max(64, min(8192, final_width))
        final_height = max(64, min(8192, final_height))
        
        # Create empty latent
        # Latent dimensions are image dimensions / 8
        latent_width = final_width // 8
        latent_height = final_height // 8
        
        # Create the latent tensor with appropriate channels
        latent = torch.zeros([batch_size, channels, latent_height, latent_width])
        
        # Formatting used values for UI display
        source = "CommonParams" if (use_commonparams and shima_commonparams) else "Widget"
        used_values_text = [
            f"Source: {source}",
            f"Seed: {final_s33d}",
            f"Size: {final_width}x{final_height}",
            f"Model: {mt_raw.upper()}"
        ]

        # Construct Internal BNDL
        latentmaker_bndl = {
            "bndl_type": "latentmaker",
            "latent": {"samples": latent}
        }

        return {
            "ui": {
                "used_values": used_values_text,  # List of strings for frontend
            },
            "result": ({"samples": latent}, final_s33d, final_width, final_height, latentmaker_bndl)
        }


class ShimaPanelLatentMaker(ShimaLatentMaker):
    """
    Panelized variant of ShimaLatentMaker.
    Frontend Javascript hides all native widgets and renders a sleek PCB chassis + double-click HTML modal.
    """
    CATEGORY = "Shima/Panels"
    RETURN_TYPES = ("LATENT", "BNDL")
    RETURN_NAMES = ("latent", "latentmaker.bndl")

    def generate(self, *args, **kwargs):
        res = super().generate(*args, **kwargs)
        orig_tuple = res["result"]
        # original returns (latent, s33d, width, height, latentmaker.bndl)
        res["result"] = (orig_tuple[0], orig_tuple[4])
        return res

# Node registration
NODE_CLASS_MAPPINGS = {
    "Shima.LatentMaker": ShimaLatentMaker,
    "Shima.PanelLatentMaker": ShimaPanelLatentMaker,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Shima.LatentMaker": "Shima Latent Maker",
    "Shima.PanelLatentMaker": "Shima Panel Latent Maker",
}
