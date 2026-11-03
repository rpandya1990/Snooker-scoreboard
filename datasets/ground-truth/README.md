# Snooker ball ground truth

Human-reviewed ball annotations from the table camera, one folder per local session date:

```text
datasets/ground-truth/
  classes.txt                 red yellow green brown blue pink black white (class ids 0–7)
  YYYY-MM-DD/
    images/<session>-<segment>-<n>.jpg    1280×720 frame from the session recording
    labels/<same>.txt                     YOLO: "class centre-x centre-y width height", normalised 0–1
    manifest.jsonl                        provenance per frame (session, video segment, offset, view quality)
    README.md                             counts for that date
```

Each ball on the cloth has one tight box around the ball (not its shadow); balls in pockets or off the table are not labelled. Labels were pre-drawn by the companion (YOLO ball detector plus colour rules), then corrected in Label Studio and checked for impossible tables (more than 15 reds, two of a colour, two cue balls).

Produced by `training/import_review.py`, which also builds the training split. Frames show the playing area and people at the table.
