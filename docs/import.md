# Importing a family's history

`sprout import family.json` creates a family and fills it from a JSON file. Use it once, when a
family already has records somewhere else. PDF paths are relative to the JSON file and must stay
inside its folder. Keep this file private: it holds your children's names and birthdays.

```json
{
  "family": {"name": "The Example Family", "owners": ["parent1@example.com"], "members": ["parent2@example.com"]},
  "children": [
    {
      "key": "sam",
      "name": "Sam",
      "born": "2019-05-01",
      "trace_name": "SAM",
      "current_level": "Adding single digits",
      "next_steps": "Two-digit addition without carrying",
      "log": [
        {"day": "2026-01-10", "kind": "sheet", "title": "Math drill", "file": "sam/math.pdf", "detail": "seed 42"},
        {"day": "2026-01-12", "kind": "project", "title": "Wooden puzzle", "detail": "cut on the CNC"}
      ]
    }
  ],
  "ideas": [
    {"title": "Bird feeder", "machine": "cnc", "child": "sam", "status": "idea", "detail": "..."}
  ]
}
```

`kind` is one of sheet, project, note, feedback. `machine` is cnc, laser, print or other.
`status` is idea, planned, built or dropped. Owners are added as owners right away (the first one)
or invited; members are invited and join when they first sign in with Google.
