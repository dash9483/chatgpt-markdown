import json
import os
import re
import argparse
from datetime import datetime, timezone


def sanitize_filename(filename):
    if filename is None or filename.strip() == "":
        return "noname"
    invalid_characters = '<>:"/\\|?*\n\t'
    for char in invalid_characters:
        filename = filename.replace(char, '')
    return filename


def format_timestamp(ts):
    """Convert UNIX timestamp to local ISO datetime string with offset."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()  # convert to local timezone
    return dt.strftime("%Y-%m-%d %H:%M:%S %z")


def clean_text(text):
    """
    Remove or simplify placeholder references like '18 turn0search4' → ''
    Preserve line breaks and indentation.
    """
    if not isinstance(text, str):
        text = str(text)
    # Remove "## citations" style IDs
    text = re.sub(r"\b\d+\s+turn\d+search\d+\b", "", text)
    # Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return text


def get_conversation(node_id, mapping, collected, last_author=None, visited=None):
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

        # Skip system messages entirely
        if author_role != "system":
            content_parts = msg["content"]["parts"]
            parts_text = [clean_text(part) for part in content_parts]

            ts = msg.get("create_time")
            timestamp_line = f"Date: {format_timestamp(ts)}" if ts else "Date: unknown"

            snippet = f"## {author_role}\n\n{timestamp_line}\n\n{''.join(parts_text)}"
            collected.append(snippet)
            last_author = author_role

    # Recurse through children safely
    for child_id in node.get("children", []):
        get_conversation(child_id, mapping, collected, last_author, visited)


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


def main(input_file, output_dir, use_date_folders):
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    for item in data:
        title = sanitize_filename(item.get("title"))

        # Find last message create_time
        timestamps = [
            node['message']['create_time']
            for node in item['mapping'].values()
            if node.get('message') and node['message'].get('create_time')
        ]
        date_prefix = datetime.fromtimestamp(max(timestamps)).date().isoformat() if timestamps else "unknown-date"

        root_node_id = next(
            node_id for node_id, node in item['mapping'].items()
            if node.get('parent') is None
        )

        collected = []
        get_conversation(root_node_id, item['mapping'], collected)

        if use_date_folders:
            date_iso = datetime.fromtimestamp(item.get("create_time", 0)).date().isoformat()
            date_folder = os.path.join(output_dir, date_iso)
            if not os.path.isdir(date_folder):
                os.makedirs(date_folder)
            file_path = generate_unique_filename(date_folder, title, date_prefix)
        else:
            file_path = generate_unique_filename(output_dir, title, date_prefix)

        # Prepare output lines with spacing rules:
        # 1. Blank line before each header except the first
        # 2. Extra blank line after each snippet except the last
        output_lines = []
        for i, snippet in enumerate(collected):
            if i != 0:
                output_lines.append('')  # blank line before header
            output_lines.append(snippet)
            if i < len(collected) - 1:
                output_lines.append('')  # extra blank line after snippet

        print(f"Attempting to write to: {file_path}")
        with open(file_path, 'w', encoding='utf-8') as outfile:
            outfile.write('\n'.join(output_lines))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process conversation data.')
    parser.add_argument('input_file', help='JSON file containing conversations')
    parser.add_argument('output_dir', help='Directory to save output Markdown files')
    parser.add_argument('--use-date-folders', action='store_true', help='Store files under date-based folders')

    args = parser.parse_args()
    main(args.input_file, args.output_dir, args.use_date_folders)
