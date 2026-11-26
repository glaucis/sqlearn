/// @file
/// Filling and summing a Buffer<double> of a million elements: the cost of
/// the raw layer's view against the memory it walks.
#define ANKERL_NANOBENCH_IMPLEMENT
#include <nanobench.h>

#include "raw/buffer.hpp"

#include <cstddef>
#include <cstdint>
#include <exception>
#include <iostream>
#include <span>

namespace {

/// The elements each run fills and sums.
constexpr std::size_t elements = 1'000'000;

/// The fewest iterations nanobench times in each epoch.
constexpr std::uint64_t min_epoch_iterations = 100;

/// Run the benchmarks and print nanobench's table.
void run() {
    sq::raw::Buffer<double> buffer(elements);
    ankerl::nanobench::Bench bench;
    bench.title("raw::Buffer<double> of 1e6")
        .unit("element")
        .batch(elements)
        .minEpochIterations(min_epoch_iterations);

    bench.run("fill", [&] {
        std::size_t i = 0;
        for (auto &element : buffer.span()) {
            element = static_cast<double>(i++);
        }
        ankerl::nanobench::doNotOptimizeAway(buffer.span().data());
    });

    bench.run("sum", [&] {
        double sum = 0.0;
        for (const auto element : buffer.span()) {
            sum += element;
        }
        ankerl::nanobench::doNotOptimizeAway(sum);
    });
}

} // namespace

/// Run the benchmarks; an exception is reported, never let out of main.
/// @return 0, or 1 when a benchmark threw.
int main() {
    try {
        run();
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
