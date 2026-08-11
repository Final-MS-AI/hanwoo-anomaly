# Model feedback loop

The feedback loop deliberately separates user reports from model training.

1. A signed-in user pauses the inference result video and submits an error type.
2. `POST /feedback` stores the timestamp, optional Track ID, corrected label,
   inference summary, and an evidence frame when the original upload is available.
3. An operator reviews pending rows on the VM.
4. Only approved rows are exported to JSONL for labeling and retraining.
5. A candidate model must pass the existing crowded-cattle and negative-sample
   evaluations before its weights replace the production model.

Apply the database migration once:

```bash
psql "$DATABASE_URL" -f ../db/migrations/20260811_create_model_feedback.sql
```

Review and export on the backend VM:

```bash
python feedback_admin.py list
python feedback_admin.py review FEEDBACK_UUID approved --note "verified"
python feedback_admin.py export --output feedback_exports/approved_feedback.jsonl
```

Never train directly from `pending` feedback. The exported JSONL is a manifest for
the labeling/retraining pipeline; it is not automatically trusted as ground truth.
