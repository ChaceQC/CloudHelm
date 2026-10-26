import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { SteeringWheel } from "@phosphor-icons/react";
import { copyFileSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const icons = join(root, "src-tauri", "icons");
const scratch = mkdtempSync(join(tmpdir(), "cloudhelm-workspace-icons-"));
mkdirSync(icons, { recursive: true });
mkdirSync(join(root, "public"), { recursive: true });
// Rasterize the standard Phosphor library mark; no custom vector drawing.
const svg = renderToStaticMarkup(createElement(SteeringWheel, {
  size: 1024, weight: "bold", color: "#0648ff",
}));
const source = join(icons, "source.svg");
writeFileSync(source, svg + "\n", "utf8");
execFileSync(process.execPath, [
  join(root, "node_modules", "@tauri-apps", "cli", "tauri.js"),
  "icon", source, "--output", scratch,
], { cwd: root, stdio: "pipe" });
copyFileSync(join(scratch, "icon.ico"), join(icons, "icon.ico"));
copyFileSync(join(scratch, "128x128.png"), join(icons, "icon.png"));
copyFileSync(join(icons, "icon.png"), join(root, "public", "icon.png"));
console.log("Prepared Windows icon and browser favicon from the Phosphor library.");
