# Zero-Duplication & Single Source of Truth (SSOT) Governance

## 🛡️ MANDATORY ZERO-DUPLICATION & SSOT GOVERNANCE RULE (NON-NEGOTIABLE)

1. **Mandatory Pre-Action Verification Protocol**:
   - BEFORE adding any new rule, guideline, prompt, workflow, or skill—and BEFORE modifying or updating existing instructions—the AI agent MUST proactively search, inspect, and confirm existing instructions across:
     • Master rulebooks (`AGENTS.md`, `CLAUDE.md`, etc.)
     • System rule directories (`.agents/rules/`, `.ai/rules/`, `.cursor/rules/`)
     • AI skills and references (`.agents/skills/`, `skills/`)
   - Never assume an instruction or guideline is missing without actively searching first.

2. **Strict Prohibition of Duplication**:
   - AI agents, subagents, and automated tools are strictly forbidden from copy-pasting full rule text, guidelines, schemas, or skill descriptions across multiple files.
   - Every domain concept, technical standard, architectural decision, and system instruction must maintain exactly ONE canonical Single Source of Truth (SSOT) file.

3. **Modification vs. Creation Protocol**:
   - If a matching rule or skill already exists: Modify and update that existing canonical file directly. Never create shadow, duplicate, or "v2" rule files.
   - If a new rule is genuinely required: Create it in exactly ONE canonical file.

4. **Lightweight Pointers Only**:
   - If other files need to reference a canonical rule, use a 1- to 2-sentence summary with a direct markdown link (`👉 [rule-name.md](path/to/file)`). Never duplicate the body.

5. **Strict Prohibition of Mirror Clones**:
   - Never maintain multi-hundred-line duplicate copies of master rulebooks. Tool-specific entry points must strictly remain lightweight pointers.
