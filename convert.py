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
    """Timestamp without seconds for clean index."""
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
    # remove placeholder ids but keep whitespace intact
    text = re.sub(r"\b\d+\s+turn\d+search\d+\b", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text

# ============================================================
# Iterative conversation traversal (stack-based DFS)
# ============================================================

def traverse_conversation_iterative(mapping, root_node_id):
    """
    Iteratively traverse the conversation graph starting from root_node_id.
    Returns (collected_snippets_list, nav_list)
    collected_snippets_list: list of snippet strings in traversal order
    nav_list: list of dicts with keys number, role, ts, anchor
    """

    collected = []
    nav_list = []
    counter = 1

    visited = set()
    # Use stack for DFS. Each entry: node_id
    # To preserve child order similar to recursion, push children in reversed order.
    stack = [root_node_id]

    while stack:
        node_id = stack.pop()
        if node_id in visited:
            continue
        visited.add(node_id)

        node = mapping.get(node_id)
        if not node:
            continue

        msg = node.get("message")
        if msg and "content" in msg and "parts" in msg["content"]:
            author_role = msg.get("author", {}).get("role")
            # Skip system messages
            if author_role != "system":
                content_parts = msg["content"]["parts"]
                # content parts may be strings or dicts; convert safely preserving formatting
                parts_text = []
                for p in content_parts:
                    parts_text.append(clean_text(p))

                ts = msg.get("create_time")
                timestamp_line = f"Date: {format_timestamp(ts)}" if ts else "Date: unknown"

                anchor = f"message-{counter}--{author_role}"
                snippet = (
                    f"<a id=\"{anchor}\"></a>\n"
                    f"## {author_role} (message: {counter})\n\n"
                    f"{timestamp_line}\n\n"
                    f"{''.join(parts_text)}"
                )

                collected.append(snippet)

                if ts:
                    nav_list.append({
                        "number": counter,
                        "role": author_role,
                        "ts": ts,
                        "anchor": anchor
                    })

                counter += 1

        # Push children to stack (reverse order so first child is processed first)
        children = node.get("children", [])
        if isinstance(children, list) and children:
            for child_id in reversed(children):
                # only push hashable ids (strings, ints). If not hashable, convert to str.
                stack.append(child_id)

    return collected, nav_list

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
            node.get("message", {}).get("create_time")
            for node in item.get("mapping", {}).values()
            if node.get("message") and node["message"].get("create_time")
        ]

        date_prefix = (
            datetime.fromtimestamp(max(timestamps)).date().isoformat()
            if timestamps else "unknown-date"
        )

        # Find root node (parent == None)
        root_node_id = next(
            (node_id for node_id, node in item["mapping"].items() if node.get("parent") is None),
            None
        )

        if root_node_id is None:
            # fallback: pick an arbitrary node
            root_node_id = next(iter(item.get("mapping", {}).keys()), None)
            if root_node_id is None:
                continue  # nothing to process

        collected, nav_list = traverse_conversation_iterative(item["mapping"], root_node_id)

        # Build navigation index sorted by timestamp ascending
        nav_sorted = sorted(nav_list, key=lambda x: x["ts"])

        nav_lines = ["# Thread Navigation Index", ""]
        for entry in nav_sorted:
            ts_clean = format_timestamp_for_index(entry["ts"])
            nav_lines.append(f"- [{ts_clean} — {entry['role']} (message {entry['number']})](#{entry['anchor']})")
        nav_lines.append("")
        nav_lines.append("---")
        nav_lines.append("")

        # Determine output file path
        if use_date_folders:
            date_iso = datetime.fromtimestamp(item.get("create_time", 0)).date().isoformat()
            date_folder = os.path.join(output_dir, date_iso)
            if not os.path.isdir(date_folder):
                os.makedirs(date_folder)
            file_path = generate_unique_filename(date_folder, title, date_prefix)
        else:
            file_path = generate_unique_filename(output_dir, title, date_prefix)

        # Assemble final file with 2 blank lines between snippets
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