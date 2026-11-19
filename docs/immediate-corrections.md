# Confirmed corrections / 确认纠正

A confirmed correction is persisted in `corrections.json` outside adapter directories before the training worker starts. It remains authoritative when training is pending, cancelled, failed, or the service restarts. Adapter training is a later optimization, not the commit boundary. Superseded rows remain audit history, not active facts.

Named questions about a corrected subject (and supported explicit self questions) use current stored facts before the model/training gate. This prevents old chat snippets, document retrieval and stale adapter weights from overriding a confirmed correction. Other known facts on the same subject are retained. While a worker runs, unrelated model-generation requests retain the existing wait behavior. This is not a general model-free conversational engine: ambiguous pronouns, unsupported paraphrases and creative tasks are not promised equivalent recall.

Corrections are overlaid onto expert facts; stale on-disk fact banks are not reused, and adapters whose saved facts predate the correction are not used for generation. A missing adapter directory does not erase the confirmed correction. The existing adapter-directory replacement implementation is otherwise unchanged; this change does not claim atomic recovery of every unrelated fact after a failed registration.

A correction from another chat cites that chat, not the original fact's chat. Original sources remain separately available for audit. The memory editor records an editor-origin correction, not whatever chat happens to be open. A source chat must actually contain the correction's supplied source text.

A replaced value is not automatically historical truth. The default event is an error correction. An explicit source that says “previously A, now B” (or its supported Chinese equivalent) is recorded as a state change; otherwise historical questions explain that the old record was corrected, not established as a past fact. This narrow rule is not a general temporal knowledge model and does not infer real-world effective dates.

## Regression

`python -m unittest tests.test_correction_store tests.test_correction_immediate`

Runs without model weights or training. Covers pre-training answers, failed worker startup, reopening and a new Python process, Chinese/English facts, stale bank rejection, separate-chat provenance, editor provenance, correction chains, unrelated facts and history semantics. Existing migration, extraction, document and recall tests also run in the correction CI. Full learned-model quality still needs the existing model-equipped E2E suite; deterministic fixtures do not establish LoRA retraining quality.
