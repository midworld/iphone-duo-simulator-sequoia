// Compatibility for the sole unavailable Swift runtime import of this plugin.
// Upstream algorithm/signature: swiftlang/swift, stdlib/public/runtime/Heap.cpp,
// swift_coroFrameAlloc(size_t, MallocTypeId): minimum one byte, malloc-family
// allocation with the supplied type ID. The host's normal free path remains.
#include <malloc/malloc.h>
#include <stdint.h>
#include <stdlib.h>

__attribute__((swiftcall, visibility("default")))
void *swift_coroFrameAlloc(size_t size, uint64_t typeID) {
    void *result = malloc_type_malloc(size ? size : 1, typeID);
    if (!result) abort();
    return result;
}
