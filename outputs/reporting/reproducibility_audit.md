# R4 reproducibility evidence

- unit: **PASS** - focused stress/reporting tests, including rate / 4 * exposure
- integration: **PASS** - R4 stress runner plus formal reporting runner completed
- artifact_consistency: **PASS** - R1-R4 metadata, mapping, model spec, registry, and artifact hashes validated
- r4_manifest_backed_delivery_chain: **PASS** - Manifest-hash-verified Fed downloads -> validated R2 panel/model refit -> R4 paths -> T1-T5/PDF
- end_to_end: **NOT_RUN** - The complete raw FFIEC -> R1 -> R2 -> R3 -> R4 repair chain was not rerun in this invocation; upstream R1-R3 were hash-validated inputs
