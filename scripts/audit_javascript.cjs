// Parse first-party static JavaScript without executing browser code.
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = path.resolve(__dirname, "..");
const ignored = new Set([".git", ".venv", "node_modules", "staticfiles", "media", "notifications"]);
const report = { checked: [], failures: [], skipped: [] };

function visit(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (ignored.has(entry.name) || entry.isSymbolicLink()) continue;
    const filename = path.join(directory, entry.name);
    const relative = path.relative(root, filename).replaceAll("\\", "/");
    if (entry.isDirectory()) {
      if (/^(static\/(images|build|assets|vendor|vendors)|\.\w+)/.test(relative)) continue;
      visit(filename);
    } else if (entry.name.endsWith(".js") && /(^|\/)static\//.test(relative)) {
      if (entry.name.endsWith(".min.js") || fs.statSync(filename).size > 300000) {
        report.skipped.push({ file: relative, reason: "minified/vendor bundle" });
        continue;
      }
      const source = fs.readFileSync(filename, "utf8");
      if (source.includes("{%")) {
        report.skipped.push({ file: relative, reason: "requires Django template rendering" });
        continue;
      }
      const result = spawnSync(process.execPath, ["--input-type=module", "--check"], {
        input: source, encoding: "utf8", timeout: 10000,
      });
      report.checked.push(relative);
      if (result.status !== 0) report.failures.push({ file: relative, error: result.stderr || String(result.error) });
    }
  }
}

visit(root);
fs.mkdirSync(path.join(root, "tmp"), { recursive: true });
fs.writeFileSync(path.join(root, "tmp", "site-javascript-audit.json"), JSON.stringify(report, null, 2));
console.log(`${report.checked.length} static JavaScript files checked; ${report.failures.length} syntax failures; ${report.skipped.length} bundles/templates excluded.`);
for (const failure of report.failures) console.log(failure.file, failure.error);
process.exitCode = report.failures.length ? 1 : 0;
