/// @file
/// The images (the program and its shared libraries) loaded in this
/// process, with the address range of each one's code: taken once, outside
/// any signal handler, so that a handler can name the image a stack
/// address falls in without asking the loader, which is not signal-safe.
/// Reading the loader's headers is the raw layer's work (ADR 0065).
#pragma once

#include <cstddef>
#include <cstdint>
#include <span>

namespace sq::raw {

/// One loaded image.
struct Image {
    std::uintptr_t load = 0;  ///< Its load address, as atos -l takes it.
    std::uintptr_t start = 0; ///< The first address of its code.
    std::uintptr_t end = 0;   ///< The address just past its code.
    /// Its path, as the loader keeps it, valid while the image is loaded;
    /// null for one the loader gives no name.
    const char *path = nullptr;
};

/// Fill `out` with the images loaded now, as many as fit. Not
/// async-signal-safe: call it before a handler needs it.
/// @param out Where to put them.
/// @return How many were written.
std::size_t loaded_images(std::span<Image> out) noexcept;

/// Return the image whose code holds `address`. Async-signal-safe.
/// @param images Images from loaded_images.
/// @param address A code address.
/// @return The image, or null when none holds it.
[[nodiscard]] const Image *image_of(std::span<const Image> images, std::uintptr_t address) noexcept;

/// Return the program counter a signal handler's context holds: the
/// instruction that faulted, for a fault. The stack's unwinding steps from
/// the signal's frame to the faulting function's caller when that function
/// keeps no frame record (a leaf), so a report takes the instruction from
/// here. Async-signal-safe.
/// @param context The third argument of an SA_SIGINFO handler, or null.
/// @return The address, or 0 when there is no context or the platform is
///         not one sqlearn reads it on (macOS and Linux on arm64 and x86-64).
[[nodiscard]] std::uintptr_t context_pc(const void *context) noexcept;

/// Return `pointer`'s address as a number, for a report to print it.
/// @param pointer Any pointer, null included.
/// @return Its address.
[[nodiscard]] std::uintptr_t address_of(const void *pointer) noexcept;

} // namespace sq::raw
