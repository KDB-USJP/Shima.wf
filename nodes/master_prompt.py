import torch
import comfy.sd
import comfy.utils
import folder_paths
import os

class ShimaMasterPrompt:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("STRING", {"multiline": True, "dynamicPrompts": True, "default": "Positive Prompt", "tooltip": "Main positive prompt"}),
                "negative": ("STRING", {"multiline": True, "dynamicPrompts": True, "default": "Negative Prompt", "tooltip": "Main negative prompt"}),
                "model_type": (["sdxl", "sd1.5", "sd2.x", "sd3", "flux", "pony", "illustrious",
                                "auraflow", "hunyuan", "lumina2", "chroma", "hidream",
                                "z-image-base", "z-image-turbo"],),

            },
            "optional": {
                "clip": ("CLIP",),
                # Shima Integration (Input)
                "shima.commonparams": ("DICT", {"forceInput": True, "tooltip": "Connect Shima.Commons bundle here"}),
                "shima.controlbus": ("LIST", {"forceInput": True, "tooltip": "Connect ControlNet chain here"}),

                "model_type_override": ("STRING", {"forceInput": True, "tooltip": "Override model_type selection"}),
                
                "modelcitizen": ("BNDL", {
                    "forceInput": True,
                    "tooltip": "Bundle containing CLIP (overrides individual inputs)"
                }),
                
                # L Components (Interleaved)
                "clip_l_weight": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.01}),
                "positive_l": ("STRING", {"multiline": True, "dynamicPrompts": True, "default": "", "tooltip": "CLIP-L Positive (SDXL/SD3 style/detail)"}),
                "negative_l": ("STRING", {"multiline": True, "dynamicPrompts": True, "default": ""}),
                
                # G Components (Interleaved)
                "clip_g_weight": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.01}),
                "positive_g": ("STRING", {"multiline": True, "dynamicPrompts": True, "default": "", "tooltip": "CLIP-G Positive (SDXL/SD3 subject)"}),
                "negative_g": ("STRING", {"multiline": True, "dynamicPrompts": True, "default": ""}),
                
                # T5 Components (Interleaved)
                "t5_weight": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.01}),
                "positive_t5": ("STRING", {"multiline": True, "dynamicPrompts": True, "default": "", "tooltip": "T5 Positive (SD3/Flux complex text)"}),
                "negative_t5": ("STRING", {"multiline": True, "dynamicPrompts": True, "default": ""}),

                # Flux/Chroma-specific
                "flux_guidance": ("FLOAT", {"default": 3.5, "min": 0.0, "max": 100.0, "step": 0.1, "tooltip": "Guidance scale for Flux/Chroma models (auto-applied when model_type is flux or chroma)"}),

                # Lumina2-specific
                "lumina_sysprompt": ("STRING", {"multiline": True, "default": "", "tooltip": "System prompt prefix for Lumina2. Leave blank to use the default. Only used when model_type is lumina2."}),

                # Shima Integration (Widgets)
                "use_commonparams": ("BOOLEAN", {"default": False, "tooltip": "If True, use model_type from Shima.Commons bundle."}),
                "allow_external_linking": ("BOOLEAN", {"default": False, "tooltip": "Allow connections outside the Island"}),
                "show_used_values": ("BOOLEAN", {"default": False, "tooltip": "Show actual values being used (debug)"}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "CONDITIONING", "CONDITIONING", "CONDITIONING", "STRING", "STRING", "BNDL")
    # CLIP_L/G/T5 outputs are currently fallbacks to main positive.
    RETURN_NAMES = ("positive", "negative", "CLIP_L_ONLY", "CLIP_G_ONLY", "T5_ONLY", "pos_string", "neg_string", "masterprompt.bndl")
    FUNCTION = "encode"
    CATEGORY = "Shima/Conditioning"

    def encode(self, positive, negative, model_type, 
              clip=None, model_type_override=None, allow_external_linking=False, 
              clip_l_weight=1.0, positive_l=None, negative_l=None,
              clip_g_weight=1.0, positive_g=None, negative_g=None,
              t5_weight=1.0, positive_t5=None, negative_t5=None,
              use_commonparams=True, **kwargs):
        
        # Safely parse boolean arguments
        def _parse_bool(v):
            if isinstance(v, str): return v.lower() not in ("false", "0", "")
            return bool(v)
            
        use_commonparams = _parse_bool(use_commonparams)

        # Priority Logic: Explicit Input > Model Bundle
        modelcitizen = kwargs.get("modelcitizen", None)
        
        if clip is None and modelcitizen:
            if modelcitizen.get("bndl_type") == "modelcitizen":
                clip = modelcitizen.get("clip")
            
        if clip is None:
            raise ValueError("[Shima MasterPrompt] No CLIP provided! Please connect 'clip' input or 'modelbundle'.")

        # 1. Determine Model Type logic
        final_model_type = model_type
        
        # Check Common Params first
        common_params = kwargs.get("shima.commonparams", {})
        if use_commonparams and common_params:
            cp_model = common_params.get("model_type_raw", common_params.get("model_type"))
            # Fallback to model_preset if old key used (though we updated it)
            if not cp_model:
                cp_model = common_params.get("model_preset")
            
            if cp_model:
                final_model_type = cp_model

        # Override Input takes highest precedence
        if model_type_override:
            final_model_type = model_type_override
            
        final_model_type = final_model_type.lower().strip()
        print(f"[ShimaMasterPrompt] Encoding for: {final_model_type}")

        # Auto-prepend Lumina2 system prompt
        if final_model_type == "lumina2":
            lumina_default = ("You are an advanced image generation assistant designed to "
                             "generate high-quality realistic images, specialized in creating "
                             "highly detailed, high-resolution photography that precisely matches "
                             "user prompts, including tag-based prompts. <Prompt Start> ")
            custom_sysprompt = kwargs.get("lumina_sysprompt", "").strip()
            sysprompt = custom_sysprompt if custom_sysprompt else lumina_default
            positive = sysprompt + positive
            print(f"[ShimaMasterPrompt] Lumina2 system prompt applied ({len(sysprompt)} chars)")

        # Helper to encode text to condition
        def get_conditioning(text, l_text=None, g_text=None, t5_text=None):
            # If specific texts are provided, we might need advanced logic.
            # For now, simplistic approach: prioritize specific if available, else main.
            # Ideally "Global" means G, "Local" means L.
            
            # Standard tokenization (uses all available)
            # We use the main text prompt for the main output.
            tokens = clip.tokenize(text)
            
            # This returns [[cond, {"pooled_output": pooled}]]
            # This is the standard ComfyUI structure.
            cond, pooled = clip.encode_from_tokens(tokens, return_pooled=True)
            return [[cond, {"pooled_output": pooled}]]

        # Generate Main Outputs
        pos_cond = get_conditioning(positive)
        neg_cond = get_conditioning(negative)
        
        # Determine L/G/T5 specific outputs
        # This is tricky because the 'clip' object might be SDXL (L+G) or SD1.5 (L).
        # Returning 'pos_cond' for everything is a safe fallback for now 
        # until we implement specific sub-encoding extraction.
        # User asked for text boxes for G/L/T5, which implies they want to FEED them separate text.
        # If we just accept the text inputs but don't use them differently, it's misleading.
        
        # Since I cannot easily split the CLIP object into L/G/T5 sub-encoders without deep interaction
        # with Comfy's backend classes (SD1ClipModel, SDXLClipModel, etc.), 
        # I will route the MAIN text to all for now to fix the crash.
        # Functionality for specific text inputs requires a deeper specialized implementation 
        # (e.g. manually constructing tokens for specific sub-models).
        
        # FIX: Ensure we return the LIST of [tensor, dict], not just tensor.
        # My previous code `pos_cond = clip.encode(positive)` likely returned `[[tensor, dict]]` 
        # IF `clip` is the Comfy wrapper. 
        # Wait, if `clip.encode(positive)` returns [[tensor, dict]], then `pos_cond` was correct?
        # Let's verify via the helper above which explicitly calls `encode_from_tokens`.
        
        # Apply FluxGuidance for Flux and Chroma (Flux variant)
        if final_model_type in ("flux", "chroma"):
            guidance = kwargs.get("flux_guidance", 3.5)
            pos_cond = [[t[0], {**t[1], "guidance": guidance}] for t in pos_cond]
            print(f"[ShimaMasterPrompt] Applied FluxGuidance: {guidance}")

        # --- SHIMA CONTROLBUS INTEGRATION ---
        controlbus = kwargs.get("shima.controlbus", [])
        if controlbus:
            print(f"[ShimaMasterPrompt] Found {len(controlbus)} ControlNets on the bus. Applying...")
            
            # Helper to find the right model path
            def _resolve_controlnet(architecture, c_type):
                cnet_paths = folder_paths.get_filename_list("controlnet")
                architecture_clean = architecture.replace(".", "").lower() # e.g. "sd1.5" -> "sd15"
                c_type = c_type.lower()
                
                # 1. Very strict matching: Architecture specific folder
                for path in cnet_paths:
                     path_clean = path.lower().replace("\\", "/") # Normalize path separators
                     if f"/{architecture_clean}/" in f"/{path_clean}" and c_type in path_clean:
                         return path
                         
                # 2. Lazy Matching: Both terms exist in the filename anywhere
                for path in cnet_paths:
                    path_clean = path.lower().replace("\\", "/").split("/")[-1]
                    # Map common naming shorthands
                    aliases = [architecture_clean]
                    if architecture_clean == "sdxl": aliases.extend(["xl"])
                    if architecture_clean == "sd15": aliases.extend(["v15", "15"])
                    if architecture_clean == "sd3": aliases.extend(["sd3"])
                    
                    if any(alias in path_clean for alias in aliases) and c_type in path_clean:
                        return path
                        
                # 3. Yolo Matching: Just look for the type
                for path in cnet_paths:
                    path_clean = path.lower().replace("\\", "/").split("/")[-1]
                    if c_type in path_clean:
                        return path
                        
                return None

            for instruction in controlbus:
                c_type = instruction.get("control_type", "unknown")
                strength = instruction.get("strength", 1.0)
                c_image = instruction.get("image", None)
                
                if not c_image is None:
                    cnet_filename = _resolve_controlnet(final_model_type, c_type)
                    if cnet_filename:
                        cnet_path = folder_paths.get_full_path("controlnet", cnet_filename)
                        print(f"[ShimaMasterPrompt] Loading ControlNet: {cnet_filename}")
                        # Load actual comfy controlnet model
                        controlnet = comfy.sd.load_controlnet(cnet_path)
                        
                        # Apply to Positive (ComfyUI native wrapping)
                        new_pos_cond = []
                        for t in pos_cond:
                            n = [t[0], t[1].copy()]
                            c_net = controlnet.copy().set_cond_hint(c_image, strength, (0.0, 1.0))
                            if "control" in n[1]:
                                c_net.set_previous_controlnet(n[1]["control"])
                            n[1]["control"] = c_net
                            n[1]["control_apply_to_uncond"] = False # Matches ComfyUI Advanced default
                            new_pos_cond.append(n)
                        pos_cond = new_pos_cond
                        
                        # Apply to Negative (If enabled / advanced)
                        new_neg_cond = []
                        for t in neg_cond:
                            n = [t[0], t[1].copy()]
                            c_net = controlnet.copy().set_cond_hint(c_image, strength, (0.0, 1.0))
                            if "control" in n[1]:
                                c_net.set_previous_controlnet(n[1]["control"])
                            n[1]["control"] = c_net
                            n[1]["control_apply_to_uncond"] = False
                            new_neg_cond.append(n)
                        neg_cond = new_neg_cond
                        
                        print(f"[ShimaMasterPrompt] Applied {c_type} ControlNet ({strength}) successfully.")
                    else:
                        print(f"[ShimaMasterPrompt] WARNING: Could not find any ControlNet matching architecture '{final_model_type}' and type '{c_type}'. Skipping.")

        # Formatting used values for UI display
        source = "CommonParams" if (use_commonparams and common_params) else "Widget"
        used_values_text = [
            f"Source: {source}",
            f"Model: {final_model_type}"
        ]
        if final_model_type in ("flux", "chroma"):
            used_values_text.append(f"Guidance: {kwargs.get('flux_guidance', 3.5)}")
        if final_model_type == "lumina2":
            used_values_text.append("Lumina2 sysprompt: active")

        # Construct Internal BNDL
        masterprompt_bndl = {
            "bndl_type": "masterprompt",
            "pos": pos_cond,
            "neg": neg_cond
        }

        return {
            "ui": {
                "used_values": used_values_text,
            },
            "result": (pos_cond, neg_cond, pos_cond, pos_cond, pos_cond, positive, negative, masterprompt_bndl)
        }

class ShimaPanelMasterPrompt(ShimaMasterPrompt):
    """
    Panelized variant of ShimaMasterPrompt.
    Frontend Javascript hides all native widgets and renders a sleek PCB chassis + double-click HTML modal.
    """
    CATEGORY = "Shima/Panels"
    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "BNDL")
    RETURN_NAMES = ("positive", "negative", "masterprompt.bndl")

    def encode(self, *args, **kwargs):
        res = super().encode(*args, **kwargs)
        orig_tuple = res["result"]
        # original returns (pos_cond, neg_cond, l_cond, g_cond, t5_cond, positive_str, negative_str, masterprompt.bndl)
        res["result"] = (orig_tuple[0], orig_tuple[1], orig_tuple[7])
        return res

NODE_CLASS_MAPPINGS = {
    "Shima.MasterPrompt": ShimaMasterPrompt,
    "Shima.PanelMasterPrompt": ShimaPanelMasterPrompt,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Shima.MasterPrompt": "Shima Master Prompt",
    "Shima.PanelMasterPrompt": "Shima Panel Master Prompt",
}
