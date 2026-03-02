import { app } from "../../scripts/app.js";

/**
 * Noodman Sticker - Frontend Renderer
 * Handles grid-based sprite slicing for the Shima mascot.
 */
app.registerExtension({
    name: "Shima.Noodman",
    async nodeCreated(node) {
        if (node.comfyClass === "Shima.NoodmanSticker") {

            // 1. Helper: Convert coordinate (A1, B5) to Col/Row
            function parseCoordinate(coord) {
                if (!coord || coord.length < 2) return { col: 0, row: 0 };
                const letter = coord.charAt(0).toUpperCase();
                const number = parseInt(coord.slice(1)) - 1;

                // A=0, B=1, ... J=9
                const col = letter.charCodeAt(0) - 65;
                const row = Math.max(0, number);
                return { col, row };
            }

            // 2. Logic: Handle Execution State (Reaction)
            node.onExecute = function () {
                const animWidget = this.widgets.find(w => w.name === "animation");
                if (animWidget && animWidget.value !== "Custom") {
                    // Temporarily switch to "Thinking" during execution
                    const oldVal = animWidget.value;
                    animWidget.value = "Think";
                    this.setDirtyCanvas(true, true);

                    // Revert after a short delay or when execution finish is detected
                    setTimeout(() => {
                        if (animWidget.value === "Think") {
                            animWidget.value = oldVal;
                            this.setDirtyCanvas(true, true);
                        }
                    }, 2000);
                }
            };

            // 3. Override: Draw Background (The slice math)
            const originalDrawBackground = node.onDrawBackground;
            node.onDrawBackground = function (ctx) {
                // Determine the image to draw
                const img = this.imgs?.[0] || this._stickerImage;
                if (!img || !img.width || !img.height) return;

                const columns = this.widgets.find(w => w.name === "columns")?.value || 10;
                const rows = this.widgets.find(w => w.name === "rows")?.value || 10;
                const animation = this.widgets.find(w => w.name === "animation")?.value;
                const coordStr = this.widgets.find(w => w.name === "coordinate")?.value || "A1";
                const frameIndexWidget = this.widgets.find(w => w.name === "frame_index");

                let frameIndex = frameIndexWidget ? frameIndexWidget.value : 0;

                // Automatic Idle Playback (Simple tick)
                if (animation === "Idle") {
                    // Use global time for smooth loop across multiple nodes
                    const speed = 0.005;
                    const total = columns * rows;
                    frameIndex = Math.floor((Date.now() * speed) % total);
                }

                let col = 0;
                let row = 0;

                if (animation === "Custom") {
                    const parsed = parseCoordinate(coordStr);
                    col = parsed.col;
                    row = parsed.row;
                } else {
                    // Sequence indexing: frame_index -> grid coords
                    col = frameIndex % columns;
                    row = Math.floor(frameIndex / columns);
                }

                // Slice Math
                const sw = img.width / columns;
                const sh = img.height / rows;
                const sx = col * sw;
                const sy = row * sh;

                ctx.save();
                const dw = this.size[0];
                const dh = this.size[1];

                // Draw sliced portion
                ctx.drawImage(img, sx, sy, sw, sh, 0, 0, dw, dh);
                ctx.restore();

                // If animating, keep redrawing
                if (animation !== "Custom") {
                    this.setDirtyCanvas(true, true);
                }
            };
        }
    }
});
