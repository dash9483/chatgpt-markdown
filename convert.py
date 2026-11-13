r"""
convert.py - turn a ChatGPT or Claude chat export into Markdown files
=====================================================================

WHAT IT DOES
    Reads the conversations file from a ChatGPT or Claude data export and
    writes ONE Markdown (.md) file per conversation. The output format is the
    same for both services:

      * a "Thread Navigation Index" at the top (clickable list of messages)
      * one "## role (message: N)" section per message, with its date
      * messages sorted by real timestamp and numbered from 1

    File names look like:   2026-11-04 Chat title.md
      - the date is the date of the LAST message in the chat
      - if the name already exists, _v1, _v2, ... is added
      - chats without a title are called "noname"

SUPPORTED EXPORTS
    ChatGPT : conversations.json (or the export .zip that contains it)
    Claude  : conversations.json inside conversations-000.zip
              (Claude's export is split into several zips; you only need the
              "conversations" one. The small manifest .json is NOT enough.)

    The export type is detected automatically. Use --source to force it.

HOW TO GET THE EXPORT FILES
    ChatGPT : Settings > Data controls > Export data (link arrives by email)
    Claude  : Settings > Privacy > Export data on claude.ai in a browser
              (not possible in the mobile apps). The email links expire after
              24 hours, so download the files right away.

USAGE
    python convert.py INPUT_FILE OUTPUT_DIR [options]

    INPUT_FILE   conversations.json, or a .zip that contains it
    OUTPUT_DIR   folder for the .md files (created if missing)

OPTIONS
    --source {auto,chatgpt,claude}
                        Export type. Default: auto (detected from the JSON).
    --use-date-folders  Put each file in a sub-folder named after the date the
                        chat was created (OUTPUT_DIR/2026-11-04/...).
    --keyword WORD      Only convert chats where WORD appears in the title or
                        in any message. Whole words only, case-insensitive, so
                        "ERP" will not match "enterprise". Can be repeated;
                        a chat is kept if ANY of the words match.

EXAMPLES
    # Claude export, straight from the zip, auto-detected
    python convert.py conversations-000.zip claude_md

    # ChatGPT export, straight from the zip
    python convert.py chatgpt_export.zip chatgpt_md

    # Already unzipped, one folder per creation date
    python convert.py conversations.json out --use-date-folders

    # Force the type instead of auto-detecting
    python convert.py conversations.json out --source claude

    # Only chats that mention CBT or ERP (English, Swedish, Spanish terms)
    python convert.py conversations-000.zip cbt_erp --keyword CBT --keyword ERP --keyword KBT --keyword TCC

    # Windows (use the full path if the file is somewhere else)
    python convert.py "C:\Users\me\Downloads\conversations-000.zip" "C:\Users\me\claude_md"

WHAT IS LEFT OUT
    ChatGPT : system messages.
    Claude  : thinking blocks, tool calls and web-search results, and internal
              system/memory blocks. Text attachments (pasted text) are
              included. Empty conversations are skipped and reported.

NOTES
    * If you edited or regenerated a message, ALL versions are written, in
      time order (both for ChatGPT and for Claude).
    * Output files are never overwritten; re-running creates _v1, _v2 copies,
      so use a fresh OUTPUT_DIR for each run.
    * Only the Python standard library is used (Python 3.8+).
"""
import json
import os
import re
import argparse
import zipfile
from datetime import datetime, timezone


# ============================================================
# Utilities
# ============================================================

def sanitize_filename(filename):
    if filename is None or filename.strip() == "":
        return "noname"
    invalid_characters = '<>:"/\\|?*\n\t'
    for char in invalid_characters:
        filename = filename.replace(char, "")
    return filename


def format_timestamp(ts):
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S %z")


def format_timestamp_for_index(ts):
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M")


