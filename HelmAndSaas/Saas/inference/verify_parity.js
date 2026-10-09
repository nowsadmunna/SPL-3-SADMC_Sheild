import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { runRaw } from "./onnxModel.js";
import { ANOMALY_CLASSES } from "./classes.js";
import { fixedNormalise } from "./fixedScaler.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ref = JSON.parse(readFileSync(path.join(__dirname, "fixtures", "torch_reference_v3.json"), "utf-8"));
const PROB_TOLERANCE = 1e-4;
const NORM_TOLERANCE = 1e-5;
let allPass = true;

// normalise (fixedScaler.js) + ONNX vs torch, per fixture
console.log(`${"idx".padEnd(4)} ${"service".padEnd(10)} ${"torch".padEnd(14)} ${"onnx".padEnd(14)} ${"norm_diff".padEnd(11)} ${"prob_diff".padEnd(11)} result`);
for (let i = 0; i < ref.fixtures.length; i++) {
  const fx = ref.fixtures[i];
  const input = fixedNormalise(fx.input);
  const normDiff = Math.max(...Array.from(input, (v, j) => Math.abs(v - fx.normalised[j])));
  const { probs } = await runRaw(input);
  let c = 0;
  for (let k = 1; k < probs.length; k++) if (probs[k] > probs[c]) c = k;
  const probDiff = Math.max(...probs.map((p, k) => Math.abs(p - fx.probs[k])));
  const pass = c === fx.pred_class && probDiff < PROB_TOLERANCE && normDiff < NORM_TOLERANCE;
  allPass = allPass && pass;
  console.log(`${String(i).padEnd(4)} ${fx.service.padEnd(10)} ${ANOMALY_CLASSES[fx.pred_class].padEnd(14)} ${ANOMALY_CLASSES[c].padEnd(14)} ${normDiff.toExponential(1).padEnd(11)} ${probDiff.toExponential(1).padEnd(11)} ${pass ? "PASS" : "FAIL"}`);
}
console.log(allPass ? `\nAll checks PASS (norm<${NORM_TOLERANCE}, prob<${PROB_TOLERANCE}).` : "\nParity check FAILED - see FAIL rows above.");
process.exit(allPass ? 0 : 1);
