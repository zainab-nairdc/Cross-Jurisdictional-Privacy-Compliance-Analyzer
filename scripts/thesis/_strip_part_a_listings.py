"""Strip Part A code listings from appendix 3 generator.

Removes every 'add_paragraph(...the listing below...)' caption that
precedes an 'add_code(...)' block in Part A only. Part B / C
listings are preserved (they cover the AI pipeline + deployment +
reference tables which the rubric specifically asks for).
"""
from pathlib import Path

path = (Path(__file__).resolve().parent
        / 'generate_appendix_3_implementation_v3.py')
src = path.read_text(encoding='utf-8')

b_marker = src.index('def write_part_b(')
part_a = src[:b_marker]
part_bc = src[b_marker:]

lines = part_a.splitlines(keepends=True)
out = []
i = 0
removed = 0
while i < len(lines):
    line = lines[i]
    # Look for a caption line that mentions 'the listing below'
    if 'the listing below' in line and 'add_paragraph' in line.replace(' ', '') or (
        i + 1 < len(lines)
        and 'add_paragraph' in line.replace(' ', '')
        and 'the listing below' in lines[i + 1]
    ):
        # Skip the add_paragraph block until the closing )
        j = i
        depth = 0
        started = False
        while j < len(lines):
            depth += lines[j].count('(') - lines[j].count(')')
            if not started and 'add_paragraph' in lines[j]:
                started = True
            if started and depth <= 0:
                j += 1
                break
            j += 1
        # Now expect an add_code( call right after
        if j < len(lines) and 'add_code(' in lines[j]:
            k = j
            depth = 0
            while k < len(lines):
                depth += lines[k].count('(') - lines[k].count(')')
                if depth <= 0:
                    k += 1
                    break
                k += 1
            removed += 1
            i = k
            continue
        # No add_code follows — keep the caption
    out.append(line)
    i += 1

print(f'Removed {removed} listings from Part A')
new_part_a = ''.join(out)
path.write_text(new_part_a + part_bc, encoding='utf-8')
