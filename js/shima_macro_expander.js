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

                // 3. Construct Node A: Shima.PanelDeBNDLer
                // It needs the two incoming BNDL connections that were wired into the Panel
                const deBNDL = {
                    class_type: "Shima.PanelDeBNDLer",
                    inputs: {
                        "modelcitizen.bndl": panelData.inputs["modelcitizen.bndl"] || panelData.inputs["modelcitizen_bndl"] || panelData.inputs["modelcitizen"],
                        "latentmaker.bndl": panelData.inputs["latentmaker.bndl"] || panelData.inputs["latentmaker_bndl"] || panelData.inputs["latentmaker"],
                        "masterprompt.bndl": panelData.inputs["masterprompt.bndl"] || panelData.inputs["masterprompt_bndl"] || panelData.inputs["masterprompt"]
                    }
                };
                prompt[deBNDL_Id] = deBNDL;

                // 4. Construct Node B: Shima.Sampler (The monolithic backend handler)
                // It takes its inputs FROM the outputs of ShimaDeBNDLer AND its internal widgets
                const samplerInputs = {
                    model: [deBNDL_Id, 2],       // 2 is MODEL
                    positive: [deBNDL_Id, 5],    // 5 is POSITIVE
                    negative: [deBNDL_Id, 6],    // 6 is NEGATIVE
                    latent_image: [deBNDL_Id, 7], // 7 is LATENT
                    vae: [deBNDL_Id, 4],         // 4 is VAE (Needed for decode)
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

                // 5. Construct Node C: Shima.PanelReBNDLer
                // Repacks the newly sampled latent, passing along the un-touched BNDLs
                const reBNDL = {
                    class_type: "Shima.PanelReBNDLer",
                    inputs: {
                        sampled_latent: [kSampler_Id, 0], // 0 is LATENT from Shima.Sampler
                        modelcitizen_passthrough: [deBNDL_Id, 0], // Output 0 is the untouched modelcitizen BNDL
                        masterprompt_passthrough: [deBNDL_Id, 1], // Output 1 is the untouched masterprompt BNDL
                        s33d_used: [kSampler_Id, 2], // 2 is s33d from Shima.Sampler
                        image: [kSampler_Id, 1] // 1 is IMAGE from Shima.Sampler
                    }
                };
                prompt[reBNDL_Id] = reBNDL;

                // 6. Reroute outbound connections.
                // Any node in the graph that was wired to the ShimaPanelSampler needs to be re-pointed to ShimaReBNDLer.
                // Panel Outputs: 0 = shimasampler.bndl, 1 = Image, 2 = Latent.
                // ReBNDLer Outputs: 0 = shimasampler.bndl, 1 = Image, 2 = Latent. (They match perfectly)

                for (const targetId of Object.keys(prompt)) {
                    if (targetId === panelId) continue; // skip the panel itself
                    const targetNode = prompt[targetId];
                    if (!targetNode || !targetNode.inputs) continue;

                    for (const [inputKey, linkData] of Object.entries(targetNode.inputs)) {
                        // linkData is usually an array [node_id, output_index]
                        if (Array.isArray(linkData) && linkData[0] === panelId) {
                            const outputIndex = linkData[1];
                            targetNode.inputs[inputKey] = [reBNDL_Id, outputIndex];
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
