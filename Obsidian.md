# AGENT AUTOMATION PROTOCOL

Whenever the user gives a short command or a task, you MUST implicitly execute the following workflow without asking for further permission:

## STEP 1: INITIALIZE (Context Gathering)
- Silently read `D:/PYTHON/freqtrade/obsidian-freqtrade/00_System/Prompts/Architect_Persona.md` to understand your core principles and coding style (e.g., Vectorization, Fault Tolerance for Freqtrade).
- Silently check `D:/PYTHON/freqtrade/obsidian-freqtrade/02_Active_Tasks/` for any specific requirements related to the user's prompt.

## STEP 2: EXECUTION (Do the work)
- Write, modify, or refactor the code in the appropriate project folder based on the user's request.
- Ensure all code strictly follows the Persona rules read in Step 1.

## STEP 3: WRAP-UP (Auto-Logging to Obsidian)
- Once the code is successfully written and there are no immediate errors, automatically generate a brief technical summary.
- Create a new Markdown file in `obsidian-freqtrade/03_Memories/` named `Log_YYYY-MM-DD_TaskName.md`.
- The log must include: What was changed, which files were touched, and any important technical decisions made.

Never ask "Should I log this?". Just do it automatically at the end of the task.