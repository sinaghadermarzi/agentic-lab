# The simplified series

A shorter, plainer twin of every numbered chapter. Same micro-world (Larkspur Outfitters), same
`shoplab` package, same chapter numbers and titles, about a quarter of the words (roughly 17k
against 68k across the 21 chapters) and fewer cells per notebook.

## Who it is for

- Readers who want the shape of the whole course in a day before doing the full chapters.
- Readers who find the full chapters' prose dense; each simplified notebook states what it will
  do as a short bullet list and then does exactly that.
- Workshops and reading groups that need a 60 to 90 minute version of a chapter.

## What is different

| | Full chapters (repo root) | Simplified series (this folder) |
|---|---|---|
| Prose | Long-form, with callouts, recap table, three exercises | Short, one idea per section, no exercises |
| Config cell | The frozen cell from `docs/CONVENTIONS.md` | A plain cell that finds the repo root from either directory and loads the same `.env` |
| Phoenix | Every chapter has the optional Phoenix cell | Only chapters 03 and 20 mention Phoenix |
| Validation | `scripts/validate_notebooks.py` enforces the skeleton and sentinel drift | Not validated: these are reading copies, not the contract |
| Build-then-import | The chapter is where the `shoplab` code is first written | Imports `shoplab`; shows the key pieces but does not rebuild every one |

Everything else is shared: `.env`, the disk cache, the data in `data/`, the extras table in the
main README (the same chapters need the same `pip install -e ".[...]"` extras and ch18 still needs
the `agentic-lab-crewai` kernel).

## Running them

Open JupyterLab from the repo root as usual and navigate into this folder. Each config cell walks
up one directory to find `pyproject.toml` and `.env`, so the notebooks work from here without
copying anything.

## Keeping them in sync

The simplified series is maintained by hand. When a full chapter changes in substance (a new
tool, a renamed function, a different gold ticket), update the twin in the same pull request so
the two never teach different things. The full chapter is authoritative whenever they disagree.
