#!/usr/bin/env python3
"""Rebuild the tested 27A9275/Sequoia compatibility app from local Apple files.

Never patches an installed Xcode or shared component. Refuses unknown inputs
and existing output directories. No sudo, downloads, launch, or global defaults.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent.parent
IDENTIFIER = "local.devicehub.SequoiaCompat"  # Also scoped in QuartzCompat.m.
SUPPORTED_SWIFT_VERSIONS = {"6.2.3", "6.2.4"}
INPUTS = {
    "Contents/Applications/DeviceHub.app/Contents/MacOS/DeviceHub":
        "0a97f2c3ef3cc1b72feaf5561882ac7b86ed43d5399187c0f5bd0d78197f1f2b",
    "Contents/SharedFrameworks/DeviceKit.framework/Versions/A/DeviceKit":
        "30de60c70b766c51d02d72c6fa6714abdc60b4de40e790359ec4c79243b2552e",
    "Contents/SharedFrameworks/DeviceKit.framework/Versions/A/PlugIns/"
    "CoreDevicePopDeviceKitExtension.devicekitplugin/Contents/MacOS/"
    "CoreDevicePopDeviceKitExtension":
        "d29e71b34571f30e5744b8337d6c195a22d254b40551cd17360ee47e2068ad55",
}
GATES = [
    (0x42D084, "a00f0036", "HIDManager observation setup"),
    (0x42DACC, "e0120036", "HIDManager observation setup"),
    (0x42DEA0, "e0120036", "HIDManager async resume"),
    (0x499F20, "c0140036", "DeviceInteractionModel observation setup"),
    (0x4A51E4, "80140036", "usage assertion observation setup"),
    (0x4AD820, "c0180036", "interaction state observation setup"),
    (0x4A96CC, "a0130036", "usage assertion silent early return"),
    (0x4DFB6C, "80080036", "DeviceStateTracker alternate setup"),
    (0x4E0028, "60080036", "DeviceStateTracker setup"),
    (0x585338, "800d0036", "accessibility observation setup"),
]
OBSERVATION_SYMBOLS = [
    "_$s11Observation12ObservationsV17makeAsyncIteratorAC0E0Vyxq__GyF",
    "_$s11Observation12ObservationsV8IteratorV4next9isolationxSgScA_pSgYi_tYaq_YKF",
    "_$s11Observation12ObservationsVyACyxq_GxyYbq_YKYAccfC",
    "_$s11Observation12ObservationsV8IteratorV4next9isolationxSgScA_pSgYi_tYaq_YKFTu",
    "_$s11Observation12ObservationsVMn",
    "_$s11Observation12ObservationsV8IteratorVMn",
    "_$s11Observation12ObservationsVyxq_GSciAAMc",
]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(*args, capture=False):
    command = [str(a) for a in args]
    if not capture:
        print("+", " ".join(command), flush=True)
    return subprocess.run(command, check=True, env=ENV, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_plist(path):
    return plistlib.loads(path.read_bytes())


def save_plist(path, value):
    path.write_bytes(plistlib.dumps(value))


def patch_instructions(path, sites):
    data = bytearray(path.read_bytes())
    for offset, old, new, _ in sites:
        require(data[offset:offset + 4].hex() == old,
                f"Instruction mismatch: {path.name} +{offset:#x}")
    for offset, old, new, reason in sites:
        data[offset:offset + 4] = bytes.fromhex(new)
        PATCHES.append(dict(binary=path.name, offset=hex(offset),
                            original=old, replacement=new, reason=reason))
    path.write_bytes(data)


def redirect_observations(path, exports, require_all):
    data = path.read_bytes()
    found = 0
    for original in sorted(OBSERVATION_SYMBOLS, key=len, reverse=True):
        replacement = original.replace("11Observation12Observations", "11BackportObs12Observations")
        replacement = replacement.replace("17makeAsyncIteratorAC0E0V", "17makeAsyncIteratorAC0F0V")
        require(len(original) == len(replacement), "Symbol length changed")
        require(replacement in exports, f"Backport export missing: {replacement}")
        count = data.count(original.encode())
        require(count > 0 or not require_all, f"Expected import missing: {original}")
        found += count
        data = data.replace(original.encode(), replacement.encode())
    require(found > 0, f"No Observations symbols in {path.name}")
    path.write_bytes(data.replace(b"11Observation12Observations", b"11BackportObs12Observations"))
    run("/usr/bin/install_name_tool", "-change", "/usr/lib/swift/libswiftObservation.dylib",
        "@rpath/libBackportObs.dylib", path)


def swift_library(module, sources, library, reexport, extra=()):
    run("/usr/bin/xcrun", "swiftc", "-emit-library", "-O", "-enable-library-evolution",
        "-swift-version", "5", "-module-name", module, "-target", "arm64e-apple-macosx15.0",
        *[HERE / "src" / source for source in sources],
        "-Xlinker", "-install_name", "-Xlinker", f"@rpath/{library.name}",
        *reexport, *extra, "-o", library)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xcode", required=True, type=Path,
                        help="Official Xcode 27.1 (27A9275), base files unmodified")
    parser.add_argument("--compiler-xcode", required=True, type=Path,
                        help="Sequoia-compatible Xcode 26.3 (17C529)")
    parser.add_argument("--output", required=True, type=Path,
                        help="New directory outside both Xcodes and this source package")
    args = parser.parse_args()
    xcode = args.xcode.expanduser().resolve()
    compiler = args.compiler_xcode.expanduser().resolve()
    output = args.output.expanduser().resolve()
    require(platform.system() == "Darwin" and platform.machine() == "arm64",
            "Native Apple Silicon macOS is required")
    host_version = platform.mac_ver()[0]
    require(not output.exists(), "Output already exists; choose a new directory")
    for source in (xcode, compiler, HERE):
        require(source != output and source not in output.parents and output not in source.parents,
                "Output must be separate from inputs")
    require(load_plist(xcode / "Contents/version.plist")["ProductBuildVersion"] == "27A9275",
            "Wrong source Xcode build")
    require(load_plist(compiler / "Contents/version.plist")["ProductBuildVersion"] == "17C529",
            "Wrong compiler Xcode build; other compilers are not validated")
    for relative, expected in INPUTS.items():
        require(sha(xcode / relative) == expected, f"Wrong pristine input: {relative}")
    ENV["DEVELOPER_DIR"] = str(compiler / "Contents/Developer")
    ENV["TOOLCHAINS"] = "com.apple.dt.toolchain.XcodeDefault"
    # Avoid inherited build/injection settings silently changing ABI or signing.
    for key in list(ENV):
        if key.startswith("DYLD_") or key in ("SDKROOT", "SWIFT_EXEC", "MACOSX_DEPLOYMENT_TARGET"):
            ENV.pop(key)
    compiler_version = run("/usr/bin/xcrun", "swiftc", "--version", capture=True)
    swift_version = re.search(r"(?m)^Apple Swift version (\d+\.\d+\.\d+)(?=\s|\(|$)", compiler_version)
    require(swift_version is not None and swift_version.group(1) in SUPPORTED_SWIFT_VERSIONS,
            "Swift 6.2.3 or 6.2.4 is required")
    sdk = Path(run("/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path", capture=True).strip())
    output.mkdir(parents=True)
    app = output / "DeviceHub-Duo.app"
    source_app = xcode / "Contents/Applications/DeviceHub.app"
    framework = app / "Contents/Frameworks/DeviceKit.framework"
    run("/usr/bin/ditto", source_app, app)
    framework.parent.mkdir(exist_ok=True)
    run("/usr/bin/ditto", xcode / "Contents/SharedFrameworks/DeviceKit.framework", framework)
    main_binary = app / "Contents/MacOS/DeviceHub"
    kit = framework / "Versions/A/DeviceKit"
    plugin = framework / "Versions/A/PlugIns/CoreDevicePopDeviceKitExtension.devicekitplugin"
    pop = plugin / "Contents/MacOS/CoreDevicePopDeviceKitExtension"
    info = load_plist(app / "Contents/Info.plist")
    info.update(CFBundleExecutable="DeviceHub", CFBundleIdentifier=IDENTIFIER,
                CFBundleName="Device Hub Duo Repair", CFBundleDisplayName="Device Hub Duo Repair",
                LSMinimumSystemVersion=host_version)
    info.pop("CFBundleURLTypes", None)
    save_plist(app / "Contents/Info.plist", info)
    shutil.move(str(app / "Contents/MacOS/DevicesTrampoline"), str(output / "DevicesTrampoline.original"))
    plugin_info = load_plist(plugin / "Contents/Info.plist")
    plugin_info["LSMinimumSystemVersion"] = host_version
    save_plist(plugin / "Contents/Info.plist", plugin_info)
    raw = run("/usr/bin/codesign", "-d", "--entitlements", ":-",
              source_app / "Contents/MacOS/DeviceHub", capture=True)
    entitlements = {key: value for key, value in plistlib.loads(raw.encode()).items()
                    if key.startswith("com.apple.security.")
                    and key != "com.apple.security.attestation.access"}
    require(entitlements.get("com.apple.security.app-sandbox") is True, "Sandbox missing")
    entitlements["com.apple.security.cs.disable-library-validation"] = True
    entitlement_file = output / "local-entitlements.plist"
    save_plist(entitlement_file, entitlements)
    libs = framework.parent
    swift_library("BackportObs", ["Observations.swift", "ManagedCriticalState.swift"],
                  libs / "libBackportObs.dylib",
                  ["-Xlinker", "-reexport_library", "-Xlinker", sdk / "usr/lib/swift/libswiftObservation.tbd"])
    swift_library("DuoFoundationCompat", ["BundleShim.swift"], libs / "libDuoFoundationCompat.dylib",
                  ["-Xlinker", "-reexport_framework", "-Xlinker", "Foundation"])
    aliases = [
        ("_$s17RealityFoundation16OpacityComponentV03DuoA6Compat014LegacyImplicitD0ADWP",
         "_$s17RealityFoundation16OpacityComponentVAA028_ImplicitlyAnimatableBuiltinD0AAWP"),
        ("_$s10RealityKit6EntityC0A10FoundationE20ConfigurationCatalogVSQ03DuoA6CompatMc",
         "_$s10RealityKit6EntityC0A10FoundationE20ConfigurationCatalogVSQADMc"),
    ]
    alias_flags = []
    for original, alias in aliases:
        alias_flags.extend(["-Xlinker", "-alias", "-Xlinker", original, "-Xlinker", alias])
    swift_library("DuoRealityCompat", ["RealityCompat.swift"], libs / "libDuoRealityCompat.dylib",
                  ["-Xlinker", "-reexport_framework", "-Xlinker", "RealityFoundation"], alias_flags)
    ui_aliases = []
    for original, alias in (
        ("_$s7DuoUI1519_TaskValueModifier2VyxG7SwiftUI12ViewModifierAAMc",
         "_$s7DuoUI1519_TaskValueModifier2VyxGAA12ViewModifierAAMc"),
        ("_$s7DuoUI1518_TaskValueModifierVyxG7SwiftUI04ViewE0AAMc",
         "_$s7DuoUI1518_TaskValueModifierVyxGAA04ViewE0AAMc"),
    ):
        ui_aliases.extend(["-Xlinker", "-alias", "-Xlinker", original, "-Xlinker", alias])
    swift_library("DuoUI15", ["TaskValueModifier.swift"], libs / "libDuoUI15.dylib",
                  ["-Xlinker", "-reexport_framework", "-Xlinker", "SwiftUI"], ui_aliases)
    run("/usr/bin/xcrun", "clang", "-dynamiclib", "-fobjc-arc", "-mmacosx-version-min=15.0",
        "-Wall", "-Werror", "-framework", "Foundation", "-framework", "AppKit",
        "-Wl,-reexport_framework,QuartzCore", "-install_name", "@rpath/libDuoQuartzCompat.dylib",
        HERE / "src/QuartzCompat.m", "-o", libs / "libDuoQuartzCompat.dylib")
    run("/usr/bin/xcrun", "clang", "-dynamiclib", "-arch", "arm64e", "-mmacosx-version-min=15.0", "-Wall", "-Werror",
        "-Wl,-reexport_library," + str(sdk / "usr/lib/swift/libswiftCore.tbd"),
        "-install_name", "@rpath/libDuoSwiftRuntimeCompat.dylib", HERE / "src/CoroutineAlloc.c",
        "-o", libs / "libDuoSwiftRuntimeCompat.dylib")
    exports = set(line.split()[-1] for line in
                  run("/usr/bin/nm", "-gU", libs / "libBackportObs.dylib", capture=True).splitlines()
                  if line.split())
    patch_instructions(kit, [(o, b, "1f2003d5", why) for o, b, why in GATES] +
                       [(o, "00008092", "0000f092", "cancellable lifetime sleep: Int64.max")
                        for o in (0x590AC0, 0x591214, 0x5A0B34, 0x5B7238)])
    redirect_observations(kit, exports, require_all=True)
    redirect_observations(pop, exports, require_all=False)
    data = pop.read_bytes()
    require(b"7SwiftUI19_TaskValueModifier2" in data, "New task modifier missing")
    pop.write_bytes(data.replace(b"7SwiftUI19_TaskValueModifier2", b"7DuoUI1519_TaskValueModifier2"))
    # The old, frozen modifier remains bound to the host SwiftUI framework.
    for offset, target in ((0xB840, 0xB858), (0xB8CC, 0xB8FC)):
        old = (0x34000000 | (((target - offset) // 4) << 5)).to_bytes(4, "little").hex()
        patch_instructions(pop, [(offset, old, "1f2003d5", "consistent new task metadata/witness")])
    require(pop.read_bytes()[0xA4CFC:0xA4D00].hex() == "55050014",
            "Native 3D view provider must remain intact")
    for name, version in (("Foundation", "C"), ("RealityFoundation", "A"),
                          ("SwiftUI", "A"), ("QuartzCore", "A")):
        library = "libDuo" + {"Foundation": "FoundationCompat", "RealityFoundation": "RealityCompat",
                              "SwiftUI": "UI15", "QuartzCore": "QuartzCompat"}[name] + ".dylib"
        run("/usr/bin/install_name_tool", "-change",
            f"/System/Library/Frameworks/{name}.framework/Versions/{version}/{name}",
            f"@rpath/{library}", pop)
    run("/usr/bin/install_name_tool", "-change", "/usr/lib/swift/libswiftCore.dylib",
        "@rpath/libDuoSwiftRuntimeCompat.dylib", pop)
    for executable in (main_binary, kit):
        for directory in ("SharedFrameworks", "Frameworks"):
            run("/usr/bin/install_name_tool", "-add_rpath", xcode / "Contents" / directory, executable)
    for library in sorted(libs.glob("*.dylib")):
        run("/usr/bin/codesign", "--force", "--sign", "-", library)
    run("/usr/bin/codesign", "--force", "--sign", "-", plugin)
    run("/usr/bin/codesign", "--force", "--sign", "-", framework)
    run("/usr/bin/codesign", "--force", "--sign", "-", "--identifier", IDENTIFIER,
        "--entitlements", entitlement_file, app)
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", app)
    for relative, expected in INPUTS.items():
        require(sha(xcode / relative) == expected, "Source changed during build")
    manifest = dict(sourceBuild="27A9275", host=host_version,
                    compiler=compiler_version.strip(), bundleIdentifier=IDENTIFIER,
                    inputSHA256=INPUTS, patches=PATCHES, originalsUnchanged=True,
                    signatureVerified=True, launched=False,
                    sourceSHA256={p.name: sha(p) for p in sorted((HERE / "src").iterdir())},
                    note="Build verification is not a clean-machine/runtime certification")
    (output / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("\nBuilt (not launched):", app)
    print("Keep the source Xcode at its current path; external framework rpaths depend on it.")


ENV = dict(os.environ)
PATCHES = []
if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError, KeyError) as error:
        print(f"ERROR: {error}\nPartial output is retained for diagnosis; nothing was auto-deleted.", file=sys.stderr)
        sys.exit(1)
