import { app } from "../../scripts/app.js";

function getUniqueNodeId(prompt) {
    let id = 10000;
    while (prompt[id.toString()]) {
        id++;
    }
    return id.toString();
}

app.registerExtension({
    name: "Shima.MacroExpander",
    async setup() {
        const origGraphToPrompt = app.graphToPrompt;
        app.graphToPrompt = async function () {
            // Let ComfyUI do the initial serialization of the canvas
            let p;
            try {
                p = await origGraphToPrompt.apply(this, arguments);
            } catch (e) {
                // If it fails (e.g., disconnected nodes), pass the error up
                throw e;
            }

            if (!p || !p.output) return p;
            const prompt = p.output;
            console.log("[Shima.Macro] RAW PRE-EXPANSION PROMPT:", JSON.parse(JSON.stringify(prompt)));

            // Find all Shima.PanelSampler instances in the serialized prompt
            const panelNodes = [];
            for (const [id, node] of Object.entries(prompt)) {
                if (node.class_type === "Shima.PanelSampler") {
                    panelNodes.push({ id, node });
                }
            }

            for (const panel of panelNodes) {
                const panelId = panel.id;
                const panelData = panel.node;

                // 1. Generate new IDs for the 3 injected backend nodes
                const deBNDL_Id = getUniqueNodeId(prompt);
                // Pre-claim it so we don't collide on the next one
                prompt[deBNDL_Id] = { "class_type": "Dummy" };

                const kSampler_Id = getUniqueNodeId(prompt);
                prompt[kSampler_Id] = { "class_type": "Dummy" };

                const reBNDL_Id = getUniqueNodeId(prompt);
                prompt[reBNDL_Id] = { "class_type": "Dummy" };

                // 2. Extract configuration directly from the node's native inputs (now that they are real widgets)
                const cfg = panelData.inputs || {};

                // 3. Construct Node A: Shima.DeBNDLer (for Model Citizen BNDL)
                // The new DeBNDLer takes a single BNDL input and auto-detects type.
                // We need 3 separate DeBNDLers -- one per BNDL source.
                const deBNDL_MC_Id = deBNDL_Id;
                const deBNDL_LM_Id = getUniqueNodeId(prompt);
                prompt[deBNDL_LM_Id] = { "class_type": "Dummy" };
                const deBNDL_MP_Id = getUniqueNodeId(prompt);
                prompt[deBNDL_MP_Id] = { "class_type": "Dummy" };

                // DeBNDLer for ModelCitizen: outputs Model(0), Clip(1), VAE(2)
                const deBNDL_MC = {
                    class_type: "Shima.DeBNDLer",
                    inputs: {
                        bndl: panelData.inputs["modelcitizen.bndl"] || panelData.inputs["modelcitizen_bndl"] || panelData.inputs["modelcitizen"],
                        bndl_type: "Model Citizen",
                        allow_external_linking: false,
                    }
                };
                prompt[deBNDL_MC_Id] = deBNDL_MC;

                // DeBNDLer for MasterPrompt: outputs Positive(3), Negative(4)
                const deBNDL_MP = {
                    class_type: "Shima.DeBNDLer",
                    inputs: {
                        bndl: panelData.inputs["masterprompt.bndl"] || panelData.inputs["masterprompt_bndl"] || panelData.inputs["masterprompt"],
                        bndl_type: "Master Prompt",
                        allow_external_linking: false,
                    }
                };
                prompt[deBNDL_MP_Id] = deBNDL_MP;

                // DeBNDLer for LatentMaker: outputs Latent(5)
                const deBNDL_LM = {
                    class_type: "Shima.DeBNDLer",
                    inputs: {
                        bndl: panelData.inputs["latentmaker.bndl"] || panelData.inputs["latentmaker_bndl"] || panelData.inputs["latentmaker"],
                        bndl_type: "Latent Maker",
                        allow_external_linking: false,
                    }
                };
                prompt[deBNDL_LM_Id] = deBNDL_LM;

                // 4. Construct Node B: Shima.Sampler (The monolithic backend handler)
                // It takes its inputs FROM the outputs of ShimaDeBNDLer AND its internal widgets
                // New output indices based on BNDL_REGISTRY order:
                // ModelCitizen DeBNDLer: 0=Model, 1=Clip, 2=VAE
                // MasterPrompt DeBNDLer: 3=Positive, 4=Negative
                // LatentMaker DeBNDLer:  5=Latent
                const samplerInputs = {
                    model: [deBNDL_MC_Id, 0],       // Model from ModelCitizen DeBNDLer
                    positive: [deBNDL_MP_Id, 3],    // Positive from MasterPrompt DeBNDLer
                    negative: [deBNDL_MP_Id, 4],    // Negative from MasterPrompt DeBNDLer
                    latent_image: [deBNDL_LM_Id, 5], // Latent from LatentMaker DeBNDLer
                    vae: [deBNDL_MC_Id, 2],         // VAE from ModelCitizen DeBNDLer
                };

                // Forward the shima_commonparams wire if it exists
                if (cfg["shima.commonparams"]) {
                    samplerInputs["shima.commonparams"] = cfg["shima.commonparams"];
                }

                // Forward ALL native widget variables straight to Shima.Sampler
                const standardKeys = [
                    "s33d", "randomize", "steps", "cfg", "sampler_name", "scheduler",
                    "denoise", "add_noise", "start_at_step", "end_at_step", "return_with_leftover_noise",
                    "preview_method", "vae_decode", "upscale_enabled", "upscale_method",
                    "upscale_factor", "upscale_denoise", "upscale_steps", "use_commonparams",
                    "allow_external_linking"
                ];

                for (const key of standardKeys) {
                    if (cfg[key] !== undefined) samplerInputs[key] = cfg[key];
                }

                const shimaSampler = {
                    class_type: "Shima.Sampler",
                    inputs: samplerInputs
                };
                prompt[kSampler_Id] = shimaSampler;

                // 5. Construct Node C: Shima.ReBNDLer (builds a shimasampler BNDL)
                const reBNDL = {
                    class_type: "Shima.ReBNDLer",
                    inputs: {
                        bndl_type: "Shima Sampler",
                        allow_external_linking: false,
                        image: [kSampler_Id, 1],      // IMAGE from Shima.Sampler
                        latent: [kSampler_Id, 0],     // LATENT from Shima.Sampler
                        s33d_used: [kSampler_Id, 2],  // s33d from Shima.Sampler
                    }
                };
                prompt[reBNDL_Id] = reBNDL;

                // 6. Reroute outbound connections.
                // Panel Outputs:         0 = Image (IMAGE), 1 = Latent (LATENT), 2 = shimasampler.bndl (BNDL)
                // Shima.Sampler Outputs: 0 = LATENT,         1 = IMAGE,           2 = s33d (INT)
                // ReBNDLer Output:       0 = BNDL

                for (const targetId of Object.keys(prompt)) {
                    if (targetId === panelId) continue;
                    const targetNode = prompt[targetId];
                    if (!targetNode || !targetNode.inputs) continue;

                    for (const [inputKey, linkData] of Object.entries(targetNode.inputs)) {
                        if (Array.isArray(linkData) && linkData[0] === panelId) {
                            const outputIndex = linkData[1];
                            if (outputIndex === 0) {
                                // Panel output 0 (Image) -> Shima.Sampler output 1 (IMAGE)
                                targetNode.inputs[inputKey] = [kSampler_Id, 1];
                            } else if (outputIndex === 1) {
                                // Panel output 1 (Latent) -> Shima.Sampler output 0 (LATENT)
                                targetNode.inputs[inputKey] = [kSampler_Id, 0];
                            } else if (outputIndex === 2) {
                                // Panel output 2 (shimasampler.bndl) -> ReBNDLer output 0 (BNDL)
                                targetNode.inputs[inputKey] = [reBNDL_Id, 0];
                            }
                        }
                    }
                }

                // 7. Erase the Panel from existence! 
                // The python backend will never know it existed.
                delete prompt[panelId];
            }

            console.log("[Shima.Macro] Intercepted execution payload, expanded Panel Samplers.");
            console.log("[Shima.Macro] FINAL POST-EXPANSION PROMPT:", JSON.parse(JSON.stringify(prompt)));
            p.output = prompt;
            return p;
        };
    }
});
