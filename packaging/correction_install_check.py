"""Run the no-model correction contract against packaged runtime/modules.

Host invocation finds unpacked app resources and re-execs their Python. The
--installed invocation verifies imports and runs source test definitions against
installed implementation, not the checkout's memory_core.
"""
from pathlib import Path
import os
import subprocess
import sys

repo = Path(__file__).resolve().parents[1]
if len(sys.argv) == 1:
    candidates = []
    for script in (repo / 'desktop' / 'dist').rglob('e2e-check.sh'):
        resources = script.parent
        python = resources / 'runtime' / ('python.exe' if os.name == 'nt' else 'bin/python3')
        if python.is_file() and (resources / 'app' / 'memory_core').is_dir():
            candidates.append((resources, python))
    if len(candidates) != 1:
        raise RuntimeError(f'Expected one installed runtime, found {candidates}')
    resources, python = candidates[0]
    env = dict(os.environ, PYTHONPATH=str(resources/'app'))
    env['LD_LIBRARY_PATH'] = str(resources/'runtime'/'lib') + os.pathsep + env.get('LD_LIBRARY_PATH','')
    subprocess.run([str(python), str(Path(__file__).resolve()), '--installed', str(resources/'app')], env=env, cwd=resources, check=True)
else:
    import importlib.util
    import unittest
    installed = Path(sys.argv[2]).resolve()
    sys.path.insert(0, str(installed))
    import memory_core.service
    assert Path(memory_core.service.__file__).resolve().is_relative_to(installed), memory_core.service.__file__
    suite = unittest.TestSuite()
    for name in ('test_correction_store', 'test_correction_immediate', 'test_correction_adapter'):
        spec = importlib.util.spec_from_file_location(name, repo/'tests'/f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print('PACKAGED_CORRECTION_OK', memory_core.service.__file__)
