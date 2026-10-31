//
//  ManagedCriticalState.swift
//  ObservationShim
//
//  Copyright (c) 2026 Jacob Fielding
//

import Foundation

final class _ManagedCriticalState<State: Sendable>: @unchecked Sendable {
  private let lock = NSRecursiveLock()
  private var state: State

  init(_ initial: State) {
    state = initial
  }

  func withCriticalRegion<R>(
    _ critical: (inout State) throws -> R
  ) rethrows -> R {
    try lock.withLock {
      try critical(&state)
    }
  }
}
