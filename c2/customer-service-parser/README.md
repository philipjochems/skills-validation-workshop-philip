.app# Customer Servce Parser

Transcript parsing utility used by support operations to convert plain-text call notes into JSON records.

This package provides a shell-based workflow for parsing support call transcripts into structured JSON output files.

## Purpose

The parser reads one transcript text file and attempts to extract key metadata fields:

- call_id
- date
- customer
- agent
- product
- issue
- resolution
- escalate

It writes a JSON file into the local output folder.

## Package contents

- parse_transcript.sh: main parser script.
- transcripts/transcript-clean.txt: sample transcript that follows expected label format.
- transcripts/transcript-messy.txt: sample transcript that demonstrates parser failure modes.
- output/: destination directory for generated JSON files.

## Prerequisites

- Bash-compatible shell (macOS/Linux or WSL).
- Standard Unix text tools available on PATH:
	- grep
	- sed
	- head
	- basename

## Quick start

From this folder:

```bash
chmod +x parse_transcript.sh
./parse_transcript.sh transcripts/transcript-clean.txt
```

Generated file:

```text
output/transcript-clean.json
```

## Run with both sample files

```bash
./parse_transcript.sh transcripts/transcript-clean.txt
./parse_transcript.sh transcripts/transcript-messy.txt
```

## Input format expectations

The script is line-oriented and expects exact labels at the start of lines, such as:

- Call ID:
- Date:
- Customer:
- Agent:
- Product:
- Issue:
- Resolution:
- Escalate:

Only the first match per label is used. Any variation in spelling, punctuation, field order, or multiline values can produce empty or inaccurate results.

## Output behavior

- Output file name is derived from the input file name.
- Files are written to output/<input_filename>.json.
- Existing output files are overwritten.
- Missing fields are emitted as empty strings.

## Known limitations

- No schema validation.
- Minimal error handling.
- No logging beyond a single success line.
- Naive JSON escaping.
- Cannot reliably parse free-form or conversational transcripts.

## Troubleshooting

- Error "file not found": verify the input path is correct.
- Empty JSON fields: confirm transcript labels exactly match expected format.
- Permission denied: run chmod +x parse_transcript.sh once.

## Modernization note

This package can be extended in future versions to support stronger validation, richer error handling, semantic extraction, and direct warehouse integrations.
