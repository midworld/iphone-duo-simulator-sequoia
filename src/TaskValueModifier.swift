import SwiftUI

// The plugin also embeds the frozen legacy modifier directly. Its exact
// three-field layout must stay identical to Apple's published SDK layout.
@frozen public nonisolated struct _TaskValueModifier<Value: Equatable>: ViewModifier {
    public var action: @Sendable () async -> Void
    public var priority: TaskPriority
    public var value: Value

    @inlinable public init(value: Value, priority: TaskPriority,
                          action: @escaping @Sendable () async -> Void) {
        self.action = action
        self.priority = priority
        self.value = value
    }

    @MainActor public func body(content: Content) -> some View {
        content.modifier(_TaskValueModifier2(id: value, name: "legacy task",
                                             executorPreference: nil,
                                             priority: priority, action: action))
    }
}

// Same dynamic generic shape and initializer ABI as the unavailable SwiftUI
// modifier. The actual lifecycle uses public onAppear/onChange/onDisappear
// callbacks and a cancellable Task on the old runtime.
public nonisolated struct _TaskValueModifier2<ID: Equatable>: ViewModifier {
    private let id: ID
    private let executor: (any TaskExecutor)?
    private let priority: TaskPriority
    private let action: @isolated(any) () async -> Void
    @State private var running: Task<Void, Never>?

    public nonisolated init(id: ID, name: String, executorPreference: (any TaskExecutor)?,
                           priority: TaskPriority,
                           action: sending @escaping @isolated(any) () async -> Void) {
        self.id = id
        self.executor = executorPreference
        self.priority = priority
        self.action = action
    }

    @MainActor public func body(content: Content) -> some View {
        content
            .onAppear { restart() }
            .onChange(of: id) { _, _ in restart() }
            .onDisappear {
                running?.cancel()
                running = nil
            }
    }

    @MainActor private func restart() {
        running?.cancel()
        // The new executor preference is not a reliable old-runtime input.
        // Preserve the action's own actor isolation and the task's priority.
        let operation = action
        running = Task(priority: priority) { @MainActor in await operation() }
    }
}
