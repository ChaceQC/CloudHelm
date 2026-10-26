import { copyFileSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { execFileSync, spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

if (process.platform !== "win32") throw new Error("Build this Windows example on Windows.");
const root = dirname(dirname(fileURLToPath(import.meta.url)));
const args = process.argv.slice(2);
const result = spawnSync(process.execPath, [
  join(root, "node_modules", "@tauri-apps", "cli", "tauri.js"),
  "build", "--no-bundle", ...args,
], { cwd: root, stdio: "inherit" });
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);

const metadata = JSON.parse(execFileSync("cargo", ["metadata", "--no-deps", "--format-version", "1"], {
  cwd: join(root, "src-tauri"), encoding: "utf8",
}));
const profile = args.includes("--debug") ? "debug" : "release";
const output = join(metadata.target_directory, profile);
const build = join(output, "build");
// The Windows GNU WebView2 binding dynamically loads this official loader.
const bindings = readdirSync(build).filter((name) => name.startsWith("webview2-com-sys-"));
const loaders = bindings.map((name) => join(build, name, "out", "x64", "WebView2Loader.dll"));
const outputLoader = join(output, "WebView2Loader.dll");
const loader = existsSync(outputLoader) ? outputLoader : loaders.find(existsSync);
if (!loader) throw new Error("WebView2Loader.dll was not found in this build.");
if (loader !== outputLoader) copyFileSync(loader, outputLoader);
const delivery = join(root, "output", "windows");
mkdirSync(delivery, { recursive: true });
copyFileSync(join(output, "cloudhelm-desktop-journal.exe"), join(delivery, "cloudhelm-desktop-journal.exe"));
copyFileSync(outputLoader, join(delivery, "WebView2Loader.dll"));
console.log("Windows app and WebView2Loader.dll are ready in " + delivery);
