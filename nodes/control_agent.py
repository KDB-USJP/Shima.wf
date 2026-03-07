import torch
import torch.nn.functional as F
import comfy.utils
from nodes import MAX_RESOLUTION

class ShimaControlAgent:
    """
    Shima ControlNet Agent
    Auto-resizes the input image to match the latent dimensions provided by CommonParams.
    Outputs a packed `shima.controlbus` instruction bundle for the MasterPrompt.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "control_type": (["canny", "depth", "pose", "lineart", "scribble", "color", "custom"], {"default": "canny"}),
                "strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.05}),
                "fit_method": (["crop to fit", "pad to fit", "stretch"], {"default": "crop to fit"}),
            },
            "optional": {
                "shima.commonparams": ("DICT", {"forceInput": True, "tooltip": "Provides the target latent resolution for auto-sizing."}),
                "modelcitizen": ("BNDL", {"forceInput": True, "tooltip": "Fallback bundle to parse commonparams if direct commonparams are unavailable."}),
                "shima.controlbus": ("LIST", {"forceInput": True, "tooltip": "Daisy-chain previous ControlAgents here."}),
            }
        }

    RETURN_TYPES = ("LIST", "IMAGE")
    RETURN_NAMES = ("shima.controlbus", "processed_image")
    FUNCTION = "apply_control"
    CATEGORY = "Shima/ControlNet"

    def apply_control(self, image, control_type, strength, fit_method, **kwargs):
        # 1. Resolve Target Dimensions
        target_w, target_h = 1024, 1024 # Safest fallback
        
        # Look for explicit commonparams first
        common_params = kwargs.get("shima.commonparams", {})
        
        if not common_params:
             mc_bndl = kwargs.get("modelcitizen", {})
             if mc_bndl and mc_bndl.get("bndl_type") == "modelcitizen":
                 common_params = mc_bndl.get("shima.commonparams", {})
        
        if common_params:
            target_w = common_params.get("width", target_w)
            target_h = common_params.get("height", target_h)
            
        print(f"[ShimaControlAgent] Target Latent Resolution resolved to: {target_w}x{target_h}")

        # 2. Extract dimensions from the BCHW image tensor (ComfyUI uses BHWC by default)
        # ComfyUI image format is [Batch, Height, Width, Channels]
        img_h, img_w = image.shape[1], image.shape[2]
        
        processed_image = image
        
        # 3. Handle Auto-Resizing if the dimensions don't match
        if img_w != target_w or img_h != target_h:
            # We must convert to BCHW for PyTorch interpolate
            # Permute: [B, H, W, C] -> [B, C, H, W]
            tensor_bchw = image.permute(0, 3, 1, 2)
            
            if fit_method == "stretch":
                tensor_bchw = F.interpolate(tensor_bchw, size=(target_h, target_w), mode="bilinear", align_corners=False)
            
            elif fit_method == "crop to fit":
                # Determine aspect ratios
                target_ar = target_w / target_h
                img_ar = img_w / img_h
                
                if img_ar > target_ar:
                    # Image is wider than target. Crop width.
                    new_w = int(img_h * target_ar)
                    offset = (img_w - new_w) // 2
                    tensor_bchw = tensor_bchw[:, :, :, offset:offset+new_w]
                else:
                    # Image is taller than target. Crop height.
                    new_h = int(img_w / target_ar)
                    offset = (img_h - new_h) // 2
                    tensor_bchw = tensor_bchw[:, :, offset:offset+new_h, :]
                    
                # Resize cropped square to target
                tensor_bchw = F.interpolate(tensor_bchw, size=(target_h, target_w), mode="bilinear", align_corners=False)
                
            elif fit_method == "pad to fit":
                target_ar = target_w / target_h
                img_ar = img_w / img_h
                
                if img_ar > target_ar:
                    # Image is wider. Pad top/bottom.
                    new_h = int(img_w / target_ar)
                    pad_total = new_h - img_h
                    pad_top = pad_total // 2
                    pad_bottom = pad_total - pad_top
                    tensor_bchw = F.pad(tensor_bchw, (0, 0, pad_top, pad_bottom), mode="constant", value=0)
                else:
                    # Image is taller. Pad left/right.
                    new_w = int(img_h * target_ar)
                    pad_total = new_w - img_w
                    pad_left = pad_total // 2
                    pad_right = pad_total - pad_left
                    tensor_bchw = F.pad(tensor_bchw, (pad_left, pad_right, 0, 0), mode="constant", value=0)
                    
                # Downsize/Upsize the padded image to the exact target size
                tensor_bchw = F.interpolate(tensor_bchw, size=(target_h, target_w), mode="bilinear", align_corners=False)

            # Convert back to BHWC
            processed_image = tensor_bchw.permute(0, 2, 3, 1)
            print(f"[ShimaControlAgent] Resized/Cropped image from {img_w}x{img_h} to {target_w}x{target_h} using {fit_method}")

        # 4. Create the Instruction Dict
        instruction = {
            "control_type": control_type.lower(),
            "strength": strength,
            "image": processed_image,
        }
        
        # 5. Append to the Daisy-Chain Bus
        bus = kwargs.get("shima.controlbus", [])
        
        # Copy the list to prevent mutating earlier steps
        new_bus = list(bus)
        new_bus.append(instruction)

        return (new_bus, processed_image)

class ShimaPanelControlAgent(ShimaControlAgent):
    """
    Panelized variant of ShimaControlAgent.
    Frontend Javascript hides all native widgets and renders a sleek PCB chassis + double-click HTML modal.
    """
    CATEGORY = "Shima/Panels"

NODE_CLASS_MAPPINGS = {
    "Shima.ControlAgent": ShimaControlAgent,
    "Shima.PanelControlAgent": ShimaPanelControlAgent,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Shima.ControlAgent": "Shima ControlNet Agent",
    "Shima.PanelControlAgent": "Shima Panel Control Agent",
}
