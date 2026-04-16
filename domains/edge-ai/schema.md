# Edge AI Domain Schema

Read this before digesting or writing any pages in the edge-ai domain.

## Preferred page types
- `entity` — chips, boards, NPUs, vendors
- `concept` — NNAPI delegates, quantization, runtimes, operators
- `source-summary` — digest of a specific source
- `comparison` — head-to-head benchmarks
- `research-report` — synthesized findings
- `deep-research-report` — multi-source investigation

## Link conventions
- Link boards to their chips: [[VOXL 2]] → [[Qualcomm QRB5165]]
- Link models to their runtime backends: [[YOLOv8n]] → [[TFLite Delegate]]
- Link benchmarks to hardware and model pages

## Required fields for benchmark pages
- hardware (board + chip)
- model (name, precision, input shape)
- runtime (TFLite / ONNX / TensorRT / RKNN / SNPE)
- quantization (INT8 / FP16 / FP32)
- latency (ms per inference, batch=1)
- power (mW, if measured)
- accuracy (mAP or top-1, if available)

## Confidence guidance for this domain
- Vendor datasheets with measurements: base 0.80
- Third-party benchmarks with methodology: base 0.78
- Blog posts without methodology: base 0.55
- Forum claims or anecdotes: base 0.40
