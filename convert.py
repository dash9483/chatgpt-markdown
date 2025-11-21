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
        filename = filename.replace(char, '')
    return filename


def format_timestamp(ts):
    """Convert UNIX timestamp to local ISO datetime string with offset."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S %z")


def format_timestamp_for_index(ts):
    """Timestamp without timezone for clean index."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M")


def clean_text(text):
    """
    Preserve everything:
      - whitespace
      - code blocks
      - tables
      - indentation
      - blank lines
    Only remove placeholder references like "18 turn0search4".
    """
    if not isinstance(text, str):
        text = str(text)

    text = re.sub(r"\b\d+\s+turn\d+search\d+\b", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text

# ============================================================
# Gather conversation structure + navigation data
# ============================================================

def get_conversation(node_id, mapping, collected, nav_list, counter, visited=None):
    if visited is None:
        visited = set()
    if node_id in visited:
        return
    visited.add(node_id)

    node = mapping.get(node_id)
    if not node:
        return

    msg = node.get("message")
    if msg and "content" in msg and "parts" in msg["content"]:

        author_role = msg["author"]["role"]

        # Skip system messages
        if author_role != "system":

            content_parts = msg["content"]["parts"]
            parts_text = [clean_text(part) for part in content_parts]

            ts = msg.get("create_time")
            timestamp_line = f"Date: {format_timestamp(ts)}" if ts else "Date: unknown"

            # Build anchor name
            anchor = f"message-{counter[0]}--{author_role}"

            # FIXED — remove invalid f-string from your version
            safe_text = "".join(parts_text)

            snippet = (
                f"<a id=\"{anchor}\"></a>\n"
                f"## {author_role}\n\n"
                f"{timestamp_line}\n\n"
                f"{safe_text}"
            )

            collected.append(snippet)

            # Add navigation entry
            if ts:
                nav_list.append({
                    "number": counter[0],
                    "role": author_role,
                    "ts": ts,
                    "anchor": anchor
                })

            counter[0] += 1

    for child_id in node.get("children", []):
        get_conversation(child_id, mapping, collected, nav_list, counter, visited=visited)

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

        title = sanitize_filename(item.get("title"))

        timestamps = [
            node["message"]["create_time"]
            for node in item["mapping"].values()
            if node.get("message") and node["message"].get("create_time")
        ]

        date_prefix = (
            datetime.fromtimestamp(max(timestamps)).date().isoformat()
            if timestamps else "unknown-date"
        )

        # Find root node
        root_node_id = next(
            node_id for node_id, node in item["mapping"].items()
            if node.get("parent") is None
        )

        collected = []
        nav_list = []
        counter = [1]  # message counter

        # Collect conversation & navigation
        get_conversation(root_node_id, item["mapping"], collected, nav_list, counter)

        # Build navigation index
        nav_lines = ["# Thread Navigation Index", ""]
        for entry in nav_list:
            ts_clean = format_timestamp_for_index(entry["ts"])
            nav_lines.append(
                f"- [{ts_clean} — {entry['role']}](#{entry['anchor']})"
            )
        nav_lines.append("")
        nav_lines.append("---")
        nav_lines.append("")

        # Folder setup
        if use_date_folders:
            date_iso = datetime.fromtimestamp(
                item.get("create_time", 0)
            ).date().isoformat()
            date_folder = os.path.join(output_dir, date_iso)
            if not os.path.isdir(date_folder):
                os.makedirs(date_folder)

            file_path = generate_unique_filename(date_folder, title, date_prefix)
        else:
            file_path = generate_unique_filename(output_dir, title, date_prefix)

        # Output with 2 blank lines between snippets
        output_lines = nav_lines[:]

        for i, snippet in enumerate(collected):
            output_lines.append(snippet)
            if i < len(collected) - 1:
                output_lines.append("")  # blank line 1
                output_lines.append("")  # blank line 2

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
