import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { runRaw } from "./onnxModel.js";
import { ANOMALY_CLASSES } from "./classes.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES_PATH = path.join(__dirname, "fixtures", "torch_reference.json");
const PROB_TOLERANCE = 1e-4;

async function main() {
  const fixtures = JSON.parse(readFileSync(FIXTURES_PATH, "utf-8"));
  let allPass = true;

  console.log(
    `${"idx".padEnd(4)} ${"torch_class".padEnd(14)} ${"onnx_class".padEnd(14)} ${"max_prob_diff".padEnd(15)} result`
  );

  for (let i = 0; i < fixtures.length; i++) {
    const fixture = fixtures[i];
    const { probs } = await runRaw(fixture.input);

    let onnxClass = 0;
    for (let c = 1; c < probs.length; c++) {
      if (probs[c] > probs[onnxClass]) onnxClass = c;
    }

    const maxProbDiff = Math.max(...probs.map((p, c) => Math.abs(p - fixture.probs[c])));
    const classMatch = onnxClass === fixture.pred_class;
    const probsMatch = maxProbDiff < PROB_TOLERANCE;
    const pass = classMatch && probsMatch;
    allPass = allPass && pass;

    console.log(
      `${String(i).padEnd(4)} ${ANOMALY_CLASSES[fixture.pred_class].padEnd(14)} ${ANOMALY_CLASSES[onnxClass].padEnd(14)} ${maxProbDiff.toExponential(2).padEnd(15)} ${pass ? "PASS" : "FAIL"}`
    );
  }

  if (allPass) {
    console.log(`\nAll ${fixtures.length} fixtures PASS (tolerance ${PROB_TOLERANCE}).`);
    process.exit(0);
  } else {
    console.error(`\nParity check FAILED — see FAIL rows above.`);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error("[verify_parity.js] error:", err);
  process.exit(1);
});
