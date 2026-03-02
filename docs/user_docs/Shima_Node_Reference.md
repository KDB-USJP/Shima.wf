# Shima Nodes Reference

A concise guide to the available Shima Custom Nodes for ComfyUI.

## 🧠 Core Controllers

### **Shima.Commons**
The workflow "brain" that broadcasts global settings (Seed, Dimensions, Project Name) to all downstream Shima nodes via Use Everywhere. Use this to control your entire workflow from one place.

### **Shima.LatentMaker**
Generates empty latent images with built-in aspect ratio presets and model-aware sizing (SDXL, SD1.5, etc.). Includes internal seed control and upscaling options.

### Global Integration Toggles
Most nodes now include standardized integration toggles in the **Optional** inputs (positioned at the absolute bottom for predictable layout):

- **`use_commonparams`** (Boolean): 
  - If **True**, the node pulls settings (Seed, Project, Dimensions) from the `shima.commonparams` bundle.
  - If **False**, it uses the node's local widgets.
  - *Note:* In `LatentMaker`, this allows overriding the manually set dimensions.

- **`allow_external_linking`** (Boolean):
  - If **True**, the node broadcasts/receives specific "Use Everywhere" signals that ignore the standard group regex (allowing cross-island communication).
  - Useful for connecting a main controller to a submodule in a different group.

### **Shima.SeedController**
A dedicated node for complex seed manipulation, capable of broadcasting seeds or outputting them for manual connection. Supports fixed, increment, decrement, and randomized modes.

---

## 🎨 Conditioning & Prompting

### **Shima.MasterPrompt**
A unified prompting node supporting multiple model types (SDXL, SD1.5, Flux) with dynamic text inputs and CLIP weight controls. Automatically adjusts its UI based on the selected model checks.

---

## 🔬 Sampling & Generation

### **Shima.Sampler**
A powerful, model-aware wrapper around standard KSampling. Adapts allowed samplers/schedulers based on the model type (e.g., hiding incompatible samplers for Flux) and supports Use Everywhere integration.

---

## 🖼️ Images & Previews

### **Shima.Preview**
A robust image previewer that allows saving the current frame to disk or opening it in an external editor.

### **Shima.CarouselPreview**
An interactive previewer for batch generations. Displays a film-strip style carousel to easily navigate and select images from a large batch.

### **Shima.Sticker**
Adds a watermark or logo overlay to your images. Supports transparency and positioning control.

### **Shima.NSFWChecker**
A hybrid safety filter that scores images for NSFW content. Features a "Smart Cap" to allow swimwear (PG-13) while blocking explicit content, with options to blur or black out detected images.

---

## 💾 Saving & Files

### **Shima.FileSaver**
Saves images to disk with flexible naming patterns. Can automatically pull project names and timestamps from Shima Commons.

### **Shima.MultiSaver**
Designed for complex workflows, this node saves multiple image types (Original, Depth, Lineart, etc.) in one go. It handles batching and folder organization automatically.

### **Shima.FileNamer**
A utility to generate advanced filename strings based on date, time, project name, or custom patterns. Useful for piping into standard ComfyUI savers.

---

## 🛠️ Utilities & Debugging

### **Shima.Inspector** (New!)
A universal debug node with 10 wildcard inputs. Displays a real-time, scrolling table of input values and types (including Tensor shapes) while passing the data through unchanged.

### **Shima.BatchImageProcessor** (New!)
A directory iterator for mass processing. Loads images sequentially from a folder (and subfolders) with internal auto-incrementing logic. Includes safety checks to prevent overwriting source files and outputs relative paths for maintaining folder structure.

### **Shima.SeedLogger** (New!)
A minimalist visual history tool. Tracks and displays a scrolling list of used seeds in your session; click any seed to copy it to your clipboard.

### **Shima.RichDisplay**
Renders HTML or Markdown content bundles passed from other Shima nodes. Useful for viewing logs or complex data structures in a formatted way.

---

## 🧱 Primitives & Converters

### **Shima.Int / Float / String / Boolean**
Wrappers for standard primitive values. These allow for easier labeling and broadcasting of constants within your workflow.

### **Shima.ToInt / ToFloat / ToString**
Simple utility nodes to convert data types between standard formats (e.g., converting a Number to a String for filenames).
