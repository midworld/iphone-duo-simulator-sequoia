// Import through the SDK's public umbrella; the ABI remains RealityFoundation.
import RealityKit

// The new protocol adds no requirements beyond Component. The plugin only
// imports its OpacityComponent witness table; keep this conformance local to
// the compatibility library and alias that one table at link time.
public protocol LegacyImplicitComponent: Component {}
extension OpacityComponent: LegacyImplicitComponent {}

extension Entity.ComponentSet {
    @_silgen_name("$s10RealityKit6EntityC12ComponentSetV0A10FoundationE3setyyxAF028_ImplicitlyAnimatableBuiltinD0RzlF")
    @MainActor public func setWithoutImplicitAnimation<C: LegacyImplicitComponent>(_ component: C) {
        setPlain(component)
    }

    @MainActor private func setPlain<C: Component>(_ component: C) {
        set(component)
    }
}

// Used as the task identity of the plugin's fixed, bundled model catalog.
// Compare all publicly observable configuration-set contents. This does not
// emulate private combination/entity identity semantics of newer RealityKit.
extension Entity.ConfigurationCatalog: @retroactive Equatable {
    public static func == (lhs: Self, rhs: Self) -> Bool {
        let left = lhs.configurationSets
        let right = rhs.configurationSets
        guard left.keys.sorted() == right.keys.sorted() else { return false }
        for (key, value) in left {
            guard let other = right[key], value.id == other.id,
                  value.defaultConfiguration.id == other.defaultConfiguration.id,
                  value.configurations.mapValues({ $0.id }) == other.configurations.mapValues({ $0.id }) else {
                return false
            }
        }
        return true
    }
}
