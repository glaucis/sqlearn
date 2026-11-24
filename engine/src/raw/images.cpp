/// @file
/// The loaded images, from dyld on macOS and dl_iterate_phdr elsewhere.
#include "raw/images.hpp"

#include <cstddef>
#include <cstdint>
#include <span>

#if defined(__APPLE__)
#include <mach-o/dyld.h>
#include <mach-o/getsect.h>
#include <mach-o/loader.h>
// ucontext_t and its machine state alone: <ucontext.h> declares the
// deprecated context routines, and refuses to compile without
// _XOPEN_SOURCE.
#include <sys/ucontext.h> // IWYU pragma: keep
// IWYU pragma: no_include <ucontext.h>
// IWYU pragma: no_include <arm/_mcontext.h>
// IWYU pragma: no_include <mach/arm/_structs.h>
#else
#include <link.h>
#include <ucontext.h>
#endif

namespace sq::raw {

#if defined(__APPLE__)

std::size_t loaded_images(std::span<Image> out) noexcept {
    std::size_t count = 0;
    const std::uint32_t total = _dyld_image_count();
    for (std::uint32_t i = 0; i < total && count < out.size(); ++i) {
        const mach_header *header = _dyld_get_image_header(i);
        if (header == nullptr || header->magic != MH_MAGIC_64) {
            continue;
        }
        unsigned long size = 0;
        // Every image sqlearn runs in is 64-bit (MH_MAGIC_64 above).
        const auto *header64 = reinterpret_cast<const mach_header_64 *>(header);
        const std::uint8_t *text = getsegmentdata(header64, "__TEXT", &size);
        if (text == nullptr) {
            continue;
        }
        Image &image = out[count];
        image.load = reinterpret_cast<std::uintptr_t>(header);
        image.start = reinterpret_cast<std::uintptr_t>(text);
        image.end = image.start + size;
        image.path = _dyld_get_image_name(i);
        ++count;
    }
    return count;
}

#else

namespace {

/// Where dl_iterate_phdr's callback writes.
struct Filling {
    std::span<Image> out; ///< The images' room.
    std::size_t count;    ///< How many are written.
};

/// dl_iterate_phdr's callback: one image, each executable segment's range
/// joined into one.
/// @param info The image.
/// @param size The size of `info`.
/// @param data The Filling.
/// @return 0 to go on, 1 when `out` is full.
int add_image(dl_phdr_info *info, std::size_t size, void *data) noexcept {
    (void)size;
    auto &filling = *static_cast<Filling *>(data);
    if (filling.count == filling.out.size()) {
        return 1;
    }
    std::uintptr_t start = UINTPTR_MAX;
    std::uintptr_t end = 0;
    for (ElfW(Half) i = 0; i < info->dlpi_phnum; ++i) {
        const ElfW(Phdr) &segment = info->dlpi_phdr[i];
        if (segment.p_type == PT_LOAD && (segment.p_flags & PF_X) != 0) {
            const std::uintptr_t first = info->dlpi_addr + segment.p_vaddr;
            start = first < start ? first : start;
            end = first + segment.p_memsz > end ? first + segment.p_memsz : end;
        }
    }
    if (end == 0) {
        return 0;
    }
    Image &image = filling.out[filling.count];
    image.load = info->dlpi_addr;
    image.start = start;
    image.end = end;
    // The program itself has an empty name.
    image.path =
        info->dlpi_name != nullptr && info->dlpi_name[0] != '\0' ? info->dlpi_name : nullptr;
    ++filling.count;
    return 0;
}

} // namespace

std::size_t loaded_images(std::span<Image> out) noexcept {
    Filling filling{out, 0};
    dl_iterate_phdr(add_image, &filling);
    return filling.count;
}

#endif

const Image *image_of(std::span<const Image> images, std::uintptr_t address) noexcept {
    for (const Image &image : images) {
        if (address >= image.start && address < image.end) {
            return &image;
        }
    }
    return nullptr;
}

std::uintptr_t context_pc(const void *context) noexcept {
    if (context == nullptr) {
        return 0;
    }
    const auto *ucontext = static_cast<const ucontext_t *>(context);
#if defined(__APPLE__) && defined(__aarch64__)
    // NOLINTNEXTLINE(misc-include-cleaner): the SDK's accessor, from <sys/ucontext.h>
    return __darwin_arm_thread_state64_get_pc(ucontext->uc_mcontext->__ss);
#elif defined(__APPLE__) && defined(__x86_64__)
    return ucontext->uc_mcontext->__ss.__rip;
#elif defined(__linux__) && defined(__aarch64__)
    return ucontext->uc_mcontext.pc;
#elif defined(__linux__) && defined(__x86_64__)
    return static_cast<std::uintptr_t>(ucontext->uc_mcontext.gregs[REG_RIP]);
#else
    (void)ucontext;
    return 0;
#endif
}

std::uintptr_t address_of(const void *pointer) noexcept {
    return reinterpret_cast<std::uintptr_t>(pointer);
}

} // namespace sq::raw
