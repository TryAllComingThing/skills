---
name: skill-i18n
description: Translate SKILL.md and README.md files into multiple languages for sharing skills internationally
---

# Skill i18n

Translate skill documentation files (SKILL.md, README.md) into multiple languages, making it easier to share skills with international users.

## Usage

| Command | Description |
|---------|-------------|
| `/skill-i18n` | Translate files in current skill directory |
| `/skill-i18n <skill-name>` | Translate files for specified skill |
| `/skill-i18n config` | Configure default languages and file types |
| `/skill-i18n --lang zh-CN` | Translate to specified languages (for integration) |
| `/skill-i18n --files SKILL.md,README.md` | Translate specified files |

## Supported Languages

| Language | Code | Output File |
|----------|------|-------------|
| 简体中文 | `zh-CN` | `SKILL.zh-CN.md` |
| 日本語 | `ja` | `SKILL.ja.md` |
| 한국어 | `ko` | `SKILL.ko.md` |
| Español | `es` | `SKILL.es.md` |
| Custom | User-defined | `SKILL.<code>.md` |

## Configuration

All settings are stored in `~/.claude/skill-i18n-config.json`:

```json
{
  "default_languages": ["zh-CN"],
  "default_files": ["SKILL.md"]
}
```

**Configuration Fields:**

| Field | Description | Default |
|-------|-------------|---------|
| `default_languages` | Languages to translate by default | `["zh-CN"]` |
| `default_files` | Files to translate by default | `["SKILL.md"]` |

## Execution Steps

### Command: `/skill-i18n`

Translate files in current skill directory:

1. **Detect current directory**
   ```bash
   # Check if current directory contains SKILL.md
   if [ ! -f SKILL.md ]; then
     echo "Error: SKILL.md not found in current directory"
     exit 1
   fi
   ```

2. **Load configuration**
   ```bash
   # Read config file
   CONFIG=$(cat ~/.claude/skill-i18n-config.json 2>/dev/null || echo '{}')

   # Get skill name from directory
   SKILL_NAME=$(basename "$(pwd)")
   ```

3. **First-run selection (if no config)**

   If no configuration exists for this skill, show TUI selection:

   ```json
   {
     "questions": [
       {
         "question": "Which languages should be generated?",
         "header": "Languages",
         "multiSelect": true,
         "options": [
           { "label": "简体中文 (zh-CN)", "description": "Simplified Chinese" },
           { "label": "日本語 (ja)", "description": "Japanese" },
           { "label": "한국어 (ko)", "description": "Korean" },
           { "label": "Español (es)", "description": "Spanish" }
         ]
       },
       {
         "question": "Which files should be translated?",
         "header": "Files",
         "multiSelect": true,
         "options": [
           { "label": "SKILL.md", "description": "Skill documentation (recommended)" },
           { "label": "README.md", "description": "Repository readme" }
         ]
       }
     ]
   }
   ```

4. **Save configuration**
   ```bash
   # Save selection to config for future runs
   jq --arg skill "$SKILL_NAME" \
      --argjson langs '["zh-CN"]' \
      --argjson files '["SKILL.md"]' \
      ~/.claude/skill-i18n-config.json > tmp.json && mv tmp.json ~/.claude/skill-i18n-config.json
   ```

5. **Execute translation**
   - For each selected file and language, generate translation
   - See "Translation Rules" section below

### Command: `/skill-i18n <skill-name>`

Translate files for specified skill:

1. **Search skill location**
   ```bash
   # Search in common locations
   SKILL_PATH=""

   # Check ~/.claude/skills/
   if [ -d ~/.claude/skills/"$SKILL_NAME" ]; then
     SKILL_PATH=~/.claude/skills/"$SKILL_NAME"
   fi

   if [ -z "$SKILL_PATH" ]; then
     echo "Error: Skill '$SKILL_NAME' not found"
     exit 1
   fi
   ```

2. **Execute translation** (same as default command)

### Command: `/skill-i18n config`

Configure default settings:

1. **Show current configuration**
   ```bash
   echo "Current configuration:"
   cat ~/.claude/skill-i18n-config.json | jq .
   ```

2. **Interactive configuration via AskUserQuestion**
   ```json
   {
     "questions": [
       {
         "question": "Select default languages for new skills:",
         "header": "Defaults",
         "multiSelect": true,
         "options": [
           { "label": "简体中文 (zh-CN)", "description": "Simplified Chinese" },
           { "label": "日本語 (ja)", "description": "Japanese" },
           { "label": "한국어 (ko)", "description": "Korean" },
           { "label": "Español (es)", "description": "Spanish" }
         ]
       }
     ]
   }
   ```

3. **Update configuration file**


## Translation Rules

### Preserve Unchanged

These elements must NOT be translated:

- **Code blocks** (```bash, ```json, etc.)
- **File paths** (`~/.claude/settings.json`, `~/Codes/skills/`)
- **Command names** (`/skill-i18n`, `git push`)
- **Technical identifiers** (variable names, JSON keys)
- **URLs and links**

### Translate Naturally

- Adapt sentence structure to target language
- Use appropriate formality level:
  - Japanese: Polite form (です/ます)
  - Chinese: Standard written form
  - Korean: Polite form (합니다/습니다)
  - Spanish: Formal usted form
- Localize examples where appropriate

### Frontmatter Handling

```yaml
---
name: port-allocator          # Keep unchanged (identifier)
description: Translate this   # Translate to target language
---
```

### Style Adaptation

Different languages may use different visual styles:

| Language | Emoji Usage | Example |
|----------|-------------|---------|
| Chinese (zh-CN) | Common | ✅ 正确 / ❌ 错误 |
| Japanese (ja) | Minimal | 正しい / 間違い |
| Korean (ko) | Moderate | ✅ 올바름 / ❌ 잘못됨 |
| Spanish (es) | Minimal | Correcto / Incorrecto |

Follow existing translation patterns in the project if available.

## Output Format

### Translation Success

```
Translation complete

Source: SKILL.md

Generated:
  - SKILL.zh-CN.md (简体中文)

Next run will auto-translate to: zh-CN
```

### Existing Files Detected

```
Existing translations detected:
  - SKILL.zh-CN.md

Options:
  [ ] Overwrite all
  [ ] Skip existing
  [ ] Select individually
```

### Configuration Saved

```
Configuration updated

Default languages: zh-CN
Default files: SKILL.md
```

## Notes

1. **Source file safety** - Never overwrite the source `SKILL.md` file
2. **First-run prompt** - First translation requires language selection
3. **Per-skill config** - Different skills can have different language settings
4. **Incremental updates** - Only translate when source file is newer than translations
5. **Integration-friendly** - Command-line flags allow other skills to call skill-i18n
