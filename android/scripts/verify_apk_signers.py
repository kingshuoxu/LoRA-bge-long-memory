#!/usr/bin/env python3
"""Fail-closed APK signer comparison across apksigner output versions."""
import pathlib
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

def certificate_digest(report):
    # AOSP changed "#1" to an SDK range; compare identities, not labels.
    pattern = r"^Signer (?:#\d+|\(minSdkVersion=\d+, maxSdkVersion=\d+\)) certificate SHA-256 digest: ([0-9a-fA-F]{64})$"
    digests = set()
    for line in report.splitlines():
        if "certificate SHA-256 digest:" not in line:
            continue
        match = re.fullmatch(pattern, line.strip())
        if not match:
            raise ValueError("Unrecognized signer certificate output")
        digests.add(match.group(1).lower())
    if len(digests) != 1:
        raise ValueError("Expected exactly one signing certificate identity")
    return next(iter(digests))

def verify(signer, baseline, candidate, stage):
    identities = []
    for name, apk in (("baseline", baseline), ("candidate", candidate)):
        result = subprocess.run([signer, "verify", "--print-certs", apk],
                                capture_output=True, text=True)
        report = result.stdout + result.stderr
        pathlib.Path(stage, name + "-signer.txt").write_text(report)
        if result.returncode != 0:
            raise ValueError(name + " APK signature verification failed; see signer report")
        identities.append(certificate_digest(result.stdout))
    if identities[0] != identities[1]:
        raise ValueError("Baseline and candidate APK signing certificates differ")
    print("Baseline and candidate APK signing certificates match")

class CertificateTests(unittest.TestCase):
    def test_verification_exit_is_required(self):
        result = subprocess.CompletedProcess([], 1, "Signer #1 certificate SHA-256 digest: " + "a"*64, "")
        with patch("subprocess.run", return_value=result), patch.object(pathlib.Path, "write_text"):
            with self.assertRaises(ValueError):
                verify("signer", "base", "candidate", "stage")

    def test_match_and_mismatch(self):
        def result(value):
            return subprocess.CompletedProcess([], 0, "Signer #1 certificate SHA-256 digest: " + value*64, "")
        with patch("subprocess.run", side_effect=[result("a"), result("a")]), patch.object(pathlib.Path, "write_text"):
            verify("signer", "base", "candidate", "stage")
        with patch("subprocess.run", side_effect=[result("a"), result("b")]), patch.object(pathlib.Path, "write_text"):
            with self.assertRaises(ValueError):
                verify("signer", "base", "candidate", "stage")

    def test_legacy(self):
        self.assertEqual(certificate_digest("Signer #1 certificate SHA-256 digest: " + "a"*64), "a"*64)
    def test_ranges(self):
        self.assertEqual(certificate_digest("\n".join(
            "Signer (minSdkVersion=" + str(a) + ", maxSdkVersion=" + str(b) + ") certificate SHA-256 digest: " + "B"*64
            for a, b in ((24, 32), (33, 2147483647)))), "b"*64)
    def test_reject_missing_malformed_or_multiple(self):
        for report in ("", "Signer #1 public key SHA-256 digest: " + "a"*64,
                       "Signer #1 certificate SHA-256 digest: abc",
                       "Signer #1 certificate SHA-256 digest: " + "a"*64 + "\nSigner #2 certificate SHA-256 digest: " + "b"*64):
            with self.assertRaises(ValueError):
                certificate_digest(report)

if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        unittest.main(argv=[sys.argv[0]])
    else:
        try:
            verify(*sys.argv[1:])
        except (ValueError, OSError) as exc:
            sys.exit(str(exc))