def clean_text(text):
    if not isinstance(text, str):
        text = str(text)
    # Remove placeholder refs like "18 turn0search4"
    text = re.sub(r"\b\d+\s+turn\d+search\d+\b", "", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def iso_to_ts(value):
    """Claude timestamps are ISO strings like 2026-08-15T15:11:45.990581Z."""
    if not value:
        return 0
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


# ============================================================
# Loading + source detection
# ============================================================

def load_conversations(input_file):
    """Load a conversations JSON file, or the conversations*.json inside a .zip."""
    if input_file.lower().endswith(".zip"):
        data = []
        with zipfile.ZipFile(input_file) as zf:
            names = sorted(
                n for n in zf.namelist()
                if os.path.basename(n).startswith("conversations")
                and n.lower().endswith(".json")
            )
            if not names:
                raise SystemExit("No conversations*.json found inside the zip file.")
            for name in names:
                with zf.open(name) as f:
                    data.extend(json.load(f))
        return data

    with open(input_file, "r", encoding="utf-8") as f:
        return json.load(f)


def detect_source(data):
    for item in data:
        if "mapping" in item:
            return "chatgpt"
        if "chat_messages" in item:
            return "claude"
    raise SystemExit("Could not detect export type. Use --source chatgpt or --source claude.")


# ============================================================
# ChatGPT parser (unchanged behaviour)
# ============================================================

def collect_all_messages(mapping):
    messages = []

    for node_id, node in mapping.items():
        msg = node.get("message")
        if not msg:
            continue

        author_role = msg.get("author", {}).get("role")
        if author_role == "system":
            continue

        content = msg.get("content", {})
        parts = content.get("parts", [])

        parts_text = [clean_text(p) for p in parts]

        ts = msg.get("create_time", 0)

        messages.append({
            "ts": ts,
            "role": author_role,
            "parts": parts_text,
            "node_id": node_id
        })

    return messages


def parse_chatgpt(item):
    mapping = item.get("mapping", {})

    timestamps = [
        node.get("message", {}).get("create_time")
        for node in mapping.values()
        if node.get("message") and node["message"].get("create_time")
    ]

    return {
        "title": sanitize_filename(item.get("title", "")),
        "last_ts": max(timestamps) if timestamps else None,
        "create_ts": item.get("create_time", 0),
        "messages": collect_all_messages(mapping),
    }


# ============================================================
# Claude parser
# ============================================================

def fenced(text):
    """Wrap text in a code fence long enough to survive backticks inside it."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def claude_message_text(msg):
    # Use the "text" content blocks. The top-level "text" field also contains
    # placeholders for tool calls ("This block is not supported ...").
    # Thinking blocks, tool calls/results and injected prompt blocks are skipped.
    blocks = msg.get("content") or []
    if blocks:
        texts = [b.get("text") or "" for b in blocks if b.get("type") == "text"]
        text = "\n\n".join(t for t in texts if t.strip())
    else:
        text = msg.get("text") or ""

    extra = []
    for att in msg.get("attachments") or []:
        name = att.get("file_name") or "unnamed"
        label = f"**Attachment:** {name} ({att.get('file_type') or '?'}, {att.get('file_size', '?')} bytes)"
        content = att.get("extracted_content")
        extra.append(label + (f"\n\n{fenced(content)}" if content else ""))
    for f in msg.get("files") or []:
        if f.get("file_name"):
            extra.append(f"**File:** {f['file_name']}")

    return clean_text("\n\n".join([t for t in [text] + extra if t.strip()]))


def parse_claude(item):
    messages = []
    for msg in item.get("chat_messages", []):
        text = claude_message_text(msg)
        if not text.strip():
            continue  # empty placeholder messages
        role = "user" if msg.get("sender") == "human" else msg.get("sender", "assistant")
        messages.append({
            "ts": iso_to_ts(msg.get("created_at")),
            "role": role,
            "parts": [text],
            "node_id": msg.get("uuid"),
        })

    return {
        "title": sanitize_filename(item.get("name", "")),
        "last_ts": max((m["ts"] for m in messages), default=None),
        "create_ts": iso_to_ts(item.get("created_at")),
        "messages": messages,
    }


PARSERS = {"chatgpt": parse_chatgpt, "claude": parse_claude}


# ============================================================
# File naming
# ============================================================

def generate_unique_filename(base_path, title, date_prefix):
    version = 0
    title = title if title.strip() != "" else "noname"
    base_name = f"{date_prefix} {title}.md"
    file_path = os.path.join(base_path, base_name)

    while os.path.exists(file_path):
        version += 1
        base_name = f"{date_prefix} {title}_v{version}.md"
        file_path = os.path.join(base_path, base_name)

    return file_path


# ============================================================
# Keyword filter (optional)
# ============================================================

def build_keyword_regex(keywords):
    if not keywords:
        return None
    pattern = "|".join(re.escape(k) for k in keywords)
    return re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE)


def conversation_matches(regex, title, messages):
    if regex is None:
        return True
    if regex.search(title):
        return True
    return any(regex.search("".join(m["parts"])) for m in messages)


# ============================================================
# Main
# ============================================================

def main(input_file, output_dir, use_date_folders, source="auto", keywords=None):

    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    data = load_conversations(input_file)

    if source == "auto":
        source = detect_source(data)
        print(f"Detected export type: {source}")
    parse = PARSERS[source]

    keyword_regex = build_keyword_regex(keywords)
    written = 0

    for item in data:

        conv = parse(item)
        title = conv["title"]
        messages = conv["messages"]

        if source == "claude" and not messages:
            print(f"Skipping empty conversation: {title}")
            continue

        if not conversation_matches(keyword_regex, title, messages):
            continue

        date_prefix = (
            datetime.fromtimestamp(conv["last_ts"]).date().isoformat()
            if conv["last_ts"] else "unknown-date"
        )

        # ------------------------------
        # STEP 2: Sort by real timestamp
        # ------------------------------
        messages.sort(key=lambda x: x["ts"])

        # ------------------------------
        # STEP 3: Assign new correct numbers
        # ------------------------------
        for i, msg in enumerate(messages, start=1):
            msg["number"] = i
            msg["anchor"] = f"message-{i}--{msg['role']}"

        # ------------------------------
        # Build navigation index
        # ------------------------------
        nav_lines = ["# Thread Navigation Index", ""]
        for msg in messages:
            ts_clean = format_timestamp_for_index(msg["ts"])
            nav_lines.append(
                f"- [{ts_clean} — {msg['role']} (message {msg['number']})](#{msg['anchor']})"
            )
        nav_lines.append("")
        nav_lines.append("---")
        nav_lines.append("")

        # ------------------------------
        # Build conversation sections
        # ------------------------------
        output_lines = nav_lines[:]

        for idx, msg in enumerate(messages):
            snippet = (
                f"<a id=\"{msg['anchor']}\"></a>\n"
                f"## {msg['role']} (message: {msg['number']})\n\n"
                f"Date: {format_timestamp(msg['ts'])}\n\n"
                f"{''.join(msg['parts'])}"
            )

            output_lines.append(snippet)

            if idx < len(messages) - 1:
                output_lines.append("")
                output_lines.append("")

        # ------------------------------
        # Output path
        # ------------------------------
        if use_date_folders:
            date_iso = datetime.fromtimestamp(conv["create_ts"] or 0).date().isoformat()
            date_folder = os.path.join(output_dir, date_iso)
            os.makedirs(date_folder, exist_ok=True)
            file_path = generate_unique_filename(date_folder, title, date_prefix)
        else:
            file_path = generate_unique_filename(output_dir, title, date_prefix)

        print(f"Writing file: {file_path}")
        with open(file_path, "w", encoding="utf-8") as outfile:
            outfile.write("\n".join(output_lines))
        written += 1

    print(f"Done. {written} file(s) written.")


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export ChatGPT / Claude JSON → Markdown")
    parser.add_argument("input_file", help="conversations.json (or the export .zip containing it)")
    parser.add_argument("output_dir", help="Directory for Markdown output")
    parser.add_argument("--use-date-folders", action="store_true")
    parser.add_argument("--source", choices=["auto", "chatgpt", "claude"], default="auto",
                        help="Export type (default: auto-detect from the JSON structure)")
    parser.add_argument("--keyword", action="append", default=[],
                        help="Only convert conversations whose title or text contains this whole word "
                             "(case-insensitive). Repeat for several, e.g. --keyword CBT --keyword ERP")
    args = parser.parse_args()

    main(args.input_file, args.output_dir, args.use_date_folders, args.source, args.keyword)
