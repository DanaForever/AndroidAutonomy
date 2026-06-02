# Prompt: build an agentic-design slide deck for a GUI-agent framework

Copy the block below into a new session. Fill in the three placeholders at the
top (`FRAMEWORK NAME`, `REPO URL`, `DOCS/BLOG URLS`). Everything else is fixed
guidance that produced the MobileRun deck.

The gold-standard reference already exists. Tell the session to read it first:
- `/home/thivux/code/vinai/GUI_agent/AndroidAutonomy/tasks/agentic_framework/mobilerun/index.html`
- `/home/thivux/code/vinai/GUI_agent/AndroidAutonomy/tasks/agentic_framework/mobilerun/prompts.html`

---

```
# Task: build an agentic-design slide deck for <FRAMEWORK NAME>

## Inputs
- Framework: <FRAMEWORK NAME>
- Repo: <REPO URL>
- Docs / blog: <DOCS OR BLOG URLS>

## Goal
Produce a self-contained HTML slide deck that explains this framework's AGENTIC
ENGINEERING DESIGN for a technical meeting. Optionally produce a second file
that shows the framework's actual prompts.

Write the files here:
/home/thivux/code/vinai/GUI_agent/AndroidAutonomy/tasks/agentic_framework/<framework-slug>/
- index.html   (the deck, required)
- prompts.html  (the prompts, only if the framework ships prompt templates worth showing)

## Match this reference
Read these two files first and match their structure, quality, and interaction
model (do NOT copy the color palette, pick a new one, see Design below):
- .../tasks/agentic_framework/mobilerun/index.html
- .../tasks/agentic_framework/mobilerun/prompts.html

## Research method (do this before writing a single slide)
1. Read the repo README and the docs/blog. Use WebFetch; for a docs index try
   <docs-root>/llms.txt.
2. Clone or locate the repo source and GROUND every claim in code. Do not infer
   architecture from marketing copy. Specifically find:
   - perception: accessibility tree vs screenshot vs set-of-marks; how elements
     are indexed; what the model actually receives.
   - agent architecture: single agent vs planner/executor vs multi-agent; the
     control loop; how state/messages pass between agents.
   - action space: the atomic actions/tools; index-based vs coordinate-based.
   - models: one model or per-role models; default model; configurability.
   - prompts: where they live, are they templates, what each enforces.
3. Separate VERIFIED facts (from code) from SELF-REPORTED claims (from a vendor
   blog: scores, "top-3", "%"). Label benchmark numbers as self-reported.
4. If you make a substantive interpretation, call the advisor before committing.

## Deck content (3-4 slides, paginated, agentic-design focus only)
DISCARD: CLI/TUI usage, install steps, cloud ops, pricing, integrations.
Lead general to specific. A structure that worked:
- Slide 1 "How it works": the execution mode(s) first (e.g. simple vs reasoning),
  then the main control-flow diagram (the agent loop).
- Slide 2 "The agents/roles": each agent and its job, with a one-line quote from
  its real prompt if available.
- Slide 3 "How it sees the screen": perception. Include a screenshot/overlay image
  if one exists. Add a short "Under the hood" block answering: who builds the
  overlay (script vs model), how grounding works, any fallback path, key flags.
- Slide 4 "A worked example": one concrete task traced through the loop.
Adapt the slides to the framework. If it has no planner/executor split, restructure.

## prompts.html (only if prompts exist)
Toggle/tab layout: one tab per agent (e.g. Planner / Executor / single-agent).
Show the REAL shipped prompt text, lightly trimmed, with simple syntax coloring.
Link to it from the deck.

## Writing rules (strict)
- Short, plain sentences. One idea per sentence.
- NO em dashes. Use periods, colons, "and", or parentheses instead.
- Avoid stacked clauses. Bad: "Two agents with opposite personalities. Neither
  does the other's job, and the prompts enforce it hard." Good: "There are 2
  agents: a planner and an executor. Each has a different role, set by its prompt."
- Define jargon the first time. A reader skimming should follow it.

## Design rules (match the reference's quality, not its look)
- Build a real paginated slide deck: full-viewport slides, arrow-key + button +
  clickable-dot navigation, a page counter, smooth fade between slides.
- Pick a DISTINCT aesthetic per framework so decks are not identical. Vary the
  accent palette and pick a fresh one. Keep a dark, technical, blueprint feel.
- Fonts: use distinctive ones via Google Fonts. Display = a characterful
  geometric/grotesque (e.g. Syne). Body = a readable serif (e.g. Newsreader).
  Code = a mono (e.g. JetBrains Mono). Do NOT use Inter, Roboto, Arial, or
  system fonts. Vary fonts across frameworks.
- Use inline SVG for flow/loop diagrams. Use a real embedded image for any
  screenshot/overlay (copy it into the framework folder).
- Keep each slide digestible: it is one focus at a time, so denser content is ok,
  but never a wall of text. Use cards, small diagrams, and short bullets.
- Make it responsive: multi-column grids collapse to one column on narrow widths.

## Honesty
- State plainly what is verified from code vs claimed by the vendor.
- If a benchmark number is self-reported with no public ablation, say so on the slide.

## Before you finish
- Open the files mentally: confirm the deck has 3-4 slides, navigation works, no
  em dashes, sentences are short, and the screenshot (if any) is embedded.
- Briefly summarize to me what you built and any claims you could not verify.
```

---

## Notes for me (the human), not part of the prompt

- Frameworks I may want decks for: AutoDevice (already drafted in
  `./autodevice/`), plus any others under
  `/home/thivux/code/vinai/GUI_agent/AndroidAutonomy/` (MAI-UI, UI-Venus,
  MobileWorld, MARS-Voyager / UI-Voyager).
- The AutoDevice deck (`./autodevice/index.html`) is a lighter "summary" variant
  (single scroll, no prompts file) because it is closed-source and blog-only.
  Use the full reference (MobileRun) when the framework is open-source and I can
  read its prompts and code; use the AutoDevice variant when it is blog-only.
- Consider a top-level `index.html` in `agentic_framework/` later that links all
  the decks as a comparison hub.
