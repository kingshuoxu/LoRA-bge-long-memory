#!/usr/bin/env python3
"""Exercise the patched host generator with a fake compiler, without an NDK.
Usage: python3 test_shader_generation.py /path/to/patched/vulkan-shaders-gen.cpp
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    binary = root / 'generator'
    subprocess.run(['c++', '-std=c++17', '-pthread', '-DGGML_VULKAN_BUILD_ADRENO_SHADERS',
                    sys.argv[1], '-o', str(binary)], check=True)
    compiler = root / 'glslc'
    compiler.write_text('''#!/usr/bin/env python3
import os, pathlib, sys
if os.environ.get('FAKE_FAIL') == 'late' and len(list(pathlib.Path(sys.argv[sys.argv.index('-o') + 1]).parent.glob('*.spv'))) > 3: sys.exit(9)
if os.environ.get('FAKE_FAIL') == 'loud':
    print('error' * 30000, file=sys.stderr)
    sys.exit(9)
if os.environ.get('FAKE_FAIL') == 'silent': sys.exit(9)
if os.environ.get('FAKE_FAIL') == 'empty': sys.exit(0)
if os.environ.get('FAKE_FAIL') == 'warning': print('warning: test', file=sys.stderr)
args = sys.argv[1:]
pathlib.Path(args[args.index('-o') + 1]).write_bytes(b'\\x03\\x02\\x23\\x07')
if '-MF' in args:
    pathlib.Path(args[args.index('-MF') + 1]).write_text('shader: source')
''')
    compiler.chmod(0o755)
    for mode in ('success', 'warning', 'silent', 'empty', 'loud', 'late', 'missing'):
        output = root / mode
        output.mkdir()
        target = output / 'shaders.cpp'
        result = subprocess.run([str(binary), '--glslc', str(compiler) if mode != 'missing' else str(root / 'missing'),
            '--source', 'mul_mm.comp', '--output-dir', str(output),
            '--target-hpp', str(output / 'shaders.hpp'), '--target-cpp', str(target)],
            env={**os.environ, 'FAKE_FAIL': mode}, capture_output=True, text=True, timeout=120)
        if mode in ('success', 'warning'):
            assert result.returncode == 0, result.stderr
            count = len(list(output.glob('*.spv')))
            assert count > 100, count
            assert target.stat().st_size > 100, 'missing embedded shaders'
            assert "adreno_" in target.read_text(), "missing Adreno shader variants"
            print(f'PASS: {count} shader variants generated')
        else:
            assert result.returncode != 0, f'{mode} compiler failure was ignored'
            assert not target.exists(), 'partial generated C++ was published'
            print(f'PASS: {mode} compiler failure stops generation')
