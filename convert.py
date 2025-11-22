import json
import os
import re
import argparse
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


# ============================================================
# Collect ALL messages, ignoring order
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
# Main
# ============================================================

def main(input_file, output_dir, use_date_folders):

    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    for item in data:

        title = sanitize_filename(item.get("title", ""))

        # Extract timestamps for filename prefix
        timestamps = [
            node.get("message", {}).get("create_time")
            for node in item.get("mapping", {}).values()
            if node.get("message") and node["message"].get("create_time")
        ]

        date_prefix = (
            datetime.fromtimestamp(max(timestamps)).date().isoformat()
            if timestamps else "unknown-date"
        )

        mapping = item.get("mapping", {})

        # ------------------------------
        # STEP 1: Collect all messages
        # ------------------------------
        messages = collect_all_messages(mapping)

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
            date_iso = datetime.fromtimestamp(item.get("create_time", 0)).date().isoformat()
            date_folder = os.path.join(output_dir, date_iso)
            os.makedirs(date_folder, exist_ok=True)
            file_path = generate_unique_filename(date_folder, title, date_prefix)
        else:
            file_path = generate_unique_filename(output_dir, title, date_prefix)

        print(f"Writing file: {file_path}")
        with open(file_path, "w", encoding="utf-8") as outfile:
            outfile.write("\n".join(output_lines))


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export ChatGPT JSON → Markdown")
    parser.add_argument("input_file", help="JSON export file")
    parser.add_argument("output_dir", help="Directory for Markdown output")
    parser.add_argument("--use-date-folders", action="store_true")
    args = parser.parse_args()

    main(args.input_file, args.output_dir, args.use_date_folders)
