/**
 * Shima DeBNDLer / ReBNDLer Frontend
 *
 * Slot visibility approach:
 *   LiteGraph has no native slot.hidden. We physically rebuild the
 *   output/input arrays when bndl_type changes. Full definitions are
 *   captured at first load.
 *
 *   CRITICAL: The Python backend always defines ALL outputs/inputs.
 *   Frontend rebuilds change local slot indices but the backend expects
 *   the original "full" indices. A prompt interceptor (graphToPrompt hook)
 *   remaps compact frontend indices back to full backend indices before
 *   the prompt hits the validator.
 */

import { app } from "../../scripts/app.js";
import { addShimaToolbar } from "./shima_topbar.js";

// Mirror of BNDL_REGISTRY from utilities.py
const BNDL_REGISTRY = {
    "Model Citizen": ["model", "clip", "vae"],
    "Master Prompt": ["pos", "neg"],
    "Latent Maker": ["latent"],
    "Shima Sampler": ["image", "latent", "s33d_used"],
};

const ALL_FIELD_KEYS = new Set(Object.values(BNDL_REGISTRY).flat());
const WIDGET_ONLY = new Set(["bndl_type", "allow_external_linking"]);

function getActiveInputKeys(typeLabel) {
    return new Set(BNDL_REGISTRY[typeLabel] || []);
}

function hideWidget(w) {
    w.type = "hidden";
    w.hidden = true;
    w.computeSize = () => [0, -4];
    if (w.element) w.element.style.display = "none";
    w.onDraw = () => { };
}

function findSyncedReBNDLers(debndlerNode) {
    const results = [];
    if (!debndlerNode.outputs) return results;
    const syncSlot = debndlerNode.outputs.find(o => o.name === "sync");
    if (!syncSlot || !syncSlot.links) return results;
    for (const linkId of syncSlot.links) {
        const link = app.graph.links[linkId];
        if (!link) continue;
        const targetNode = app.graph.getNodeById(link.target_id);
        if (targetNode && targetNode.comfyClass === "Shima.ReBNDLer") {
            results.push(targetNode);
        }
    }
    return results;
}

/**
 * Build the mapping from compact (frontend) index -> full (backend) index
 * for a given BNDL type on the DeBNDLer.
 */
function buildOutputIndexMap(selectedType, fullOutputs) {
    // Determine which full indices are active
    const activeFullIndices = [];
    let idx = 0;
    for (const [label, fields] of Object.entries(BNDL_REGISTRY)) {
        for (const _field of fields) {
            if (label === selectedType) activeFullIndices.push(idx);
            idx++;
        }
    }
    // Sync is always the last slot in fullOutputs
    activeFullIndices.push(fullOutputs.length - 1);

    // Map: compact index -> full index
    const map = {};
    for (let compact = 0; compact < activeFullIndices.length; compact++) {
        map[compact] = activeFullIndices[compact];
    }
    return map;
}

/**
 * Build the mapping from compact (frontend) index -> full (backend) index
 * for a given BNDL type on the ReBNDLer.
 */
function buildInputIndexMap(selectedType, fullInputs) {
    const activeKeys = getActiveInputKeys(selectedType);
    const activeFullIndices = [];
    for (let i = 0; i < fullInputs.length; i++) {
        const def = fullInputs[i];
        if (WIDGET_ONLY.has(def.name)) continue;
        const isRegistryField = ALL_FIELD_KEYS.has(def.name);
        if (!isRegistryField || activeKeys.has(def.name)) {
            activeFullIndices.push(i);
        }
    }
    const map = {};
    for (let compact = 0; compact < activeFullIndices.length; compact++) {
        map[compact] = activeFullIndices[compact];
    }
    return map;
}

// Store per-node index maps for the prompt interceptor
// Key: node ID, Value: { outputs: {compact -> full}, inputs: {compact -> full} }
const NODE_INDEX_MAPS = {};

