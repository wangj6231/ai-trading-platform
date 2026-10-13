"""F4.1 final-code coverage; stale changed-file line maps are excluded."""
from pathlib import Path
import json

from coverage import Coverage, CoverageData

from tests.fixtures.dashboard_composition_profile import OUTPUT
from tests.fixtures.journal_readmodel_profile import ROOT, protected


def run():
    before = json.loads((OUTPUT / 'protected_before.json').read_text(encoding='utf8'))
    after = protected()
    changed = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
    result = CoverageData(basename=str(OUTPUT / '.coverage.combined'))
    for name, final in (('.coverage.units', False), ('.coverage.pg', False), ('.coverage.final_seams', True)):
        data = CoverageData(basename=str(OUTPUT / name))
        data.read()
        for filename in data.measured_files():
            relative = Path(filename).resolve().relative_to(ROOT).as_posix()
            if relative in changed and not final:
                continue
            if data.has_arcs():
                result.add_arcs({filename: data.arcs(filename) or []})
            else:
                result.add_lines({filename: data.lines(filename) or []})
    result.write()
    coverage = Coverage(data_file=str(OUTPUT / '.coverage.combined'), config_file='pyproject.toml')
    coverage.load()
    percentage = coverage.json_report(outfile=str(OUTPUT / 'final_coverage.json'))
    if percentage < 90:
        raise AssertionError('unchanged 90% backend coverage gate failed')
    print(json.dumps(dict(coverage_percent=percentage, fail_under=90, changed_files_use_final_seams_only=True)))


if __name__ == '__main__':
    run()
