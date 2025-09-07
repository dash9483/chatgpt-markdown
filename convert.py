import json
import os
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


def get_conversation(node_id, mapping, collected, last_author=None):
    node = mapping[node_id]

    if node.get('message') and 'content' in node['message'] and 'parts' in node['message']['content']:
        content_parts = node['message']['content']['parts']
        parts_text = []
        for part in content_parts:
            if isinstance(part, str):
                parts_text.append(part)
            elif isinstance(part, dict):
                parts_text.append(str(part))

        if parts_text:
            author_role = node['message']['author']['role']
            ts = node['message'].get('create_time')
            timestamp_line = f"Date: {format_timestamp(ts)}" if ts else "Date: unknown"

            if author_role != "system" and author_role != last_author:
                collected.append(f"## {author_role}\n\n{timestamp_line}\n\n{''.join(parts_text)}")
            elif author_role != "system":
                collected.append(f"\n{timestamp_line}\n\n{''.join(parts_text)}")

            last_author = author_role

    for child_id in node.get('children', []):
        get_conversation(child_id, mapping, collected, last_author)


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
        data = json.loads(f.read())
        for item in data:
            title = sanitize_filename(item.get("title"))

            # Find last message create_time
            timestamps = []
            for node in item['mapping'].values():
                if node.get('message') and node['message'].get('create_time'):
                    timestamps.append(node['message']['create_time'])
            if timestamps:
                last_ts = max(timestamps)
                date_prefix = datetime.fromtimestamp(last_ts).date().isoformat()
            else:
                date_prefix = "unknown-date"

            root_node_id = next(
                node_id for node_id, node in item['mapping'].items()
                if node.get('parent') is None
            )
            collected = []
            get_conversation(root_node_id, item['mapping'], collected)

            if use_date_folders:
                date_iso = datetime.fromtimestamp(item["create_time"]).date().isoformat()
                date_folder = os.path.join(output_dir, date_iso)
                if not os.path.isdir(date_folder):
                    os.makedirs(date_folder)
                file_path = generate_unique_filename(date_folder, title, date_prefix)
            else:
                file_path = generate_unique_filename(output_dir, title, date_prefix)

            print(f"Attempting to write to: {file_path}")
            with open(file_path, 'w', encoding='utf-8') as outfile:
                outfile.write('\n\n'.join(collected))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process conversation data.')
    parser.add_argument('input_file', help='JSON file containing conversations')
    parser.add_argument('output_dir', help='Directory to save output Markdown files')
    parser.add_argument('--use-date-folders', action='store_true', help='Store files under date-based folders')

    args = parser.parse_args()
    main(args.input_file, args.output_dir, args.use_date_folders)
