import Foundation

// ABI-compatible allocating initializer used by Swift's bundle lookup in the
// new plugin. Only a local copy binds this unavailable Foundation entry point
// here; all other Foundation symbols are reexported from the host framework.
extension Bundle {
  @_silgen_name("$sSo8NSBundleC10FoundationE11__dsoHandleABSgSV_tcfC")
  public convenience init?(compatDSO dsoHandle: UnsafeRawPointer) {
    // The SDK already supplies a complete pre-macOS-26 fallback for this
    // older public spelling. With deployment target 15 it runs that fallback.
    self.init(_dsoHandle: dsoHandle)
  }
}
