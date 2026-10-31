#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>
#import <QuartzCore/QuartzCore.h>
#import <objc/runtime.h>

// Preserve the existing dynamic-range compatibility shim.
NSString * const CADynamicRangeHigh = @"high";

static id legacyPreferredDynamicRange(CALayer *layer, SEL selector) {
    return layer.wantsExtendedDynamicRangeContent ? @"high" : @"standard";
}

static void legacySetPreferredDynamicRange(CALayer *layer, SEL selector, NSString *range) {
    layer.wantsExtendedDynamicRangeContent = [range isEqualToString:@"high"];
}

// On Sequoia, the plugin's opaque 3D screen surfaces cover its separate live
// framebuffer hosts. Keep each host's native placement/mesh, but composite the
// screen group above the RealityRenderer group. This changes neither simulator
// geometry nor the input view, and only runs in this disposable compatibility app.
static BOOL isDuoScreenHost(NSView *view) {
    NSString *name=NSStringFromClass(view.class);
    return [name hasPrefix:@"_TtGC31CoreDevicePopDeviceKitExtension19ScreenLayerHostView"];
}

static void placeDuoScreenGroup(NSView *view) {
    if (!isDuoScreenHost(view)) return;
    CALayer *group=view.superview.layer;
    if (group != nil) group.zPosition=100;
}

static void placeExistingScreenGroups(NSView *view) {
    placeDuoScreenGroup(view);
    for(NSView *child in view.subviews) placeExistingScreenGroups(child);
}

__attribute__((constructor)) static void installLegacyCompatibility(void) {
    Class layer=CALayer.class;
    SEL getter=NSSelectorFromString(@"preferredDynamicRange");
    SEL setter=NSSelectorFromString(@"setPreferredDynamicRange:");
    if (!class_getInstanceMethod(layer,getter)) {
        class_addMethod(layer,getter,(IMP)legacyPreferredDynamicRange,"@@:");
    }
    if (!class_getInstanceMethod(layer,setter)) {
        class_addMethod(layer,setter,(IMP)legacySetPreferredDynamicRange,"v@:@");
    }

    if (![NSBundle.mainBundle.bundleIdentifier isEqualToString:@"local.devicehub.SequoiaCompat"]
        || NSProcessInfo.processInfo.operatingSystemVersion.majorVersion != 15) return;

    SEL selector=@selector(viewDidMoveToSuperview);
    Method method=class_getInstanceMethod(NSView.class,selector);
    void (*original)(id,SEL)=(void (*)(id,SEL))method_getImplementation(method);
    IMP replacement=imp_implementationWithBlock(^(NSView *view) {
        original(view,selector);
        if (isDuoScreenHost(view)) {
            placeDuoScreenGroup(view);
            // SwiftUI may not have installed the enclosing backing layer yet.
            dispatch_async(dispatch_get_main_queue(),^{ placeDuoScreenGroup(view); });
        }
    });
    method_setImplementation(method,replacement);
    dispatch_async(dispatch_get_main_queue(),^{
        for(NSWindow *window in NSApplication.sharedApplication.windows)
            placeExistingScreenGroups(window.contentView);
    });
    NSLog(@"[DeviceHubCompositing] Sequoia screen-group compositing workaround installed");
}
