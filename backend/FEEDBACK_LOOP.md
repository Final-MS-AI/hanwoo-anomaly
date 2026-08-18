# Model feedback loop

The feedback loop separates user reports by failure cause and never treats one
unreviewed report as ground truth.

1. A signed-in user pauses the inference result video and submits an error type.
2. `POST /feedback` stores the timestamp, optional Track ID, corrected label,
   inference summary, and an evidence frame when the original upload is available.
3. The report is linked to its original anomaly event and device, then routed to
   anomaly policy, behavior classifier, cow detector, or identity tracking.
4. Every Tuesday the weekly job writes one immutable JSON manifest to Blob.
5. Policy feedback can be consensus-approved only after reports for at least
   three distinct original events. A weekly adjustment is capped at 5%.
6. Classifier feedback remains pending until reviewed. Training starts only when
   the configured minimum approved sample count is reached.
7. A candidate model is promoted only when the evaluator prints JSON containing
   `{"passed": true}` and `FEEDBACK_AUTO_PROMOTE=true`.

Apply the database migration once:

```bash
psql "$DATABASE_URL" -f ../db/migrations/20260811_create_model_feedback.sql
psql "$DATABASE_URL" -f ../db/migrations/20260818_create_feedback_learning_loop.sql
```

Review and export on the backend VM:

```bash
python feedback_admin.py list
python feedback_admin.py review FEEDBACK_UUID approved --note "verified"
python feedback_admin.py export --output feedback_exports/approved_feedback.jsonl
```

Never train directly from `pending` feedback. The exported JSONL is a manifest for
the labeling/retraining pipeline; it is not automatically trusted as ground truth.

Install the Tuesday scheduler:

```bash
sudo cp ../infra/systemd/cowow-feedback-weekly.service /etc/systemd/system/
sudo cp ../infra/systemd/cowow-feedback-weekly.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cowow-feedback-weekly.timer
systemctl list-timers cowow-feedback-weekly.timer
```

The policy runtime must apply the generated override after its default threshold
dictionary is constructed:

```python
from feedback_policy_runtime import apply_policy_overrides

BEHAVIOR_THRESHOLDS = apply_policy_overrides(BEHAVIOR_THRESHOLDS)
```

`FEEDBACK_TRAIN_COMMAND`, `FEEDBACK_EVALUATE_COMMAND`, and
`FEEDBACK_PROMOTE_COMMAND` are command templates. They receive `{manifest}`,
`{batch_id}`, and (for evaluate/promote) `{candidate}`. Leave auto promotion off
until the candidate evaluation command is connected and verified.
