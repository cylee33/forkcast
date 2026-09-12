# Global Project Rules

## The `brain/` Folder
Every project must contain a `brain/` folder holding the project's persistent context. If the folder or any file below is missing, create it immediately. 

| File | Purpose |
|---|---|
| `brain/plan.md` | Detailed plan showing the needed workflow for the project. upon making these files, make them read-friendly. |
| `brain/tasks.md` | Tasks broken into phases, each as a `- [ ]` checkbox.   |
| `brain/progress.md` | Log of work completed so far, ending with a "pick up here next" note |
| `brain/lessons.md` | Lessons learned: struggles, unexpected situations, and all trial-and-error records |
| `brain/architecture.md` | design the product architecture, how multi-agents are given role (if any), show project pipleine structure, project pipleine flow, etc. Blueprint for building the product |



## Session Start (ALWAYS)
At the start of every session, before doing anything else:

1. Read this CLAUDE.md file.
2. Read all four files in `brain/` to rebuild context.
3. Confirm where the last session left off (from `progress.md`) before proceeding.



## Workflow Rules
- **Always have the relevant agent do the work.** If work falls within a topic that an agent in `.claude/agents/` owns (a sub-index pipeline, DB setup/access, external API calls, backend, frontend, QA, security), delegate to that agent rather than doing the work directly in the main session.
- **Plan before code.** Do NOT start coding until planning is done and I say so. Once a plan is established in /brain/plan.md, 
- **Never start building/coding before I tell you to in the planning phase** I will tell you when I am satisfied with out plan, so we should start building or making anything. I will say phrase like "start making" or "do phase X" or "start coding". Finally then, start building/coding. 
- **Never auto-compact without asking.** Always ask for permission before compacting context.
- **Ask ONE MORE TIME** if I clicked /compact on accident when it is prompted.
- Even when finished with initally planned plan.md, tasks.md, if there are any new updates, remember them and add them to the md files at the end of the session.
- **Do not ever edit ReadMe.md without permission**
- **Write MD files as closely abiding to the ReadMe.md file format/style**



## Session End (ALWAYS)
Before ending a session — triggered by ("ready to") "End Session", "Finish Session", or `/clear` — you MUST complete all of the following:

1. Update checkboxes in `brain/tasks.md` to reflect completed work.
2. Update `brain/progress.md` with a summary of this session and where to pick up next session.
3. Update `brain/plan.md` with any changes to the plan.
4. Update `brain/lessons.md` with any lessons learned this session.
5. Commit all changes to git with a descriptive message.
6. Run `git push` if asked.


# Behavioral guidelines to reduce common LLM coding mistakes. 


## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

New Rule: About every roughly 10 minutes, the main session should pause work and check in with me about progress