app.registerExtension({
    name: "Shima.BNDLer",

    // ---- Prompt Interceptor: remap compact indices to full backend indices ----
    async setup() {
        const origGraphToPrompt = app.graphToPrompt;
        app.graphToPrompt = async function (...args) {
            const p = await origGraphToPrompt.apply(this, args);
            const prompt = p.output;

            // Scan all nodes in the prompt for links that reference DeBNDLer outputs or ReBNDLer inputs
            for (const nodeId of Object.keys(prompt)) {
                const nodeData = prompt[nodeId];
                if (!nodeData || !nodeData.inputs) continue;

                for (const [inputKey, linkData] of Object.entries(nodeData.inputs)) {
                    if (!Array.isArray(linkData)) continue;

                    const originId = String(linkData[0]);
                    const compactSlot = linkData[1];

                    // Check if the origin node has an output index map (it's a DeBNDLer)
                    const originMap = NODE_INDEX_MAPS[originId];
                    if (originMap && originMap.outputs && originMap.outputs[compactSlot] !== undefined) {
                        linkData[1] = originMap.outputs[compactSlot];
                    }
                }

                // Check if THIS node is a ReBNDLer with an input index map
                const thisMap = NODE_INDEX_MAPS[nodeId];
                if (thisMap && thisMap.inputs) {
                    // Remap input keys... Actually, ComfyUI uses input NAMES not indices
                    // for the prompt inputs dict, so input remapping isn't needed.
                    // The backend resolves inputs by name, not by slot index.
                }
            }

            p.output = prompt;
            return p;
        };
    },

    async nodeCreated(node) {

        // ---- DeBNDLer ----
        if (node.comfyClass === "Shima.DeBNDLer") {
            addShimaToolbar(node, ["external_linking"]);

            function hideWidgets() {
                if (!node.widgets) return;
                for (const w of node.widgets) {
                    if (w.name === "allow_external_linking") hideWidget(w);
                }
            }
            hideWidgets();
            [50, 100, 250, 500, 1000].forEach(ms => setTimeout(hideWidgets, ms));

            let fullOutputs = null;
            const captureFullOutputs = () => {
                if (fullOutputs || !node.outputs || node.outputs.length === 0) return;
                fullOutputs = node.outputs.map(o => ({
                    name: o.name,
                    type: o.type,
                    color_on: o.color_on,
                    color_off: o.color_off,
                }));
            };

            const rebuildOutputs = () => {
                captureFullOutputs();
                if (!fullOutputs) return;

                const typeWidget = node.widgets?.find(w => w.name === "bndl_type");
                const selectedType = typeWidget ? typeWidget.value : "Model Citizen";

                // Build the compact -> full index map
                const indexMap = buildOutputIndexMap(selectedType, fullOutputs);
                NODE_INDEX_MAPS[String(node.id)] = NODE_INDEX_MAPS[String(node.id)] || {};
                NODE_INDEX_MAPS[String(node.id)].outputs = indexMap;

                // Determine active full indices from the map
                const activeFullIndices = new Set(Object.values(indexMap));

                // Disconnect links on outputs we're removing
                for (let i = node.outputs.length - 1; i >= 0; i--) {
                    const out = node.outputs[i];
                    const fullIdx = fullOutputs.findIndex(fo => fo.name === out.name);
                    if (fullIdx >= 0 && !activeFullIndices.has(fullIdx)) {
                        if (out.links) {
                            for (const _linkId of [...out.links]) {
                                node.disconnectOutput(i);
                            }
                        }
                    }
                }

                // Collect surviving links by name
                const survivingLinks = {};
                for (const out of node.outputs) {
                    if (out.links && out.links.length > 0) {
                        survivingLinks[out.name] = [...out.links];
                    }
                }

                // Rebuild with only active slots
                node.outputs = [];
                for (let i = 0; i < fullOutputs.length; i++) {
                    if (activeFullIndices.has(i)) {
                        const def = fullOutputs[i];
                        node.outputs.push({
                            name: def.name,
                            type: def.type,
                            links: survivingLinks[def.name] || null,
                            color_on: def.color_on,
                            color_off: def.color_off,
                        });
                    }
                }

                // Patch link objects with new compact indices
                for (let newIdx = 0; newIdx < node.outputs.length; newIdx++) {
                    const out = node.outputs[newIdx];
                    if (out.links) {
                        for (const linkId of out.links) {
                            const link = app.graph.links[linkId];
                            if (link) link.origin_slot = newIdx;
                        }
                    }
                }

                node.setSize(node.computeSize());
                node.setDirtyCanvas(true, true);
            };

            const typeWidget = node.widgets?.find(w => w.name === "bndl_type");
            if (typeWidget) {
                const origCallback = typeWidget.callback;
                typeWidget.callback = function (value) {
                    if (origCallback) origCallback.call(this, value);
                    rebuildOutputs();

                    const syncedNodes = findSyncedReBNDLers(node);
                    for (const rebndler of syncedNodes) {
                        const targetTypeW = rebndler.widgets?.find(w => w.name === "bndl_type");
                        if (targetTypeW && targetTypeW.value !== value) {
                            targetTypeW.value = value;
                            if (targetTypeW.callback) targetTypeW.callback(value);
                        }
                    }
                };
            }

            setTimeout(rebuildOutputs, 100);
            setTimeout(rebuildOutputs, 500);

            const origOnConnChange = node.onConnectionsChange;
            node.onConnectionsChange = function (...args) {
                if (origOnConnChange) origOnConnChange.apply(this, args);
                node.setDirtyCanvas(true, true);
            };
        }

        // ---- ReBNDLer ----
        if (node.comfyClass === "Shima.ReBNDLer") {
            addShimaToolbar(node, ["external_linking"]);

            function hideWidgets() {
                if (!node.widgets) return;
                for (const w of node.widgets) {
                    if (w.name === "allow_external_linking") hideWidget(w);
                    if (w.name === "s33d_used") hideWidget(w);
                }
            }
            hideWidgets();
            [50, 100, 250, 500, 1000].forEach(ms => setTimeout(hideWidgets, ms));

            let fullInputs = null;
            const captureFullInputs = () => {
                if (fullInputs || !node.inputs || node.inputs.length === 0) return;
                fullInputs = node.inputs.map(inp => ({
                    name: inp.name,
                    type: inp.type,
                    color_on: inp.color_on,
                    color_off: inp.color_off,
                }));
            };

            const rebuildInputs = () => {
                captureFullInputs();
                if (!fullInputs) return;

                const typeWidget = node.widgets?.find(w => w.name === "bndl_type");
                if (!typeWidget) return;

                const activeKeys = getActiveInputKeys(typeWidget.value);

                // Disconnect links on inputs we're removing
                for (let i = node.inputs.length - 1; i >= 0; i--) {
                    const inp = node.inputs[i];
                    if (WIDGET_ONLY.has(inp.name)) continue;
                    const isRegistryField = ALL_FIELD_KEYS.has(inp.name);
                    if (isRegistryField && !activeKeys.has(inp.name)) {
                        if (inp.link != null) node.disconnectInput(i);
                    }
                }

                // Collect surviving links by name
                const survivingLinks = {};
                for (const inp of node.inputs) {
                    if (inp.link != null) survivingLinks[inp.name] = inp.link;
                }

                // Rebuild with only active slots
                node.inputs = [];
                for (const def of fullInputs) {
                    if (WIDGET_ONLY.has(def.name)) continue;
                    const isRegistryField = ALL_FIELD_KEYS.has(def.name);
                    if (!isRegistryField || activeKeys.has(def.name)) {
                        node.inputs.push({
                            name: def.name,
                            type: def.type,
                            link: survivingLinks[def.name] ?? null,
                            color_on: def.color_on,
                            color_off: def.color_off,
                        });
                    }
                }

                // Patch link objects with new compact indices
                for (let newIdx = 0; newIdx < node.inputs.length; newIdx++) {
                    const inp = node.inputs[newIdx];
                    if (inp.link != null) {
                        const link = app.graph.links[inp.link];
                        if (link) link.target_slot = newIdx;
                    }
                }

                node.setSize(node.computeSize());
                node.setDirtyCanvas(true, true);
            };

            const typeWidget = node.widgets?.find(w => w.name === "bndl_type");
            if (typeWidget) {
                const origCallback = typeWidget.callback;
                typeWidget.callback = function (value) {
                    if (origCallback) origCallback.call(this, value);
                    rebuildInputs();
                };
            }

            setTimeout(rebuildInputs, 100);
            setTimeout(rebuildInputs, 500);

            const origOnConnChange = node.onConnectionsChange;
            node.onConnectionsChange = function (slotType, slotIndex, isConnected, linkInfo) {
                if (origOnConnChange) origOnConnChange.apply(this, arguments);
                if (slotType === LiteGraph.INPUT && node.inputs[slotIndex]?.name === "sync") {
                    if (isConnected && linkInfo) {
                        const sourceNode = app.graph.getNodeById(linkInfo.origin_id);
                        if (sourceNode && sourceNode.comfyClass === "Shima.DeBNDLer") {
                            const srcTypeWidget = sourceNode.widgets?.find(w => w.name === "bndl_type");
                            if (srcTypeWidget && typeWidget) {
                                typeWidget.value = srcTypeWidget.value;
                                if (typeWidget.callback) typeWidget.callback(typeWidget.value);
                            }
                        }
                    }
                }
            };
        }
    }
});
