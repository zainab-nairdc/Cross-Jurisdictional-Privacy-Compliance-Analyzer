"""Throwaway: reorder §3.3 sections to match the honest 'first-time
builder' flow.

Changes:
  1. Remove §3.3.15 Deployment (not implemented)
  2. Move §3.3.3 Django scaffold to AFTER §3.3.9 Reasoning agent
  3. Renumber so the order reads:
       3.3.0 Project structure
       3.3.1 Host OS
       3.3.2 Bootstrap
       3.3.3 Data gathering            (was 3.3.4)
       3.3.4 Local LLM setup           (was 3.3.6)
       3.3.5 Model and index init      (was 3.3.5, unchanged number)
       3.3.6 Ingestion pipeline        (was 3.3.7)
       3.3.7 Hybrid retrieval          (was 3.3.8)
       3.3.8 Reasoning agent           (was 3.3.9)
       3.3.9 Django scaffold + DB      (was 3.3.3, moved here)
       3.3.10 Workflow engines
       3.3.11 Copilot chat interface
       3.3.12 Web layer
       3.3.13 Cybersecurity
       3.3.14 Export and audit hash chain
"""
import re
from pathlib import Path

path = (Path(__file__).resolve().parent
        / 'generate_3_3_implementation_v4.py')
src = path.read_text(encoding='utf-8')

# Locate each section block: lines from one '# 3.3.X ' comment to the next
SECTION_RE = re.compile(r'^(    # 3\.3\.\d+ .*$)', re.MULTILINE)
matches = list(SECTION_RE.finditer(src))

# Build a map: section number -> (start_idx, end_idx, text)
blocks = {}
for i, m in enumerate(matches):
    start = m.start()
    end = matches[i + 1].start() if i + 1 < len(matches) else len(src)
    num = m.group(0).strip().split()[1]  # '3.3.X'
    blocks[num] = (start, end, src[start:end])

# Tail after last block: the doc.save() etc.
tail_start = matches[-1].start()
# Find where the last section ENDS for real (before doc.save())
last_end_marker = src.find('doc.save', tail_start)
if last_end_marker == -1:
    last_end_marker = len(src)
# Actually: the last section block runs until the next section comment OR
# until doc.save. Re-derive cleanly:
ordered_old_blocks = sorted(blocks.items(),
                            key=lambda kv: tuple(int(x)
                                                  for x in kv[0]
                                                  .split('.')))

# Section number after which everything that follows is "tail"
last_section_num = ordered_old_blocks[-1][0]   # '3.3.15'
last_section_start = blocks[last_section_num][0]
# tail starts where 3.3.15 starts; but we drop 3.3.15 entirely.
# So tail = whatever comes AFTER the 3.3.15 block (i.e., from
# blocks['3.3.15'][1] onwards).
tail = src[blocks['3.3.15'][1]:]

# Build a fresh ordered list of blocks per the new plan
new_order = [
    ('3.3.0', '3.3.0', 'Project structure overview'),
    ('3.3.1', '3.3.1', 'Host operating system and tooling'),
    ('3.3.2', '3.3.2', 'Project bootstrap'),
    ('3.3.4', '3.3.3', 'Data gathering and corpus assembly'),
    ('3.3.6', '3.3.4', 'Local LLM setup'),
    ('3.3.5', '3.3.5', 'Model and index initialisation'),
    ('3.3.7', '3.3.6', 'Ingestion pipeline'),
    ('3.3.8', '3.3.7', 'Hybrid retrieval'),
    ('3.3.9', '3.3.8', 'Reasoning agent'),
    ('3.3.3', '3.3.9', 'Django scaffold and database initialisation'),
    ('3.3.10', '3.3.10', 'Workflow engines'),
    ('3.3.11', '3.3.11', 'Copilot chat interface'),
    ('3.3.12', '3.3.12', 'Web layer'),
    ('3.3.13', '3.3.13', 'Cybersecurity'),
    ('3.3.14', '3.3.14', 'Export and audit hash chain'),
    # 3.3.15 dropped
]

head = src[:matches[0].start()]
new_body = []
for old_num, new_num, _title in new_order:
    block_text = blocks[old_num][2]
    if old_num != new_num:
        # Replace the heading comment + heading add_heading call
        block_text = block_text.replace(
            f'# {old_num} ', f'# {new_num} ', 1
        )
        block_text = block_text.replace(
            f"'{old_num} ", f"'{new_num} ", 1
        )
    new_body.append(block_text)

result = head + ''.join(new_body) + tail

# Update cross-references in prose
ref_updates = {
    '§3.3.9 reasoning': '§3.3.8 reasoning',   # reasoning moved 9 -> 8
    'general-purpose reasoning graph from §3.3.9':
        'general-purpose reasoning graph from §3.3.8',
}
for old, new in ref_updates.items():
    result = result.replace(old, new)

path.write_text(result, encoding='utf-8')
print('Reordered §3.3 sections; removed §3.3.15')
