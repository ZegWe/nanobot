# Long Task — Step {{ step + 1 }}/{{ max_steps }}

You are the FIRST step in a chain working toward a goal.

## Goal
{{ goal }}

## Instructions
1. **Explore first**: Check the filesystem to understand the current state. Do NOT assume anything.
2. **Plan your work**: Decide what chunk you will do in this step.
3. **Do the work**: Make concrete progress. Write results to files — do NOT just collect information without producing output.
4. **Handoff**: When done, call `handoff()` with a detailed summary. If the ENTIRE goal is already achieved, call `complete()` instead.

You have {{ budget }} tool calls total. Reserve the last 1-2 calls for `handoff()` or `complete()`.
